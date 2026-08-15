"""
database.py - SQLite 操作封裝
提供 messages, contacts, notification_log, settings tables 的 CRUD 方法
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "data" / "line_monitor.db"


def get_connection():
    """取得 SQLite 連線"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """初始化資料庫，建立所有 tables"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript("""
    CREATE TABLE IF NOT EXISTS messages (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         TEXT NOT NULL,
        user_name       TEXT,
        message_text    TEXT NOT NULL,
        message_time    TEXT NOT NULL,
        reply_time      TEXT,
        reply_by        TEXT,
        status          TEXT DEFAULT 'pending',
        reminded_1_time     TEXT,
        reminded_2_time     TEXT,
        escalated_time      TEXT,
        ai_draft        TEXT,
        batch_id        TEXT
    );

    CREATE TABLE IF NOT EXISTS contacts (
        user_id     TEXT PRIMARY KEY,
        name        TEXT,
        role        TEXT DEFAULT 'customer',
        added_time  TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS notification_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_id    TEXT,
        sent_time   TEXT NOT NULL,
        channel     TEXT NOT NULL,
        target_id   TEXT,
        content     TEXT,
        message_ids TEXT
    );

    CREATE TABLE IF NOT EXISTS settings (
        key     TEXT PRIMARY KEY,
        value   TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_messages_status ON messages(status);
    CREATE INDEX IF NOT EXISTS idx_messages_user_id ON messages(user_id);
    CREATE INDEX IF NOT EXISTS idx_messages_message_time ON messages(message_time);
    """)

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Messages CRUD
# ---------------------------------------------------------------------------

def add_message(user_id, user_name, message_text, message_time=None):
    """新增一筆訊息"""
    if message_time is None:
        message_time = datetime.now().isoformat()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO messages (user_id, user_name, message_text, message_time, status)
           VALUES (?, ?, ?, ?, 'pending')""",
        (user_id, user_name, message_text, message_time),
    )
    msg_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return msg_id


def get_message(msg_id):
    """取得單筆訊息"""
    conn = get_connection()
    row = conn.execute("SELECT * FROM messages WHERE id = ?", (msg_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_messages(status=None, date_from=None, date_to=None, search=None, limit=200):
    """查詢訊息清單（可依狀態、日期、關鍵字篩選）"""
    query = "SELECT * FROM messages WHERE 1=1"
    params = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if date_from:
        query += " AND date(message_time) >= date(?)"
        params.append(date_from)
    if date_to:
        query += " AND date(message_time) <= date(?)"
        params.append(date_to)
    if search:
        query += " AND (message_text LIKE ? OR user_name LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    query += " ORDER BY message_time DESC LIMIT ?"
    params.append(limit)
    conn = get_connection()
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_pending_messages():
    """取得所有未回覆（pending / reminded_1 / reminded_2 / escalated）的訊息"""
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM messages
           WHERE status IN ('pending', 'reminded_1', 'reminded_2', 'escalated')
           ORDER BY message_time ASC"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_message(msg_id, **fields):
    """更新訊息欄位"""
    if not fields:
        return
    conn = get_connection()
    set_clauses = []
    values = []
    for key, val in fields.items():
        set_clauses.append(f"{key} = ?")
        values.append(val)
    set_clauses.append("id = ?")
    values.append(msg_id)
    # 修正: 最後的 id 不在 SET 中
    set_str = ", ".join(f"{k} = ?" for k in fields.keys())
    values = list(fields.values()) + [msg_id]
    conn.execute(f"UPDATE messages SET {set_str} WHERE id = ?", values)
    conn.commit()
    conn.close()


def update_message_status(msg_id, status):
    """更新訊息狀態"""
    now = datetime.now().isoformat()
    extra = {}
    if status == "reminded_1":
        extra["reminded_1_time"] = now
    elif status == "reminded_2":
        extra["reminded_2_time"] = now
    elif status == "escalated":
        extra["escalated_time"] = now
    elif status == "resolved":
        extra["reply_time"] = now
    extra["status"] = status
    update_message(msg_id, **extra)


def resolve_message(msg_id, reply_by):
    """標記訊息為已處理"""
    update_message(msg_id, status="resolved", reply_time=datetime.now().isoformat(), reply_by=reply_by)


def get_stats():
    """取得儀表板統計資料"""
    conn = get_connection()
    today = datetime.now().strftime("%Y-%m-%d")

    pending_count = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE status IN ('pending','reminded_1','reminded_2')"
    ).fetchone()[0]
    resolved_count = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE status = 'resolved'"
    ).fetchone()[0]
    escalated_count = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE status = 'escalated'"
    ).fetchone()[0]
    today_total = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE date(message_time) = date(?)", (today,)
    ).fetchone()[0]
    today_resolved = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE status='resolved' AND date(reply_time) = date(?)", (today,)
    ).fetchone()[0]
    today_pending = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE status IN ('pending','reminded_1','reminded_2') AND date(message_time)=date(?)", (today,)
    ).fetchone()[0]

    # 7 天趨勢
    trend_rows = conn.execute(
        """SELECT date(message_time) as d, COUNT(*) as cnt
           FROM messages
           WHERE message_time >= date('now', '-7 days')
           GROUP BY date(message_time)
           ORDER BY d ASC"""
    ).fetchall()
    trend = [{"date": r["d"], "count": r["cnt"]} for r in trend_rows]

    conn.close()
    return {
        "pending": pending_count,
        "resolved": resolved_count,
        "escalated": escalated_count,
        "today_total": today_total,
        "today_resolved": today_resolved,
        "today_pending": today_pending,
        "trend": trend,
    }


