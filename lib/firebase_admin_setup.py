"""
Shared Firebase Admin SDK setup -- a single initialized app used both for
verifying ID tokens (see lib/auth.py) and for reading/writing Firestore
(users + attempts), so users and progress no longer live in a local
SQLite file that wouldn't survive a redeploy on stateless hosting.

Credentials, in order of preference:
  1. FIREBASE_SERVICE_ACCOUNT_JSON env var pointing at a downloaded
     service account key -- typical for local development, and REQUIRED
     on any host that isn't Google Cloud itself (Render, Railway,
     Fly.io, a plain VPS, ...).
  2. ./serviceAccountKey.json in the repo root, if present (same key,
     just the default filename -- see SETUP.md).
  3. Application Default Credentials -- ONLY attempted when the process
     is actually detected to be running on Google Cloud (Cloud Run, App
     Engine, Compute Engine, ...), via the platform's own environment
     variables. This is what makes deployment there need zero secret
     files. Anywhere else, a missing credential now fails immediately
     and clearly here -- rather than "succeeding" at initialize_app()
     and then failing later with a cryptic, hard-to-trace error the
     first time Auth/Firestore is actually used (this used to happen:
     firebase_admin.initialize_app() with no credentials never raises at
     that call site, since the App object is created lazily -- the
     failure only surfaced deep inside the SDK on first real use).
"""
import os
import firebase_admin
from firebase_admin import credentials, auth as firebase_auth, firestore

_app = None

# Env vars Google Cloud's own compute platforms set on themselves, used
# here purely to detect "am I actually running on Google Cloud" before
# trusting Application Default Credentials to resolve anything.
_GOOGLE_CLOUD_MARKERS = ("K_SERVICE", "GAE_APPLICATION", "GOOGLE_CLOUD_PROJECT")


def _ensure_initialized():
    global _app
    if _app is not None:
        return _app

    cred_path = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
    if not cred_path and os.path.isfile("serviceAccountKey.json"):
        cred_path = "serviceAccountKey.json"

    if cred_path:
        if not os.path.isfile(cred_path):
            raise RuntimeError(
                f"FIREBASE_SERVICE_ACCOUNT_JSON is set to '{cred_path}', but "
                f"no file exists there. On Render specifically: (1) confirm "
                f"you uploaded a Secret File named exactly "
                f"'serviceAccountKey.json' under Environment > Secret Files, "
                f"and (2) confirm this env var's value matches where Render "
                f"mounts it at runtime -- that's /etc/secrets/<filename>, so "
                f"it should be /etc/secrets/serviceAccountKey.json. See "
                f"SETUP.md."
            )
        try:
            _app = firebase_admin.initialize_app(credentials.Certificate(cred_path))
        except Exception as e:
            raise RuntimeError(
                f"Found '{cred_path}' but Firebase Admin couldn't use it as "
                f"a service account credential -- likely not the JSON "
                f"Firebase Console gave you (Project settings > Service "
                f"accounts > Generate new private key), or it's been "
                f"truncated/corrupted. See SETUP.md."
            ) from e
        return _app

    if any(os.environ.get(v) for v in _GOOGLE_CLOUD_MARKERS):
        # Actually on Google Cloud -- Application Default Credentials
        # resolve automatically via the platform's metadata server.
        _app = firebase_admin.initialize_app()
        return _app

    raise RuntimeError(
        "No Firebase credentials configured, and this doesn't look like "
        "it's running on Google Cloud (where credentials would resolve "
        "automatically) -- so there's nothing to fall back to. On Render "
        "(or Railway/Fly.io/a plain VPS): upload your downloaded service "
        "account key as a Secret File named 'serviceAccountKey.json' "
        "(Render: Environment > Secret Files), then set "
        "FIREBASE_SERVICE_ACCOUNT_JSON=/etc/secrets/serviceAccountKey.json "
        "as an environment variable. See SETUP.md."
    )


def verify_id_token(id_token):
    """Returns the decoded token dict (uid, email, email_verified,
    firebase.sign_in_provider, ...) or raises on an invalid/expired token."""
    _ensure_initialized()
    return firebase_auth.verify_id_token(id_token)


def db():
    """Shared Firestore client -- same project as Authentication."""
    _ensure_initialized()
    return firestore.client()