"""
Account profile storage -- Firestore, keyed directly by Firebase UID.

Firebase Authentication remains the source of truth for production
credentials and verification. Local development deliberately bypasses
Firebase so the exam portal can be developed without a local Firebase
service-account setup.
"""
import os
import time
from functools import wraps
from flask import session, redirect, url_for, request, jsonify

from lib.firebase_admin_setup import db

USERS_COLLECTION = "users"
LOCAL_DEV_USER_ID = "local-dev"


def _local_dev_enabled():
    """Enable the local-only auth bypass used by the development server.

    Production sets PUBLIC_BASE_DOMAIN, so this cannot accidentally turn on
    there just because FLASK_DEBUG is enabled. Set LOCAL_DEV=0 explicitly if
    a local environment needs to exercise the real Firebase login flow.
    """
    explicit = os.environ.get("LOCAL_DEV")
    if explicit is not None:
        return explicit.strip().lower() in {"1", "true", "yes", "on"}
    return os.environ.get("PUBLIC_BASE_DOMAIN", "").strip() == "" and os.environ.get("FLASK_DEBUG", "1") == "1"


def _local_user():
    return {
        "id": LOCAL_DEV_USER_ID,
        "name": os.environ.get("LOCAL_DEV_NAME", "Local Developer"),
        "email": os.environ.get("LOCAL_DEV_EMAIL", "local@ieltsband.com").strip().lower(),
        "target_band": "",
        "test_type": "",
        "exam_date": "",
    }


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
    if _local_dev_enabled() and user_id == LOCAL_DEV_USER_ID:
        return _local_user()

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

    if _local_dev_enabled() and user_id == LOCAL_DEV_USER_ID:
        user = _local_user()
        user.update({
            "name": name,
            "target_band": target_band,
            "test_type": test_type,
            "exam_date": exam_date,
        })
        return user

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
    if _local_dev_enabled():
        session.setdefault("user_id", LOCAL_DEV_USER_ID)
        return _local_user()

    user_id = session.get("user_id")
    if user_id is None:
        return None
    return get_user(user_id)


def login_required(view):
    """
    For local development, automatically use a synthetic local user and do
    not require Firebase. Production retains the normal session/Firebase
    authentication requirement.
    """
    @wraps(view)
    def wrapped(*args, **kwargs):
        if _local_dev_enabled():
            session.setdefault("user_id", LOCAL_DEV_USER_ID)
            return view(*args, **kwargs)

        if session.get("user_id") is None:
            if request.path.startswith("/api/"):
                return jsonify({"error": "login required"}), 401
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped
