import os

# Must happen before `import app` anywhere -- app.py now refuses to start
# in production mode without FLASK_SECRET_KEY, and CI runs pytest as a
# plain script, not under `python3 app.py`, so nothing else sets these.
os.environ.setdefault("FLASK_SECRET_KEY", "ci-test-secret-not-for-production")
os.environ.setdefault("FLASK_DEBUG", "1")

import pytest

from app_tests.fake_firestore import FakeFirestoreClient


@pytest.fixture
def fake_db(monkeypatch):
    """Swaps every module's Firestore client for a fresh in-memory fake,
    so tests never need real Firebase credentials."""
    client = FakeFirestoreClient()
    import lib.firebase_admin_setup as fas
    import lib.auth as auth_mod
    import lib.storage as storage_mod

    monkeypatch.setattr(fas, "db", lambda: client)
    monkeypatch.setattr(auth_mod, "db", lambda: client)
    monkeypatch.setattr(storage_mod, "db", lambda: client)
    return client


@pytest.fixture
def verified_token(monkeypatch):
    """Makes the next call to POST /auth/session look like a verified
    email/password sign-in for uid 'test-uid'. Tests that need a
    different scenario (unverified, Google, a different uid) monkeypatch
    verify_id_token again themselves -- see test_smoke.py for examples."""
    import lib.firebase_admin_setup as fas
    import app as flaskapp

    def fake_verify(id_token):
        return {
            "uid": "test-uid",
            "email": "test@example.com",
            "email_verified": True,
            "name": "Test User",
            "firebase": {"sign_in_provider": "password"},
        }

    monkeypatch.setattr(fas, "verify_id_token", fake_verify)
    monkeypatch.setattr(flaskapp.firebase_admin_setup, "verify_id_token", fake_verify)
    return fake_verify


@pytest.fixture
def client(fake_db):
    import app as flaskapp
    flaskapp.app.config.update(TESTING=True)
    return flaskapp.app.test_client()