def delete_message(msg_id):
    """刪除一筆訊息"""
    conn = get_connection()
    conn.execute("DELETE FROM messages WHERE id = ?", (msg_id,))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Contacts CRUD
# ---------------------------------------------------------------------------

def add_contact(user_id, name, role="customer"):
    """新增或更新聯絡人"""
    conn = get_connection()
    conn.execute(
        """INSERT INTO contacts (user_id, name, role, added_time)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET name=excluded.name, role=excluded.role""",
        (user_id, name, role, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_contacts(role=None):
    """取得聯絡人清單"""
    conn = get_connection()
    if role:
        rows = conn.execute("SELECT * FROM contacts WHERE role = ? ORDER BY added_time DESC", (role,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM contacts ORDER BY added_time DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_contact(user_id):
    """取得單一聯絡人"""
    conn = get_connection()
    row = conn.execute("SELECT * FROM contacts WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_contact(user_id):
    """刪除聯絡人"""
    conn = get_connection()
    conn.execute("DELETE FROM contacts WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def get_operators():
    """取得所有操作人員"""
    return get_contacts(role="operator")


def get_admins():
    """取得所有管理員"""
    return get_contacts(role="admin")


# ---------------------------------------------------------------------------
# Notification Log CRUD
# ---------------------------------------------------------------------------

def add_notification_log(batch_id, channel, target_id, content, message_ids):
    """新增通知紀錄"""
    conn = get_connection()
    conn.execute(
        """INSERT INTO notification_log (batch_id, sent_time, channel, target_id, content, message_ids)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            batch_id,
            datetime.now().isoformat(),
            channel,
            target_id,
            content,
            json.dumps(message_ids) if isinstance(message_ids, list) else message_ids,
        ),
    )
    conn.commit()
    conn.close()


def get_notification_logs(limit=50):
    """取得通知紀錄"""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM notification_log ORDER BY sent_time DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Settings (key-value store) CRUD
# ---------------------------------------------------------------------------

def get_setting(key, default=None):
    """取得單一設定值"""
    conn = get_connection()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    if row:
        try:
            return json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            return row["value"]
    return default


def set_setting(key, value):
    """設定單一設定值"""
    conn = get_connection()
    stored = json.dumps(value) if not isinstance(value, str) else value
    conn.execute(
        """INSERT INTO settings (key, value) VALUES (?, ?)
           ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
        (key, stored),
    )
    conn.commit()
    conn.close()


def get_all_settings():
    """取得所有動態設定"""
    conn = get_connection()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    result = {}
    for r in rows:
        try:
            result[r["key"]] = json.loads(r["value"])
        except (json.JSONDecodeError, TypeError):
            result[r["key"]] = r["value"]
    return result


def delete_setting(key):
    """刪除設定"""
    conn = get_connection()
    conn.execute("DELETE FROM settings WHERE key = ?", (key,))
    conn.commit()
    conn.close()
