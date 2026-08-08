"""
Tests for the app.<domain> subdomain routing in app.py.

Login/signup and the dashboard deliberately share ONE subdomain (not
separate auth./dashboard. ones) so the whole site needs only 2 custom
domains total (apex + this one) -- Render's free tier caps custom
domains at 2, and a third costs money for no functional benefit here.

Two things matter:
1. With PUBLIC_BASE_DOMAIN unset (the default, and always true for local
   dev and the rest of this test suite), none of this logic should ever
   fire -- see test_smoke.py, which already exercises /, /login,
   /signup, /app on the default host and passes unchanged.
2. With PUBLIC_BASE_DOMAIN set, apex->subdomain redirects and the
   subdomain root (serving the app shell directly when logged in, or
   redirecting to /login on the SAME host when logged out) all need to
   behave correctly.
"""
import importlib

import pytest


@pytest.fixture
def subdomain_client(monkeypatch, fake_db):
    """A test client for a *fresh* app module with PUBLIC_BASE_DOMAIN
    configured -- reloaded so the module-level PUBLIC_BASE_DOMAIN/
    SESSION_COOKIE_DOMAIN config actually picks up the env var."""
    monkeypatch.setenv("PUBLIC_BASE_DOMAIN", "ieltsband.com")
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-secret-not-for-production")
    monkeypatch.setenv("FLASK_DEBUG", "1")

    import app as flaskapp
    importlib.reload(flaskapp)
    monkeypatch.setattr(flaskapp.firebase_admin_setup, "db", lambda: fake_db)

    flaskapp.app.config.update(TESTING=True)
    client = flaskapp.app.test_client()
    yield client, flaskapp

    # Reload back to the unconfigured state so later tests (which import
    # `app` fresh via the `client` fixture) aren't affected by this
    # module-level mutation leaking across tests.
    monkeypatch.delenv("PUBLIC_BASE_DOMAIN", raising=False)
    importlib.reload(flaskapp)


def test_apex_login_redirects_to_app_subdomain(subdomain_client):
    client, _ = subdomain_client
    r = client.get("/login", base_url="https://ieltsband.com")
    assert r.status_code == 301
    assert r.headers["Location"] == "https://app.ieltsband.com/login"


def test_apex_signup_redirects_to_app_subdomain(subdomain_client):
    client, _ = subdomain_client
    r = client.get("/signup", base_url="https://ieltsband.com")
    assert r.status_code == 301
    assert r.headers["Location"] == "https://app.ieltsband.com/signup"


def test_apex_app_redirects_to_subdomain_root(subdomain_client):
    client, _ = subdomain_client
    r = client.get("/app", base_url="https://ieltsband.com")
    assert r.status_code == 301
    assert r.headers["Location"] == "https://app.ieltsband.com/"


def test_apex_landing_page_unaffected(subdomain_client):
    client, _ = subdomain_client
    r = client.get("/", base_url="https://ieltsband.com")
    assert r.status_code == 200


def test_subdomain_root_redirects_to_login_when_logged_out(subdomain_client):
    client, _ = subdomain_client
    r = client.get("/", base_url="https://app.ieltsband.com")
    assert r.status_code == 302
    assert r.headers["Location"] == "/login"


def test_subdomain_login_page_renders(subdomain_client):
    client, _ = subdomain_client
    r = client.get("/login", base_url="https://app.ieltsband.com")
    assert r.status_code == 200


def test_subdomain_root_serves_app_shell_when_logged_in(subdomain_client, monkeypatch):
    client, flaskapp = subdomain_client

    def fake_verify(id_token):
        return {
            "uid": "sub-test-uid", "email": "sub@example.com", "email_verified": True,
            "name": "Sub Test", "firebase": {"sign_in_provider": "password"},
        }
    monkeypatch.setattr(flaskapp.firebase_admin_setup, "verify_id_token", fake_verify)

    # Log in and land on the app shell -- both on the SAME app.<domain>
    # subdomain now, so this also exercises the ordinary same-host
    # session flow, not a cross-domain cookie-sharing scenario.
    r = client.post(
        "/auth/session", json={"idToken": "fake"}, base_url="https://app.ieltsband.com"
    )
    assert r.status_code == 200

    r = client.get("/", base_url="https://app.ieltsband.com")
    assert r.status_code == 200
    assert b"IELTSBand" in r.data


def test_next_param_rejects_arbitrary_external_url(subdomain_client):
    """The open-redirect guard: an attacker-supplied ?next= pointing at a
    domain we don't own must never be honored."""
    client, _ = subdomain_client
    r = client.get(
        "/login?next=https://evil.example.com/phish",
        base_url="https://app.ieltsband.com",
    )
    assert r.status_code == 200
    body = r.data.decode()
    assert "evil.example.com" not in body


def test_next_param_accepts_relative_path(subdomain_client):
    client, _ = subdomain_client
    r = client.get(
        "/login?next=/app",
        base_url="https://app.ieltsband.com",
    )
    assert r.status_code == 200
    assert '"/app"' in r.data.decode()