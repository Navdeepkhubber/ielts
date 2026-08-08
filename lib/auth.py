"""
Account profile storage -- now Firestore, keyed directly by Firebase UID.

All real authentication (passwords, Google sign-in, email verification)
is handled by Firebase Auth -- see lib/firebase_admin_setup.py and
templates/login.html / signup.html. This module just keeps a small
profile doc (name/email/created_at) per account. Using the Firebase UID
itself as the document id (rather than a separate local integer id, as
an earlier SQLite-based version of this file did) means there's no
mapping to maintain -- session["user_id"] and Firestore's key are the
same string end to end.
"""
import time
from functools import wraps

from flask import session, redirect, url_for, request, jsonify

from lib.firebase_admin_setup import db

USERS_COLLECTION = "users"


def get_or_create_user(firebase_uid, email, name):
    """
    Looks up the profile doc for this Firebase UID, creating one on first
    sign-in. Keeps name/email in sync with Firebase on every login, since
    those can change there (e.g. a Google profile name update) and we'd
    rather not go stale.
    """
    name = (name or (email.split("@")[0] if email else "") or "Student").strip()
    email = (email or "").strip().lower()

    doc_ref = db().collection(USERS_COLLECTION).document(firebase_uid)
    snap = doc_ref.get()
    if snap.exists:
        doc_ref.update({"name": name, "email": email})
    else:
        doc_ref.set({"name": name, "email": email, "created_at": time.time()})
    return {"id": firebase_uid, "name": name, "email": email}


def get_user(user_id):
    snap = db().collection(USERS_COLLECTION).document(user_id).get()
    if not snap.exists:
        return None
    data = snap.to_dict()
    return {"id": user_id, "name": data.get("name"), "email": data.get("email")}


def current_user():
    user_id = session.get("user_id")
    if user_id is None:
        return None
    return get_user(user_id)


def login_required(view):
    """
    For page routes: redirects anonymous visitors to /login (keeping the
    page they wanted via ?next=). For /api/* routes: returns 401 JSON
    instead, since a redirect makes no sense for a fetch() call.
    """
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("user_id") is None:
            if request.path.startswith("/api/"):
                return jsonify({"error": "login required"}), 401
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped