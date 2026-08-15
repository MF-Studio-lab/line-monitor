"""
app.py - Flask 主程式
LINE 客戶服務監控系統 Web UI
Port: 8080
"""

import json
import os
from datetime import datetime

from flask import Flask, request, jsonify, render_template, abort

import database as db
import line_api
import ai_service
import patrol
from config import load_config, save_config, validate_config

app = Flask(__name__)

# 啟動時初始化 DB
db.init_db()


# ---------------------------------------------------------------------------
# Web UI Routes
# ---------------------------------------------------------------------------

@app.route("/")
def dashboard():
    """儀表板頁面"""
    stats = db.get_stats()
    pending = db.get_pending_messages()
    config = load_config()
    return render_template(
        "dashboard.html",
        stats=stats,
        pending=pending,
        config=config,
        active_page="dashboard",
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

    messages = db.get_messages(
        status=status_filter or None,
        date_from=date_from or None,
        date_to=date_to or None,
        search=search or None,
        limit=500,
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
        return jsonify({"error": "訊息不存在"}), 404

    text = data.get("text") or msg.get("ai_draft", "")
    if not text:
        return jsonify({"error": "沒有可發送的內容"}), 400

    success, resp = line_api.send_message(msg["user_id"], text)
    if success:
        db.resolve_message(msg_id, reply_by="admin")
        return jsonify({"success": True, "response": resp})
    else:
        db.update_message(msg_id, ai_draft=text)
        return jsonify({"success": False, "error": resp}), 500


@app.route("/api/messages/<int:msg_id>/resolve", methods=["POST"])
def api_resolve_message(msg_id):
    """標記訊息為已處理"""
    data = request.get_json(silent=True) or {}
    reply_by = data.get("reply_by", "admin")
    msg = db.get_message(msg_id)
    if not msg:
        return jsonify({"error": "訊息不存在"}), 404
    db.resolve_message(msg_id, reply_by=reply_by)
    return jsonify({"success": True})


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


@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    """取得設定"""
    return jsonify(load_config())


@app.route("/api/settings", methods=["POST"])
def api_post_settings():
    """更新設定"""
    data = request.get_json(silent=True) or {}
    config = load_config()
    # 深度合併
    for section, values in data.items():
        if section in config and isinstance(config[section], dict):
            config[section].update(values)
        else:
            config[section] = values
    save_config(config)
    return jsonify({"success": True, "config": config})


@app.route("/api/test-line", methods=["POST"])
def api_test_line():
    """測試 LINE API 連線"""
    success, message = line_api.test_connection()
    return jsonify({"success": success, "message": message})


# ---------------------------------------------------------------------------
# LINE Webhook
# ---------------------------------------------------------------------------

@app.route("/webhook", methods=["POST"])
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
        msg_text = msg.get("text", "")

        if msg_type != "text":
            continue

        # 取得用戶名稱
        profile = line_api.get_user_profile(user_id)
        user_name = profile.get("displayName", "") if profile else ""

        # 存入 DB
        db.add_message(user_id, user_name, msg_text)

        # 若 contact 不存在則新增
        existing = db.get_contact(user_id)
        if not existing and not profile:
            db.add_contact(user_id, user_name or "未知客戶", role="customer")
        elif not existing:
            db.add_contact(user_id, user_name, role="customer")

    return "OK", 200


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
