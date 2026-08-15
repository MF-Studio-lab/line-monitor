"""
line_api.py - LINE Messaging API 封裝
提供 push message、reply message、取得用戶資料、webhook 簽章驗證
"""

import hashlib
import hmac
import base64
import requests
from config import load_config

LINE_API_BASE = "https://api.line.me/v2"


def _get_headers():
    """取得 LINE API 請求標頭"""
    config = load_config()
    token = config.get("line", {}).get("channel_access_token", "")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def send_message(user_id, text):
    """
    Push message 到指定用戶
    回傳 (success: bool, response: dict)
    """
    headers = _get_headers()
    payload = {
        "to": user_id,
        "messages": [
            {"type": "text", "text": text},
        ],
    }
    resp = requests.post(
        f"{LINE_API_BASE}/bot/message/push",
        headers=headers,
        json=payload,
        timeout=30,
    )
    success = resp.status_code == 200
    try:
        body = resp.json()
    except ValueError:
        body = {"text": resp.text}
    return success, body


def reply_message(reply_token, text):
    """
    使用 reply token 回覆訊息
    回傳 (success: bool, response: dict)
    """
    headers = _get_headers()
    payload = {
        "replyToken": reply_token,
        "messages": [
            {"type": "text", "text": text},
        ],
    }
    resp = requests.post(
        f"{LINE_API_BASE}/bot/message/reply",
        headers=headers,
        json=payload,
        timeout=30,
    )
    success = resp.status_code == 200
    try:
        body = resp.json()
    except ValueError:
        body = {"text": resp.text}
    return success, body


def get_user_profile(user_id):
    """
    取得用戶資料（顯示名稱）
    回傳 dict: {display_name, user_id, picture_url, status_message} 或 None
    """
    headers = _get_headers()
    resp = requests.get(
        f"{LINE_API_BASE}/bot/profile/{user_id}",
        headers=headers,
        timeout=30,
    )
    if resp.status_code == 200:
        return resp.json()
    return None


def verify_webhook(signature, body):
    """
    驗證 LINE webhook 簽章
    signature: X-Line-Signature 標頭值
    body: request body 原始字串 (bytes 或 str)
    回傳 bool
    """
    config = load_config()
    channel_secret = config.get("line", {}).get("channel_secret", "")
    if not channel_secret:
        return False

    if isinstance(body, str):
        body = body.encode("utf-8")

    computed = hmac.new(
        channel_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()

    try:
        sig = base64.b64decode(signature)
    except (ValueError, TypeError):
        return False

    return hmac.compare_digest(computed, sig)


def test_connection():
    """
    測試 LINE API 連線是否正常
    回傳 (success: bool, message: str)
    """
    config = load_config()
    token = config.get("line", {}).get("channel_access_token", "")
    if not token:
        return False, "channel_access_token 未設定"

    headers = {
        "Authorization": f"Bearer {token}",
    }
    resp = requests.get(
        f"{LINE_API_BASE}/bot/info",
        headers=headers,
        timeout=30,
    )
    if resp.status_code == 200:
        info = resp.json()
        return True, f"連線正常 — Bot: {info.get('displayName', 'N/A')}"
    else:
        try:
            err = resp.json()
        except ValueError:
            err = {"message": resp.text}
        return False, f"連線失敗 ({resp.status_code}): {err}"
