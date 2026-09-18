"""
app.py - Flask 主程式
LINE 客戶服務監控系統 Web UI
Port: 8080
"""

import json
import os
import subprocess
import threading
import time
from datetime import datetime

from flask import Flask, request, jsonify, render_template, abort

import database as db
import line_api
import ai_service
from ai_service import classify_intent
import patrol
import notify
import heartbeat
import rag
import print_handler
from config import load_config, save_config, validate_config

app = Flask(__name__)

# 啟動時初始化 DB
db.init_db()

# 用戶最後一則文字訊息快取（user_id -> text），用於圖片/檔案列印關鍵字判斷
_user_last_text = {}
_user_last_text_lock = threading.Lock()


def _get_user_last_text(user_id):
    with _user_last_text_lock:
        return _user_last_text.get(user_id, "")


def _set_user_last_text(user_id, text):
    with _user_last_text_lock:
        _user_last_text[user_id] = text


# 事件去重快取：message_id -> timestamp（避免 LINE 重試導致重複處理）
_processed_message_ids = {}
_processed_message_ids_lock = threading.Lock()
_MESSAGE_ID_TTL = 300  # 5 分鐘


def _is_processed(message_id):
    """檢查 message_id 是否已處理過，若無則標記為已處理並回傳 False"""
    if not message_id:
        return False
    now = time.time()
    with _processed_message_ids_lock:
        # 清理過期
        expired = [mid for mid, ts in _processed_message_ids.items() if now - ts > _MESSAGE_ID_TTL]
        for mid in expired:
            _processed_message_ids.pop(mid, None)
        if message_id in _processed_message_ids:
            return True
        _processed_message_ids[message_id] = now
        return False


# 列印會話管理：user_id -> session dict
# session: { "message_id": str, "message_type": str, "last_text": str, "created_at": float }
_print_sessions = {}
_print_sessions_lock = threading.Lock()
_PRINT_SESSION_TTL = 300  # 5 分鐘


def _create_print_session(user_id, message_id, message_type, last_text):
    """建立列印會話，等待用戶輸入份數"""
    with _print_sessions_lock:
        _print_sessions[user_id] = {
            "message_id": message_id,
            "message_type": message_type,
            "last_text": last_text,
            "created_at": time.time(),
        }


def _get_print_session(user_id):
    """取得用戶的列印會話（若過期則刪除並回傳 None）"""
    with _print_sessions_lock:
        session = _print_sessions.get(user_id)
        if not session:
            return None
        if time.time() - session["created_at"] > _PRINT_SESSION_TTL:
            _print_sessions.pop(user_id, None)
            return None
        return session


def _pop_print_session(user_id):
    """取得並移除用戶的列印會話"""
    with _print_sessions_lock:
        return _print_sessions.pop(user_id, None)


def _clear_expired_print_sessions():
    """清理過期會話"""
    now = time.time()
    with _print_sessions_lock:
        expired = [uid for uid, s in _print_sessions.items() if now - s["created_at"] > _PRINT_SESSION_TTL]
        for uid in expired:
            _print_sessions.pop(uid, None)


# ---------------------------------------------------------------------------
# Web UI Routes
# ---------------------------------------------------------------------------

@app.route("/")
def dashboard():
    """儀表板頁面"""
    stats = db.get_stats()
    pending = db.get_pending_messages()
    config = load_config()
    mttr_hours, mttr_count = db.get_mttr(days=30)
    escalated = db.get_escalated_stats(days=30)
    hb = heartbeat.check_heartbeat(force_alert=False)
    return render_template(
        "dashboard.html",
        stats=stats,
        pending_msgs=pending,
        pending=pending,
        config=config,
        active_page="dashboard",
        mttr=mttr_hours,
        escalated_stats=escalated,
        heartbeat_status=hb,
    )


@app.route("/settings")
def settings_page():
    """設定頁面"""
    config = load_config()
    admins = db.get_admins()
    operators = db.get_operators()
    all_contacts = db.get_contacts()
    return render_template(
        "settings.html",
        settings=config,
        contacts=all_contacts,
        config=config,
        admins=admins,
        operators=operators,
        all_contacts=all_contacts,
        active_page="settings",
    )


