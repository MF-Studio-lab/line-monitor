"""
heartbeat.py - 心跳監控模組
當 patrol 持續一段時間 (max_stale_minutes) 未執行時，判定監控系統可能失效，
自動發送高優先級警報給管理員（LINE / Discord / Telegram / Email 依設定）。
同時可透過永不退出的 watchdog 或 cron 檢查來呼叫。
"""

from datetime import datetime, timedelta

import database as db
import notify
from config import load_config


def record_patrol_beat():
    """巡檢執行時呼叫，記錄心跳。"""
    db.record_heartbeat(source="patrol")


def check_heartbeat(force_alert=False):
    """
    檢查 last heartbeat 是否過期，過期則發送警報並回傳狀態。
    回傳 dict: {healthy, last_beat_at, stale_minutes, alerts: [(channel, success, ...)]}
    """
    config = load_config()
    hb_cfg = config.get("heartbeat", {})
    enabled = hb_cfg.get("enabled", True)
    max_stale = int(hb_cfg.get("max_stale_minutes", 60))

    last = db.get_last_heartbeat(source="patrol")
    if not last:
        stale_minutes = max_stale  # 從未有心跳視為過期
        healthy = False
    else:
        try:
            last_at = datetime.fromisoformat(last["checked_at"])
        except (ValueError, TypeError):
            last_at = None
        if last_at is None:
            healthy = False
            stale_minutes = max_stale
        else:
            stale_minutes = round((datetime.now() - last_at).total_seconds() / 60, 1)
            healthy = stale_minutes <= max_stale

    alerts = []
    if (force_alert or (enabled and not healthy)):
        content = (
            "⚠️【監控系統心跳異常】\n"
            f"patrol 已 {stale_minutes} 分鐘未執行 (上限 {max_stale} 分鐘)。\n"
            "可能原因：伺服器當機 / crontab 失效 / 服務停止。\n"
            "請立即檢查 line-monitor 服務狀態，避免漏接客戶訊息。"
        )
        admins = db.get_admins()
        admin_ids = [a["user_id"] for a in admins]
        # 嚴重警報：送管理員 LINE + 其他所有已啟用通道
        alerts = notify.notify_all(content, targets=admin_ids)

    return {
        "enabled": enabled,
        "max_stale_minutes": max_stale,
        "healthy": healthy,
        "last_beat_at": (last or {}).get("checked_at"),
        "stale_minutes": stale_minutes,
        "alerts": alerts,
    }


if __name__ == "__main__":
    db.init_db()
    result = check_heartbeat()
    print(f"heartbeat healthy={result['healthy']} stale={result['stale_minutes']}min")
    for c, ok, m in result["alerts"]:
        print(f"  alert[{c}]: {'OK' if ok else 'FAIL'} {m}")