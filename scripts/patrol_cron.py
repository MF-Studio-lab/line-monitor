#!/usr/bin/env python3
"""
獨立巡檢腳本 - 供 crontab 定時呼叫
每 15 分鐘執行一次，檢查超時未回覆訊息

crontab 設定:
*/15 * * * * cd /home/mf-claw/line-monitor && venv/bin/python scripts/patrol_cron.py >> data/patrol.log 2>&1
"""

import sys
import os

# 加入專案根目錄到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from patrol import patrol

if __name__ == '__main__':
    print(f"[{__import__('datetime').datetime.now()}] 開始巡檢...")
    results = patrol()
    print(f"  待檢查: {results['checked']}")
    print(f"  觸發提醒: {results['reminded']}")
    print(f"  升級通知: {results['escalated']}")
    print(f"  發送通知: {results['sent']}")
    print(f"[{__import__('datetime').datetime.now()}] 巡檢完成")
