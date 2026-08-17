"""
patrol.py - 巡檢邏輯模組
定時檢查超時訊息、分批、發通知
通知抑制: pending → (1hr) → reminded_1 → (3hr) → reminded_2 → (6hr) → escalated
可被 cron 每 15 分鐘呼叫
"""

import uuid
from datetime import datetime, timedelta

import database as db
import line_api
import ai_service
import notify
import heartbeat
from config import load_config


def _hours_ago(hours):
    """回傳 N 小時前的 ISO 時間字串"""
    return (datetime.now() - timedelta(hours=hours)).isoformat()


def _check_timeout(msg, first_hr, second_hr, esc_hr):
    """
    檢查單條訊息是否需要升級
    回傳新狀態或 None
    """
    msg_time = datetime.fromisoformat(msg["message_time"])
    now = datetime.now()
    elapsed = now - msg_time

    status = msg["status"]

    if status == "pending" and elapsed >= timedelta(hours=first_hr):
        return "reminded_1"
    elif status == "reminded_1" and elapsed >= timedelta(hours=second_hr):
        return "reminded_2"
    elif status == "reminded_2" and elapsed >= timedelta(hours=esc_hr):
        return "escalated"
    return None


def patrol():
    """
    主巡檢函數
    0. 記錄心跳 (heartbeat)
    1. 檢查所有待回覆訊息是否超時
    2. 建立批次 (batch_id) 將本次巡檢的超時訊息合併成 1 則通知
    3. 通知操作人員 (第一次提醒含 AI 草稿摘要)
    4. 管理員收到升級通知（依設定送往多通道）
    回傳巡檢摘要 dict
    """
    # 記錄心跳，供 heartbeat.py 監控判斷
    heartbeat.record_patrol_beat()

    config = load_config()
    notif_cfg = config.get("notification", {})
    first_hr = notif_cfg.get("first_reminder_hours", 1)
    second_hr = notif_cfg.get("second_reminder_hours", 3)
    esc_hr = notif_cfg.get("escalation_hours", 6)
    suppression = notif_cfg.get("suppression_enabled", True)

    pending_msgs = db.get_pending_messages()

    # 分類超時訊息
    reminded_1_msgs = []   # 從 pending 升級到 reminded_1
    reminded_2_msgs = []   # 從 reminded_1 升級到 reminded_2
    escalated_msgs = []    # 從 reminded_2 升級到 escalated

    for msg in pending_msgs:
        new_status = _check_timeout(msg, first_hr, second_hr, esc_hr)
        if new_status == "reminded_1":
            reminded_1_msgs.append(msg)
        elif new_status == "reminded_2":
            reminded_2_msgs.append(msg)
        elif new_status == "escalated":
            escalated_msgs.append(msg)

    batch_id = str(uuid.uuid4())[:8]
    sent_notifications = 0

    # --- 第一次提醒: 通知操作人員 ---
    if reminded_1_msgs:
        msg_ids = [m["id"] for m in reminded_1_msgs]
        summary = ai_service.summarize_messages(reminded_1_msgs)

        # 為每條訊息生成 AI 草稿
        for m in reminded_1_msgs:
            if not m.get("ai_draft"):
                draft = ai_service.generate_draft(
                    m.get("user_name") or "客戶",
                    m.get("message_text", ""),
                )
                db.update_message(m["id"], ai_draft=draft)

        operators = db.get_operators()
        content = (
            f"【第一次提醒 — {len(reminded_1_msgs)} 條待回覆訊息】\n"
            f"批次: {batch_id}\n\n"
            f"{summary}\n\n"
            f"請儘速登入系統確認並回覆。"
        )
        for op in operators:
            success, _ = line_api.send_message(op["user_id"], content)
            db.add_notification_log(batch_id, "line", op["user_id"], content, msg_ids)
            sent_notifications += 1

        # 更新訊息狀態
        for m in reminded_1_msgs:
            db.update_message_status(m["id"], "reminded_1")
            db.update_message(m["id"], batch_id=batch_id)

    # --- 第二次提醒: 升級通知管理員 ---
    if reminded_2_msgs:
        msg_ids = [m["id"] for m in reminded_2_msgs]
        summary = ai_service.summarize_messages(reminded_2_msgs)
        operators = db.get_operators()
        admins = db.get_admins()

        content = (
            f"【第二次提醒 — {len(reminded_2_msgs)} 條訊息仍待回覆】\n"
            f"批次: {batch_id}\n\n"
            f"{summary}\n\n"
            f"操作人員請儘速處理，管理員請留意進度。"
        )
        targets = (operators + admins)
        for t in targets:
            success, _ = line_api.send_message(t["user_id"], content)
            db.add_notification_log(batch_id, "line", t["user_id"], content, msg_ids)
            sent_notifications += 1

        for m in reminded_2_msgs:
            db.update_message_status(m["id"], "reminded_2")
            db.update_message(m["id"], batch_id=batch_id)

    # --- 嚴重升級通知管理員 ---
    if escalated_msgs:
        msg_ids = [m["id"] for m in escalated_msgs]
        summary = ai_service.summarize_messages(escalated_msgs)
        admins = db.get_admins()
        admin_ids = [a["user_id"] for a in admins]

        content = (
            f"【嚴重延遲 — {len(escalated_msgs)} 條訊息已超過 {esc_hr} 小時未回覆】\n"
            f"批次: {batch_id}\n\n"
            f"{summary}\n\n"
            f"請管理員立即介入處理。"
        )
        # 高優先級：管理員 LINE + 其他已啟用通道，確保不看 LINE 也能收到
        results = notify.notify_all(content, targets=admin_ids)
        for a in admins:
            db.add_notification_log(
                batch_id, "line", a["user_id"], content, msg_ids
            )
        sent_notifications += len(results)

        for m in escalated_msgs:
            db.update_message_status(m["id"], "escalated")
            db.update_message(m["id"], batch_id=batch_id)

    return {
        "batch_id": batch_id,
        "checked": len(pending_msgs),
        "reminded_1": len(reminded_1_msgs),
        "reminded_2": len(reminded_2_msgs),
        "escalated": len(escalated_msgs),
        "notifications_sent": sent_notifications,
        "patrol_time": datetime.now().isoformat(),
    }


if __name__ == "__main__":
    db.init_db()
    result = patrol()
    print(f"巡檢完成: {result}")
