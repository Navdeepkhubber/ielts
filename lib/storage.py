"""
Attempt history / progress tracking -- now Firestore instead of a local
SQLite file. This is the change that actually makes the app safe to run
on stateless hosting: a local data/progress.db would get wiped on every
redeploy/restart on something like Cloud Run (each instance gets a fresh,
ephemeral disk), and wouldn't be shared across multiple instances anyway.
Firestore has neither problem, and it's the same Firebase project already
used for Authentication.

Attempt documents live in a flat "attempts" collection with a "user_id"
field (the Firebase UID) rather than a per-user subcollection, since the
existing query patterns (history filtered by test_id/section across a
user's whole history) map directly onto a flat collection + composite
index. See SETUP.md for the Firestore indexes this needs.
"""
import time

from lib.firebase_admin_setup import db

ATTEMPTS_COLLECTION = "attempts"


def start_attempt(test_id, section, time_allowed_seconds, user_id=None):
    doc_ref = db().collection(ATTEMPTS_COLLECTION).document()
    doc_ref.set({
        "user_id": user_id,
        "test_id": test_id,
        "section": section,
        "started_at": time.time(),
        "time_allowed_seconds": time_allowed_seconds,
        "submitted_at": None,
        "time_taken_seconds": None,
        "correct_count": None,
        "total": None,
        "band_estimate": None,
        "detail": None,
        "auto_submitted": False,
        "manually_scored": False,
    })
    return doc_ref.id


def submit_attempt(attempt_id, correct_count=None, total=None, band_estimate=None,
                    detail=None, auto_submitted=False):
    doc_ref = db().collection(ATTEMPTS_COLLECTION).document(attempt_id)
    snap = doc_ref.get()
    if not snap.exists:
        raise ValueError(f"No attempt with id {attempt_id}")
    started_at = snap.to_dict()["started_at"]
    now = time.time()
    time_taken = int(now - started_at)
    doc_ref.update({
        "submitted_at": now,
        "time_taken_seconds": time_taken,
        "correct_count": correct_count,
        "total": total,
        "band_estimate": band_estimate,
        "detail": detail,
        "auto_submitted": bool(auto_submitted),
    })
    return time_taken


def get_attempt(attempt_id):
    snap = db().collection(ATTEMPTS_COLLECTION).document(attempt_id).get()
    if not snap.exists:
        return None
    data = snap.to_dict()
    data["id"] = attempt_id
    return data


def update_full_score(attempt_id, correct_count, total, band_estimate, detail):
    """
    Re-marks an already-submitted attempt against the CURRENT answer key --
    for when a mistake in the answer key gets fixed after the fact.
    Deliberately leaves started_at/submitted_at/time_taken_seconds
    untouched. Always clears manually_scored, since this represents a
    real per-question re-mark, not a hand-tally -- callers should check
    manually_scored BEFORE calling this at all (see the guard in
    app.py's /remark endpoint).
    """
    doc_ref = db().collection(ATTEMPTS_COLLECTION).document(attempt_id)
    if not doc_ref.get().exists:
        raise ValueError(f"No attempt with id {attempt_id}")
    doc_ref.update({
        "correct_count": correct_count,
        "total": total,
        "band_estimate": band_estimate,
        "detail": detail,
        "manually_scored": False,
    })


def update_manual_score(attempt_id, correct_count, band_estimate):
    """
    Fills in (or corrects) correct_count/band_estimate for an attempt
    scored by hand against the book. Deliberately does NOT touch
    started_at/submitted_at/time_taken_seconds. Marks manually_scored=True
    so "re-check against current answer key" never overwrites it -- see
    the guard in app.py's /remark endpoint.
    """
    doc_ref = db().collection(ATTEMPTS_COLLECTION).document(attempt_id)
    if not doc_ref.get().exists:
        raise ValueError(f"No attempt with id {attempt_id}")
    doc_ref.update({
        "correct_count": correct_count,
        "band_estimate": band_estimate,
        "manually_scored": True,
    })


def history(test_id=None, section=None, user_id=None, limit=100):
    q = db().collection(ATTEMPTS_COLLECTION)
    if user_id is not None:
        q = q.where("user_id", "==", user_id)
    if test_id:
        q = q.where("test_id", "==", test_id)
    if section:
        q = q.where("section", "==", section)
    # submitted_at > 0 excludes in-progress (never-submitted) attempts,
    # same as the old "WHERE submitted_at IS NOT NULL".
    q = q.where("submitted_at", ">", 0).order_by(
        "submitted_at", direction="DESCENDING"
    ).limit(limit)

    results = []
    for snap in q.stream():
        data = snap.to_dict()
        data["id"] = snap.id
        results.append(data)
    return results