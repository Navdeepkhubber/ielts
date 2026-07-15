"""
Local SQLite storage for attempt history / progress tracking.
File lives at ielts-platform/data/progress.db (created on first run).
"""
import sqlite3
import os
import json
import time

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "progress.db")


def _connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_id TEXT NOT NULL,
            section TEXT NOT NULL,           -- reading | listening | writing
            started_at REAL NOT NULL,
            submitted_at REAL,
            time_allowed_seconds INTEGER,
            time_taken_seconds INTEGER,
            correct_count INTEGER,
            total INTEGER,
            band_estimate REAL,
            detail_json TEXT,                -- per-question breakdown or writing feedback
            auto_submitted INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    return conn


def start_attempt(test_id, section, time_allowed_seconds):
    conn = _connect()
    cur = conn.execute(
        "INSERT INTO attempts (test_id, section, started_at, time_allowed_seconds) VALUES (?, ?, ?, ?)",
        (test_id, section, time.time(), time_allowed_seconds),
    )
    conn.commit()
    attempt_id = cur.lastrowid
    conn.close()
    return attempt_id


def submit_attempt(attempt_id, correct_count=None, total=None, band_estimate=None,
                    detail=None, auto_submitted=False):
    conn = _connect()
    row = conn.execute("SELECT started_at, time_allowed_seconds FROM attempts WHERE id=?",
                        (attempt_id,)).fetchone()
    if row is None:
        conn.close()
        raise ValueError(f"No attempt with id {attempt_id}")
    started_at, allowed = row
    now = time.time()
    time_taken = int(now - started_at)
    conn.execute("""
        UPDATE attempts SET submitted_at=?, time_taken_seconds=?,
            correct_count=?, total=?, band_estimate=?, detail_json=?, auto_submitted=?
        WHERE id=?
    """, (now, time_taken, correct_count, total, band_estimate,
          json.dumps(detail) if detail is not None else None,
          1 if auto_submitted else 0, attempt_id))
    conn.commit()
    conn.close()
    return time_taken


def history(test_id=None, section=None, limit=100):
    conn = _connect()
    query = "SELECT * FROM attempts WHERE submitted_at IS NOT NULL"
    params = []
    if test_id:
        query += " AND test_id=?"
        params.append(test_id)
    if section:
        query += " AND section=?"
        params.append(section)
    query += " ORDER BY submitted_at DESC LIMIT ?"
    params.append(limit)
    cols = [d[0] for d in conn.execute(query, params).description] if False else None
    cur = conn.execute(query, params)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    for r in rows:
        if r.get("detail_json"):
            r["detail"] = json.loads(r["detail_json"])
        del r["detail_json"]
    return rows
