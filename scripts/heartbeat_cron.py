#!/usr/bin/env python3
"""
獨立心跳監控腳本 - 供 crontab 定時呼叫
檢查 patrol 是否持續執行；若超過 max_stale_minutes 未執行，發送高優先級警報。

crontab 設定 (例如每 5 分鐘):
*/5 * * * * cd /home/mf-claw/line-monitor && venv/bin/python scripts/heartbeat_cron.py >> data/heartbeat.log 2>&1
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database as db
import heartbeat


if __name__ == '__main__':
    db.init_db()
    result = heartbeat.check_heartbeat()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if result['healthy']:
        print(f"[{now}] heartbeat OK (last: {result['last_beat_at']})")
    else:
        print(
            f"[{now}] heartBEAT STALE! "
            f"{result['stale_minutes']}min > {result['max_stale_minutes']}min "
            f"-> alerts sent to enabled channels"
        )
        for c, ok, m in result['alerts']:
            print(f"  alert[{c}]: {'OK' if ok else 'FAIL'} {m}")
        # 非零 exit code 以傳遞異常狀態
        sys.exit(1)