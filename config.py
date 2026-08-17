"""
config.py - 設定管理模組
使用 JSON 檔存取設定（LINE token、通知時間、AI 模型等）
"""

import json
import os
from pathlib import Path

# 專案根目錄
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CONFIG_FILE = DATA_DIR / "config.json"

# 預設設定
DEFAULT_CONFIG = {
    "line": {
        "channel_access_token": "",
        "channel_secret": "",
        "webhook_url": "",
    },
    "notification": {
        "first_reminder_hours": 1,
        "second_reminder_hours": 3,
        "escalation_hours": 6,
        "patrol_interval_minutes": 15,
        "suppression_enabled": True,
    },
    "ai": {
        "model": "default",
        "auto_send": False,
        "company_info": "GREEN INDUSTRY CO., LTD. 專注於綠色產業解決方案，提供高品質的環保產品與專業諮詢服務。",
    },
    "rag": {
        "enabled": False,
        "kb_path": "",
        "top_k": 3,
    },
    "notify_channels": {
        "line": {"enabled": True},
        "discord": {
            "enabled": False,
            "webhook_url": "",
        },
        "telegram": {
            "enabled": False,
            "bot_token": "",
            "chat_id": "",
        },
        "email": {
            "enabled": False,
            "smtp_host": "",
            "smtp_port": 465,
            "smtp_user": "",
            "smtp_password": "",
            "use_tls": True,
            "from_email": "",
            "to_emails": [],
        },
    },
    "heartbeat": {
        "enabled": True,
        "max_stale_minutes": 60,
    },
    "company": {
        "name": "GREEN INDUSTRY CO., LTD.",
        "display_name": "綠色產業股份有限公司",
    },
    "server": {
        "port": 8080,
        "host": "0.0.0.0",
    },
}

# 確保 data 目錄存在
DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_config():
    """載入設定，若不存在則使用預設值並建立檔案"""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            # 合併預設值與儲存的值（深度合併）
            return _deep_merge(DEFAULT_CONFIG, saved)
        except (json.JSONDecodeError, IOError):
            pass
    # 建立預設設定檔
    save_config(DEFAULT_CONFIG)
    return DEFAULT_CONFIG


def save_config(config):
    """儲存設定到 JSON 檔"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def _deep_merge(base, override):
    """深度合併兩個字典"""
    result = {}
    for key in base:
        if key in override:
            if isinstance(base[key], dict) and isinstance(override[key], dict):
                result[key] = _deep_merge(base[key], override[key])
            else:
                result[key] = override[key]
        else:
            result[key] = base[key]
    # 加入 override 中多出的 key
    for key in override:
        if key not in result:
            result[key] = override[key]
    return result


def validate_config(config):
    """驗證設定是否完整，回傳 (is_valid, missing_fields)"""
    missing = []
    line = config.get("line", {})
    if not line.get("channel_access_token"):
        missing.append("line.channel_access_token")
    if not line.get("channel_secret"):
        missing.append("line.channel_secret")
    return (len(missing) == 0, missing)
