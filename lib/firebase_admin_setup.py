"""
Shared Firebase Admin SDK setup -- a single initialized app used both for
verifying ID tokens (see lib/auth.py) and for reading/writing Firestore
(users + attempts), so users and progress no longer live in a local
SQLite file that wouldn't survive a redeploy on stateless hosting.

Credentials, in order of preference:
  1. FIREBASE_SERVICE_ACCOUNT_JSON env var pointing at a downloaded
     service account key -- typical for local development.
  2. ./serviceAccountKey.json in the repo root, if present (same key,
     just the default filename -- see SETUP.md).
  3. Application Default Credentials -- used automatically when none of
     the above is set. This is what makes production deployment on
     Google Cloud (Cloud Run, App Engine, Compute Engine, ...) need zero
     secret files: the platform's attached service account identity is
     used directly, as long as it has the "Cloud Datastore User" /
     "Firebase Admin" role on the same GCP project as your Firebase app.
"""
import os
import firebase_admin
from firebase_admin import credentials, auth as firebase_auth, firestore

_app = None


def _ensure_initialized():
    global _app
    if _app is not None:
        return _app

    cred_path = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
    if not cred_path and os.path.isfile("serviceAccountKey.json"):
        cred_path = "serviceAccountKey.json"

    try:
        if cred_path:
            _app = firebase_admin.initialize_app(credentials.Certificate(cred_path))
        else:
            _app = firebase_admin.initialize_app()
    except Exception as e:
        raise RuntimeError(
            "Could not initialize Firebase Admin. For local development, "
            "download a service account key from Firebase Console > "
            "Project settings > Service accounts, save it as "
            "serviceAccountKey.json in the repo root (or point "
            "FIREBASE_SERVICE_ACCOUNT_JSON at wherever you saved it). "
            "See SETUP.md."
        ) from e
    return _app


def verify_id_token(id_token):
    """Returns the decoded token dict (uid, email, email_verified,
    firebase.sign_in_provider, ...) or raises on an invalid/expired token."""
    _ensure_initialized()
    return firebase_auth.verify_id_token(id_token)


def db():
    """Shared Firestore client -- same project as Authentication."""
    _ensure_initialized()
    return firestore.client()