@app.route("/messages")
def messages_page():
    """訊息日誌頁面"""
    status_filter = request.args.get("status", "")
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    search = request.args.get("search", "")
    PER_PAGE = 50
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1

    total = db.count_messages(
        status=status_filter or None,
        date_from=date_from or None,
        date_to=date_to or None,
        search=search or None,
    )
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    messages = db.get_messages(
        status=status_filter or None,
        date_from=date_from or None,
        date_to=date_to or None,
        search=search or None,
        limit=PER_PAGE,
        offset=(page - 1) * PER_PAGE,
    )
    config = load_config()
    return render_template(
        "messages.html",
        messages=messages,
        status_filter=status_filter,
        date_from=date_from,
        date_to=date_to,
        search=search,
        config=config,
        active_page="messages",
        page=page,
        total_pages=total_pages,
        current_page=page,
    )


@app.route("/reports")
def reports_page():
    """SLA 報表頁面"""
    config = load_config()
    return render_template(
        "reports.html",
        config=config,
        active_page="reports",
    )


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@app.route("/api/health")
def api_health():
    """健康檢查"""
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0",
    })


@app.route("/api/stats")
def api_stats():
    """取得儀表板統計"""
    return jsonify(db.get_stats())


@app.route("/api/stats/trend")
def api_stats_trend():
    """儀表板趨勢圖資料"""
    trend = db.get_message_trend(days=7)
    return jsonify({
        "labels": [t["date"] for t in trend],
        "messages": [t["count"] for t in trend],
        "replies": [t["replied"] for t in trend],
    })


@app.route("/api/sla")
def api_sla():
    """SLA 報表：MTTR + 延遲類別統計"""
    days = int(request.args.get("days", 30))
    mttr_hours, mttr_count = db.get_mttr(days=days)
    escalated = db.get_escalated_stats(days=days)
    resolved_lags = db.get_resolved_with_times(days=days)
    
    # 計算延遲分布
    lag_buckets = {"0-1hr": 0, "1-3hr": 0, "3-6hr": 0, "6-12hr": 0, "12-24hr": 0, "24hr+": 0}
    for r in resolved_lags:
        h = r["lag_hours"]
        if h <= 1: lag_buckets["0-1hr"] += 1
        elif h <= 3: lag_buckets["1-3hr"] += 1
        elif h <= 6: lag_buckets["3-6hr"] += 1
        elif h <= 12: lag_buckets["6-12hr"] += 1
        elif h <= 24: lag_buckets["12-24hr"] += 1
        else: lag_buckets["24hr+"] += 1
    
    return jsonify({
        "mttr_hours": mttr_hours,
        "mttr_count": mttr_count,
        "escalated": escalated,
        "resolved_count": len(resolved_lags),
        "lag_distribution": lag_buckets,
    })


@app.route("/api/heartbeat/status")
def api_heartbeat_status():
    """心跳狀態"""
    return jsonify(heartbeat.check_heartbeat(force_alert=False))


@app.route("/api/heartbeat/record", methods=["POST"])
def api_heartbeat_record():
    """手動記錄心跳（測試用）"""
    heartbeat.record_patrol_beat()
    return jsonify({"success": True})


@app.route("/api/rag/search")
def api_rag_search():
    """測試知識庫檢索"""
    config = load_config()
    rag_cfg = config.get("rag", {})
    query = request.args.get("q", "")
    if not query or not rag_cfg.get("kb_path"):
        return jsonify({"success": False, "message": "請輸入查詢或設定知識庫路徑"})
    results = rag.retrieve(query, rag_cfg.get("kb_path", ""), int(rag_cfg.get("top_k", 3)))
    return jsonify({
        "success": True,
        "results": [
            {"source": name, "score": score, "snippet": snippet}
            for name, score, snippet in results
        ],
    })


@app.route("/api/rag/rebuild", methods=["POST"])
def api_rag_rebuild():
    """重建知識庫索引"""
    try:
        # 使用 venv 的 python 完整路徑
        venv_python = "/home/green-ai/line-monitor/venv/bin/python"
        result = subprocess.run(
            [venv_python, "scripts/build_kb_index.py"],
            cwd="/home/green-ai/line-monitor",
            capture_output=True,
            text=True,
            timeout=120
        )
        if result.returncode == 0:
            # 清除 rag 快取
            rag.clear_cache()
            return jsonify({"ok": True, "message": "索引重建完成"})
        else:
            return jsonify({"ok": False, "error": f"重建失敗: {result.stderr}"}), 500
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "重建逾時（>120秒）"}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": f"伺服器錯誤: {e}"}), 500


@app.route("/api/notify/test", methods=["POST"])
def api_notify_test():
    """測試指定通知通道連線"""
    data = request.get_json(silent=True) or {}
    channel = data.get("channel", "")
    success, message = notify.test_channel(channel)
    return jsonify({"success": success, "message": message})


@app.route("/api/messages")
def api_messages():
    """取得訊息清單 API"""
    status = request.args.get("status")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    search = request.args.get("search")
    messages = db.get_messages(
        status=status, date_from=date_from, date_to=date_to,
        search=search, limit=500,
    )
    return jsonify(messages)


@app.route("/api/messages/<int:msg_id>/send", methods=["POST"])
def api_send_message(msg_id):
    """確認發送 AI 草稿回覆給客戶，並標記為已處理"""
    data = request.get_json(silent=True) or {}
    msg = db.get_message(msg_id)
    if not msg:
        return jsonify({"ok": False, "error": "訊息不存在"}), 404

    text = data.get("text") or msg.get("ai_draft", "")
    if not text:
        return jsonify({"ok": False, "error": "沒有可發送的內容"}), 400

    success, resp = line_api.send_message(msg["user_id"], text)
    if success:
        db.resolve_message(msg_id, reply_by="admin")
        return jsonify({"ok": True, "response": resp})
    else:
        db.update_message(msg_id, ai_draft=text)
        return jsonify({"ok": False, "error": resp}), 500


@app.route("/api/messages/<int:msg_id>/resolve", methods=["POST"])
def api_resolve_message(msg_id):
    """標記訊息為已處理"""
    data = request.get_json(silent=True) or {}
    reply_by = data.get("reply_by", "admin")
    msg = db.get_message(msg_id)
    if not msg:
        return jsonify({"ok": False, "error": "訊息不存在"}), 404
    db.resolve_message(msg_id, reply_by=reply_by)
    return jsonify({"ok": True})


@app.route("/api/messages/<int:msg_id>/draft", methods=["POST"])
def api_generate_draft(msg_id):
    """重新生成 AI 草稿"""
    msg = db.get_message(msg_id)
    if not msg:
        return jsonify({"error": "訊息不存在"}), 404
    draft = ai_service.generate_draft(
        msg.get("user_name") or "客戶",
        msg.get("message_text", ""),
    )
    db.update_message(msg_id, ai_draft=draft)
    return jsonify({"success": True, "draft": draft})


@app.route("/api/messages/<int:msg_id>", methods=["PUT"])
def api_update_message(msg_id):
    """更新訊息欄位（例如編輯草稿）"""
    data = request.get_json(silent=True) or {}
    msg = db.get_message(msg_id)
    if not msg:
        return jsonify({"error": "訊息不存在"}), 404
    allowed = ["ai_draft", "status"]
    updates = {k: v for k, v in data.items() if k in allowed}
    if updates:
        db.update_message(msg_id, **updates)
    return jsonify({"success": True})


@app.route("/api/patrol/trigger", methods=["POST"])
def api_patrol_trigger():
    """手動觸發巡檢"""
    result = patrol.patrol()
    return jsonify({"success": True, "result": result})


# ---------------------------------------------------------------------------
# Contacts API
# ---------------------------------------------------------------------------

@app.route("/api/contacts", methods=["POST"])
def api_add_contact():
    """新增聯繫人（管理員/操作人員）"""
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id", "").strip()
    name = data.get("name", "").strip()
    role = data.get("role", "customer")
    if not user_id or not name:
        return jsonify({"ok": False, "error": "請輸入 userId 與姓名"}), 400
    if role not in ("admin", "operator"):
        return jsonify({"ok": False, "error": "角色必須為 admin 或 operator"}), 400
    db.add_contact(user_id, name, role=role)
    return jsonify({"ok": True, "message": f"已新增{role == 'admin' and '管理員' or '操作人員'}: {name}"})


@app.route("/api/contacts/<user_id>", methods=["DELETE"])
def api_remove_contact(user_id):
    """移除聯繫人"""
    db.delete_contact(user_id)
    return jsonify({"ok": True, "message": "已移除"})


@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    """取得設定"""
    return jsonify(load_config())


@app.route("/api/settings", methods=["POST"])
def api_post_settings():
    """更新設定：加入錯誤捕捉、移除 flat、統一回傳格式"""
    data = request.get_json(silent=True) or {}
    config = load_config()
    # 深度合併（支援巢狀 section dict 與扁平欄位兩種格式）
    for key, value in data.items():
        if key in config and isinstance(config[key], dict) and isinstance(value, dict):
            config[key].update(value)
        else:
            config[key] = value
    try:
        save_config(config)
        app.logger.info("Settings saved successfully")
        return jsonify({"ok": True, "message": "儲存成功", "config": config})
    except Exception as e:
        app.logger.exception("Save settings failed")
        return jsonify({"ok": False, "error": f"伺服器錯誤: {e}"}), 500


def flatten_config(config, prefix=""):
    """將巢狀設定扁平化，方便模板/前端欄位對應"""
    flat = {}
    for k, v in config.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            flat.update(flatten_config(v, key))
        else:
            flat[key] = v
    return flat


@app.route("/api/test-line", methods=["POST"])
def api_test_line():
    """測試 LINE API 連線"""
    try:
        config = load_config()
        token = config.get("line", {}).get("channel_access_token", "")
        app.logger.info(f"Test LINE connection - token prefix: {token[:10] if token else 'EMPTY'}")
        success, message = line_api.test_connection()
        app.logger.info(f"LINE test result: success={success}, msg={message}")
        if success:
            return jsonify({"ok": True, "message": message})
        else:
            return jsonify({"ok": False, "error": message})
    except Exception as e:
        app.logger.exception("Test LINE connection crashed")
        return jsonify({"ok": False, "error": f"伺服器錯誤: {e}"}), 500


# ---------------------------------------------------------------------------
# Print API
# ---------------------------------------------------------------------------

