"""
Account profile storage -- Firestore, keyed directly by Firebase UID.

Firebase Authentication remains the source of truth for credentials and
verification. Firestore stores the small product profile used by IELTSBand:
name, email, study target, test type, and optional exam date.
"""
import time
from functools import wraps
from flask import session, redirect, url_for, request, jsonify

from lib.firebase_admin_setup import db

USERS_COLLECTION = "users"


def _clean_profile(data):
    data = data or {}
    return {
        "target_band": data.get("target_band") or "",
        "test_type": data.get("test_type") or "",
        "exam_date": data.get("exam_date") or "",
    }


def get_or_create_user(firebase_uid, email, name):
    """
    Looks up the profile doc for this Firebase UID, creating one on first
    sign-in. Name/email are kept in sync with Firebase on every login.
    Existing study preferences are preserved.
    """
    name = (name or (email.split("@")[0] if email else "") or "Student").strip()
    email = (email or "").strip().lower()
    doc_ref = db().collection(USERS_COLLECTION).document(firebase_uid)
    snap = doc_ref.get()

    if snap.exists:
        doc_ref.update({"name": name, "email": email})
        data = snap.to_dict() or {}
        return {
            "id": firebase_uid,
            "name": name,
            "email": email,
            **_clean_profile(data),
        }

    doc_ref.set({
        "name": name,
        "email": email,
        "created_at": time.time(),
        "target_band": "",
        "test_type": "",
        "exam_date": "",
    })
    return {
        "id": firebase_uid,
        "name": name,
        "email": email,
        "target_band": "",
        "test_type": "",
        "exam_date": "",
    }


def get_user(user_id):
    snap = db().collection(USERS_COLLECTION).document(user_id).get()
    if not snap.exists:
        return None

    data = snap.to_dict() or {}
    return {
        "id": user_id,
        "name": data.get("name"),
        "email": data.get("email"),
        **_clean_profile(data),
    }


def update_profile(user_id, name, target_band="", test_type="", exam_date=""):
    name = (name or "").strip()
    target_band = (target_band or "").strip()
    test_type = (test_type or "").strip()
    exam_date = (exam_date or "").strip()

    if not name:
        raise ValueError("Name is required.")

    allowed_bands = {"", "6.0", "6.5", "7.0", "7.5", "8.0", "8.5", "9.0"}
    if target_band not in allowed_bands:
        raise ValueError("Invalid target band.")

    if test_type not in {"", "Academic", "General Training"}:
        raise ValueError("Invalid test type.")

    if len(exam_date) > 10:
        raise ValueError("Invalid exam date.")

    doc_ref = db().collection(USERS_COLLECTION).document(user_id)
    snap = doc_ref.get()
    if not snap.exists:
        raise ValueError("User profile not found.")

    doc_ref.update({
        "name": name,
        "target_band": target_band,
        "test_type": test_type,
        "exam_date": exam_date,
    })

    return get_user(user_id)


def current_user():
    user_id = session.get("user_id")
    if user_id is None:
        return None
    return get_user(user_id)


def login_required(view):
    """
    For page routes: redirects anonymous visitors to /login (keeping the
    page they wanted via ?next=). For /api/* routes: returns 401 JSON.
    """
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("user_id") is None:
            if request.path.startswith("/api/"):
                return jsonify({"error": "login required"}), 401
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped
