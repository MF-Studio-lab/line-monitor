"""
notify.py - 多通道通知引擎
支援 LINE(既有) / Discord(Webhook) / Telegram(HTTP Bot) / Email(SMTP)
供 escalated(嚴重延遲) 及 heartbeat 警報使用，確保管理員在不看 LINE 時仍能收到高優先級通知。
"""

import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests

import line_api
from config import load_config


def send_channel_message(channel, content, targets=None):
    """
    透過指定通道發送通知。
    channel: 'line' | 'discord' | 'telegram' | 'email'
    content: 訊息文字
    targets(可選): line=user_id list；email=信箱 list；telegram/discord 用設定。
    回傳 (success, message)
    """
    config = load_config()
    channels = config.get("notify_channels", {})
    cfg = channels.get(channel, {})

    if channel == "line":
        return _send_line(content, targets)
    if channel == "discord":
        return _send_discord(content, cfg)
    if channel == "telegram":
        return _send_telegram(content, cfg)
    if channel == "email":
        return _send_email(content, cfg, targets)
    return False, f"未知通道: {channel}"


def notify_all(content, targets=None, only_channels=None):
    """
    依設定，向所有已啟用的通道發送。
    only_channels: 限制只送指定通道 list（例如 ['discord','telegram','email']）。
    回傳 [(channel, success, message), ...]
    """
    config = load_config()
    channels = config.get("notify_channels", {})
    results = []

    for channel, cfg in channels.items():
        if only_channels and channel not in only_channels:
            continue
        if not cfg.get("enabled", False):
            continue
        if channel == "line":
            # LINE 走既有 handle (targets 為 user_id list 才送)
            if not targets:
                continue
            success, msg = _send_line(content, targets)
        else:
            success, msg = send_channel_message(channel, content, targets)
        results.append((channel, success, msg))

    return results


def _send_line(content, targets):
    if not targets:
        return False, "無 LINE 目標"
    ok = 0
    for uid in targets:
        success, _ = line_api.send_message(uid, content)
        if success:
            ok += 1
    return (ok > 0), f"LINE 已送 {ok}/{len(targets)}"


def _send_discord(content, cfg):
    url = cfg.get("webhook_url", "")
    if not url:
        return False, "Discord webhook_url 未設定"
    try:
        resp = requests.post(url, json={"content": content}, timeout=30)
        return resp.status_code in (200, 204), f"Discord {resp.status_code}"
    except requests.RequestException as e:
        return False, f"Discord: {e}"


def _send_telegram(content, cfg):
    token = cfg.get("bot_token", "")
    chat_id = cfg.get("chat_id", "")
    if not token or not chat_id:
        return False, "Telegram bot_token/chat_id 未設定"
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(
            url, json={"chat_id": chat_id, "text": content}, timeout=30
        )
        return resp.ok, f"Telegram {resp.status_code}"
    except requests.RequestException as e:
        return False, f"Telegram: {e}"


def _send_email(content, cfg, targets=None):
    host = cfg.get("smtp_host", "")
    port = int(cfg.get("smtp_port", 465))
    user = cfg.get("smtp_user", "")
    password = cfg.get("smtp_password", "")
    from_email = cfg.get("from_email", user)
    use_tls = cfg.get("use_tls", True)

    to_emails = targets or cfg.get("to_emails", [])
    if not host or not user or not password or not from_email:
        return False, "Email SMTP 設定不完整"
    if not to_emails:
        return False, "Email 收件人未設定"

    msg = MIMEMultipart()
    msg["From"] = from_email
    msg["To"] = ", ".join(to_emails)
    msg["Subject"] = "[LINE監控] 高優先級警報"
    msg.attach(MIMEText(content, "plain", "utf-8"))

    try:
        if use_tls:
            server = smtplib.SMTP_SSL(host, port, timeout=30, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(host, port, timeout=30)
            server.ehlo()
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
        server.login(user, password)
        server.sendmail(from_email, to_emails, msg.as_string())
        server.quit()
        return True, f"Email 已送 {len(to_emails)}"
    except Exception as e:
        return False, f"Email: {e}"


def test_channel(channel):
    """
    測試某通道連線，回傳 (success, message)
    """
    config = load_config()
    channels = config.get("notify_channels", {})
    cfg = channels.get(channel, {})

    if channel == "line":
        return line_api.test_connection()
    if channel == "discord":
        return _send_discord("[測試] LINE 監控通知通道測試", cfg)
    if channel == "telegram":
        return _send_telegram("[測試] LINE 監控通知通道測試", cfg)
    if channel == "email":
        return _send_email("[測試] LINE 監控通知通道測試", cfg)
    return False, f"未知通道: {channel}"