@app.route("/api/print/printers")
def api_print_printers():
    """取得可用印表機清單"""
    try:
        printers = print_handler.get_cups_printers()
        cfg = print_handler.get_print_config()
        return jsonify({
            "printers": printers,
            "default": cfg.get("default_printer"),
            "enabled": cfg.get("enabled", True),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": f"伺服器錯誤: {e}"}), 500


@app.route("/api/print/test", methods=["POST"])
def api_print_test():
    """測試列印"""
    try:
        data = request.get_json(silent=True) or {}
        printer_hint = data.get("printer", "")
        success, result = print_handler.test_print(printer_hint if printer_hint else None)
        if success:
            return jsonify({"ok": True, "message": "測試列印已送出", "result": result})
        else:
            return jsonify({"ok": False, "error": result})
    except Exception as e:
        return jsonify({"ok": False, "error": f"伺服器錯誤: {e}"}), 500


@app.route("/api/print/config", methods=["GET"])
def api_print_config_get():
    """取得列印設定"""
    return jsonify(print_handler.get_print_config())


@app.route("/api/print/config", methods=["POST"])
def api_print_config_post():
    """更新列印設定"""
    data = request.get_json(silent=True) or {}
    config = load_config()
    print_cfg = config.get("print", {})
    print_cfg.update(data)
    config["print"] = print_cfg
    try:
        save_config(config)
        return jsonify({"ok": True, "message": "列印設定已更新", "config": print_handler.get_print_config()})
    except Exception as e:
        return jsonify({"ok": False, "error": f"伺服器錯誤: {e}"}), 500


# ---------------------------------------------------------------------------
# LINE Webhook
# ---------------------------------------------------------------------------

@app.route("/webhook", methods=["POST"])
@app.route("/line/webhook", methods=["POST"])
def webhook():
    """LINE Messaging API Webhook 端點"""
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)

    # 驗證簽章
    if not line_api.verify_webhook(signature, body):
        abort(403)

    try:
        events = json.loads(body).get("events", [])
    except json.JSONDecodeError:
        abort(400)

    for event in events:
        if event.get("type") != "message":
            continue

        src = event.get("source", {})
        user_id = src.get("userId", "")
        msg = event.get("message", {})
        msg_type = msg.get("type", "")
        msg_id = msg.get("id", "")
        msg_text = msg.get("text", "")

        # 取得用戶名稱
        profile = line_api.get_user_profile(user_id)
        user_name = profile.get("displayName", "") if profile else ""

        # 若 contact 不存在則新增
        existing = db.get_contact(user_id)
        if not existing and not profile:
            db.add_contact(user_id, user_name or "未知客戶", role="customer")
        elif not existing:
            db.add_contact(user_id, user_name, role="customer")

        # 文字訊息：既有邏輯（意圖分類、SLA 監控）+ 記錄最後文字供圖片/檔案列印判斷
        # 也處理列印會話中的份數輸入
        if msg_type == "text":
            _set_user_last_text(user_id, msg_text)

            # 檢查是否有進行中的列印會話，且輸入為數字
            session = _get_print_session(user_id)
            if session and msg_text.strip().isdigit():
                copies = int(msg_text.strip())
                if copies < 1:
                    line_api.send_message(user_id, "份數需大於 0，請重新輸入。")
                elif copies > 9:
                    line_api.send_message(user_id, "份數上限 9，請重新輸入。")
                else:
                    # 取出會話並執行列印
                    session = _pop_print_session(user_id)
                    if session:
                        _execute_print_job(user_id, session, copies)
                    else:
                        line_api.send_message(user_id, "列印會話已過期，請重新傳送圖片/檔案。")
                continue

            # 一般文字訊息處理
            intent = classify_intent(msg_text)
            initial_status = "pending" if intent == "inquiry" else "resolved"
            db.add_message(user_id, user_name, msg_text, status=initial_status)
            continue

        # 圖片/檔案訊息：檢查最後文字是否含「列印」關鍵字
        if msg_type in ("image", "file"):
            print_cfg = print_handler.get_print_config()
            if not print_cfg.get("enabled", True):
                continue
            if msg_type not in print_cfg.get("allowed_types", ["image", "file"]):
                continue

            # 檢查關鍵字：使用用戶最後一則文字訊息
            last_text = _get_user_last_text(user_id)
            if "列印" not in last_text:
                continue

            # 檢查檔案大小（file 類型有 size 欄位）
            max_size_mb = print_cfg.get("max_file_size_mb", 20)
            file_size = msg.get("size", 0)
            if file_size and file_size > max_size_mb * 1024 * 1024:
                line_api.send_message(user_id, f"檔案過大 ({file_size/1024/1024:.1f}MB)，限制 {max_size_mb}MB")
                continue

            # 檢查副檔名（file 類型有 fileName）
            file_name = msg.get("fileName", "")
            if file_name:
                ext = os.path.splitext(file_name)[1].lower()
                allowed_exts = print_cfg.get("allowed_extensions", [".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".txt", ".md", ".docx"])
                if ext not in allowed_exts:
                    line_api.send_message(user_id, f"不支援的檔案格式: {ext}")
                    continue

            # 檢查使用者權限
            if not print_handler.is_user_authorized(user_id):
                line_api.send_message(user_id, "您無列印權限，僅限管理員/操作人員使用。")
                continue

            # 建立列印會話，詢問份數
            _create_print_session(user_id, msg_id, msg_type, last_text)
            line_api.send_message(user_id, "📄 收到列印檔案，請輸入列印份數 (1-9)：")

    return "OK", 200


def _execute_print_job(user_id, session, copies):
    """在背景執行緒執行列印工作"""
    if _is_processed(session["message_id"]):
        line_api.send_message(user_id, "該檔案已處理過，跳過列印。")
        return

    def _print_worker(uid, mid, mtype, hint, copy_count):
        try:
            success, result = print_handler.process_print_request(
                user_id=uid,
                message_id=mid,
                message_type=mtype,
                printer_hint=hint,
                options={"copies": copy_count},
            )
            if success:
                reply = f"✅ 列印已送出 ({copy_count}份)\n印表機: {result['printer']}\n工作 ID: {result['job_id']}"
            else:
                reply = f"❌ 列印失敗: {result.get('error', '未知錯誤')}"
            line_api.send_message(uid, reply)
        except Exception as e:
            line_api.send_message(uid, f"❌ 列印處理錯誤: {e}")

    threading.Thread(target=_print_worker, args=(user_id, session["message_id"], session["message_type"], session["last_text"], copies), daemon=True).start()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    config = load_config()
    server_cfg = config.get("server", {})
    port = int(os.environ.get("PORT", server_cfg.get("port", 8080)))
    app.run(
        host=server_cfg.get("host", "0.0.0.0"),
        port=port,
        debug=os.environ.get("FLASK_DEBUG", "0") == "1",
    )
