"""
Local SQLite storage for attempt history / progress tracking.
File lives at ielts-platform/data/progress.db (created on first run).
"""
import sqlite3
import os
import json
import time

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "progress.db")


def _backfill_manually_scored(conn):
    """
    One-time backfill, run only immediately after the manually_scored
    column is first added to a pre-existing database. Naively defaulting
    every legacy row to 0 (not manually scored) is wrong for rows that
    WERE hand-tallied before this feature existed: the tell is in
    detail_json, which is a snapshot taken at marking time, not now.

    If every question in a row's detail_json has is_correct=null, the
    answer key was entirely blank at THE TIME IT WAS SCORED -- that's
    exactly the shape mark_section() produces for a fully-blank key,
    which always yields a null correct_count. So if such a row still has
    a non-null correct_count, the only way that could have happened is
    someone entering it by hand afterward (the pre-this-feature version
    of "Enter score" just wrote correct_count/band directly). This is
    more reliable than checking the CURRENT answers.json, since that may
    have since been partially or fully filled in -- detail_json fixes
    the picture to how things stood when the score was actually set.
    """
    rows = conn.execute(
        "SELECT id, detail_json FROM attempts "
        "WHERE correct_count IS NOT NULL AND detail_json IS NOT NULL "
        "AND section IN ('reading', 'listening')"
    ).fetchall()
    backfilled = []
    for attempt_id, detail_json in rows:
        try:
            results = json.loads(detail_json)
        except (ValueError, TypeError):
            continue
        if results and all(r.get("is_correct") is None for r in results.values()):
            backfilled.append(attempt_id)
    if backfilled:
        conn.executemany(
            "UPDATE attempts SET manually_scored=1 WHERE id=?",
            [(i,) for i in backfilled],
        )
        conn.commit()
        print(f"[storage] Backfilled manually_scored=1 for {len(backfilled)} pre-existing "
              f"attempt(s) that were hand-tallied before this tracking existed: {backfilled}")


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
            auto_submitted INTEGER DEFAULT 0,
            manually_scored INTEGER DEFAULT 0  -- 1 = score was hand-tallied against the book,
                                                -- not derived from answers.json -- see
                                                -- update_manual_score(); "Re-check against
                                                -- current answer key" must never touch these,
                                                -- since re-deriving from a still-blank/partial
                                                -- JSON key would silently overwrite a real
                                                -- manual count with nothing.
        )
    """)
    # Safe migration for databases created before this column existed --
    # SQLite has no "ADD COLUMN IF NOT EXISTS", so just ignore the error
    # if it's already there. When the column genuinely didn't exist yet
    # (this is the first run after upgrading), immediately backfill it
    # for pre-existing rows rather than leaving every legacy row at the
    # default 0 -- see _backfill_manually_scored for why that default is
    # wrong for some of them.
    try:
        conn.execute("ALTER TABLE attempts ADD COLUMN manually_scored INTEGER DEFAULT 0")
        conn.commit()
        _backfill_manually_scored(conn)
    except sqlite3.OperationalError:
        pass
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


def get_attempt(attempt_id):
    conn = _connect()
    cur = conn.execute("SELECT * FROM attempts WHERE id=?", (attempt_id,))
    row = cur.fetchone()
    if row is None:
        conn.close()
        return None
    cols = [d[0] for d in cur.description]
    result = dict(zip(cols, row))
    conn.close()
    return result


def update_full_score(attempt_id, correct_count, total, band_estimate, detail):
    """
    Re-marks an already-submitted attempt against the CURRENT answer key --
    for when a mistake in the answer key gets fixed after the fact, and a
    past attempt's stored score/detail should be recalculated to match,
    rather than staying frozen against the old (wrong) key forever.
    Like update_manual_score, deliberately leaves started_at/submitted_at/
    time_taken_seconds untouched. Always clears manually_scored, since this
    represents a real per-question re-mark, not a hand-tally -- though
    callers should check is_manually_scored() BEFORE calling this at all;
    see the guard in app.py's /remark endpoint.
    """
    conn = _connect()
    row = conn.execute("SELECT id FROM attempts WHERE id=?", (attempt_id,)).fetchone()
    if row is None:
        conn.close()
        raise ValueError(f"No attempt with id {attempt_id}")
    conn.execute(
        "UPDATE attempts SET correct_count=?, total=?, band_estimate=?, detail_json=?, manually_scored=0 WHERE id=?",
        (correct_count, total, band_estimate, json.dumps(detail), attempt_id),
    )
    conn.commit()
    conn.close()


def update_manual_score(attempt_id, correct_count, band_estimate):
    """
    Fills in (or corrects) correct_count/band_estimate for an attempt that
    was recorded as unmarked (e.g. the answer key wasn't available yet at
    the time), or that the person is re-tallying by hand against the
    answer-key page. Deliberately does NOT touch started_at/submitted_at/
    time_taken_seconds -- those describe when the test was actually taken,
    which shouldn't change just because the score was entered later.

    Marks the attempt manually_scored=1: since this count didn't come from
    per-question data, "Re-check against current answer key" must never
    be allowed to overwrite it -- re-deriving from a still-blank or
    partially-blank JSON key could silently wipe out a real hand-tallied
    score. See the guard in app.py's /remark endpoint.
    """
    conn = _connect()
    row = conn.execute("SELECT id FROM attempts WHERE id=?", (attempt_id,)).fetchone()
    if row is None:
        conn.close()
        raise ValueError(f"No attempt with id {attempt_id}")
    conn.execute(
        "UPDATE attempts SET correct_count=?, band_estimate=?, manually_scored=1 WHERE id=?",
        (correct_count, band_estimate, attempt_id),
    )
    conn.commit()
    conn.close()


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
