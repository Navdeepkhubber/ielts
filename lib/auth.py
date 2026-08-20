"""
Account profile storage -- Firestore, keyed directly by Firebase UID.

Firebase Authentication remains the source of truth for production
credentials and verification. Local development bypasses Firebase only for
localhost/127.0.0.1 (or when LOCAL_DEV=1 is explicitly set), so normal
production hosts can never enter local-auth mode merely because Flask debug
mode is enabled.
"""
import os
import time
from functools import wraps
from flask import session, redirect, url_for, request, jsonify

from lib.firebase_admin_setup import db

USERS_COLLECTION = "users"
LOCAL_DEV_USER_ID = "local-dev"


def _is_localhost_request():
    """Return True only for loopback/local development hosts."""
    host = (request.host.split(":", 1)[0] if request else "").strip().lower()
    return host in {"localhost", "127.0.0.1", "::1"}


def _local_dev_enabled():
    """Enable local auth on localhost, or explicitly via LOCAL_DEV=1."""
    explicit = os.environ.get("LOCAL_DEV", "")
    return _is_localhost_request() or explicit.strip().lower() in {"1", "true", "yes", "on"}


def _local_user():
    return {
        "id": LOCAL_DEV_USER_ID,
        "name": os.environ.get("LOCAL_DEV_NAME", "Local Developer"),
        "email": os.environ.get("LOCAL_DEV_EMAIL", "local@ieltsband.com").strip().lower(),
        "admin": True,
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
    """Create/sync the application profile for a verified Firebase user."""
    name = (name or (email.split("@")[0] if email else "") or "Student").strip()
    email = (email or "").strip().lower()
    doc_ref = db().collection(USERS_COLLECTION).document(firebase_uid)
    snap = doc_ref.get()

    if snap.exists:
        data = snap.to_dict() or {}
        doc_ref.update({"name": name, "email": email})
        return {
            "id": firebase_uid,
            "name": name,
            "email": email,
            "admin": bool(data.get("admin", False)),
            **_clean_profile(data),
        }

    doc_ref.set({
        "name": name,
        "email": email,
        "admin": False,
        "created_at": time.time(),
        "target_band": "",
        "test_type": "",
        "exam_date": "",
    })
    return {
        "id": firebase_uid,
        "name": name,
        "email": email,
        "admin": False,
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
        "admin": bool(data.get("admin", False)),
        **_clean_profile(data),
    }


def update_profile(user_id, name, target_band="", test_type="", exam_date=""):
    name = (name or "").strip()
    target_band = (target_band or "").strip()
    test_type = (test_type or "").strip()
    exam_date = (exam_date or "").strip()

    if not name:
        raise ValueError("Name is required.")
    if target_band not in {"", "6.0", "6.5", "7.0", "7.5", "8.0", "8.5", "9.0"}:
        raise ValueError("Invalid target band.")
    if test_type not in {"", "Academic", "General Training"}:
        raise ValueError("Invalid test type.")
    if len(exam_date) > 10:
        raise ValueError("Invalid exam date.")

    if _local_dev_enabled() and user_id == LOCAL_DEV_USER_ID:
        user = _local_user()
        user.update({"name": name, "target_band": target_band, "test_type": test_type, "exam_date": exam_date})
        return user

    doc_ref = db().collection(USERS_COLLECTION).document(user_id)
    snap = doc_ref.get()
    if not snap.exists:
        raise ValueError("User profile not found.")
    doc_ref.update({"name": name, "target_band": target_band, "test_type": test_type, "exam_date": exam_date})
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
    """Require a real session unless this request is local development."""
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


def admin_required(view):
    """Require an admin profile in production; localhost is always allowed."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if _local_dev_enabled():
            session.setdefault("user_id", LOCAL_DEV_USER_ID)
            return view(*args, **kwargs)

        user = current_user()
        if not user or not user.get("admin", False):
            if request.path.startswith("/api/"):
                return jsonify({"error": "admin access required"}), 403
            abort = __import__("flask").abort
            abort(403)
        return view(*args, **kwargs)
    return wrapped
