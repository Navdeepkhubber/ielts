
"""
Regression tests for lib/firebase_admin_setup.py's credential detection.

This exists because of a real production incident: on Render, with no
FIREBASE_SERVICE_ACCOUNT_JSON set, the old code silently fell through to
`firebase_admin.initialize_app()` with no credentials at all. That call
never raises by itself (the App object is created lazily), so
initialization appeared to succeed -- the failure only surfaced later,
deep inside the SDK, the first time Auth/Firestore was actually used,
as a cryptic "A project ID is required" error with no indication of
what to actually do about it.

These tests exercise `_ensure_initialized()` directly (not through the
`db()`/`verify_id_token()` fixtures used elsewhere, which mock Firestore
entirely) so they test the real credential-resolution logic itself.
"""
import importlib
import json
import os
import tempfile

import pytest


@pytest.fixture
def fresh_fas(monkeypatch):
    """Reloads lib.firebase_admin_setup with a clean singleton and a
    clean slate of the env vars its logic reads, then restores whatever
    was there afterward."""
    import lib.firebase_admin_setup as fas

    env_vars = ("FIREBASE_SERVICE_ACCOUNT_JSON", "K_SERVICE", "GAE_APPLICATION", "GOOGLE_CLOUD_PROJECT")
    for v in env_vars:
        monkeypatch.delenv(v, raising=False)

    importlib.reload(fas)
    yield fas
    fas._app = None


def test_no_credential_and_not_on_google_cloud_fails_clearly(fresh_fas, monkeypatch):
    """The exact failure mode hit on Render: no service account configured,
    and nothing indicating we're on Google Cloud either."""
    monkeypatch.chdir(tempfile.mkdtemp())  # no serviceAccountKey.json underfoot
    with pytest.raises(RuntimeError) as exc_info:
        fresh_fas._ensure_initialized()
    message = str(exc_info.value)
    assert "No Firebase credentials configured" in message
    assert "Secret File" in message  # actionable, not just "it broke"


def test_credential_path_set_but_file_missing_fails_clearly(fresh_fas, monkeypatch):
    """The likely actual cause on Render: FIREBASE_SERVICE_ACCOUNT_JSON is
    set, but no file exists at that path (secret file never uploaded, or
    uploaded under a different name)."""
    monkeypatch.setenv("FIREBASE_SERVICE_ACCOUNT_JSON", "/etc/secrets/serviceAccountKey.json")
    with pytest.raises(RuntimeError) as exc_info:
        fresh_fas._ensure_initialized()
    message = str(exc_info.value)
    assert "no file exists there" in message
    assert "/etc/secrets/serviceAccountKey.json" in message


def test_malformed_credential_file_fails_clearly(fresh_fas, monkeypatch):
    """File exists at the configured path, but isn't a real service
    account key -- should still fail with an actionable message, not a
    raw SDK stack trace."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"not": "a real service account key"}, f)
        bad_path = f.name

    monkeypatch.setenv("FIREBASE_SERVICE_ACCOUNT_JSON", bad_path)
    with pytest.raises(RuntimeError) as exc_info:
        fresh_fas._ensure_initialized()
    assert "couldn't be used as a service account credential" in str(exc_info.value) \
        or "couldn't use it as a service account credential" in str(exc_info.value)


def test_google_cloud_marker_present_does_not_trigger_our_own_refusal(fresh_fas, monkeypatch):
    """When actually running on Google Cloud (detected via K_SERVICE, the
    env var Cloud Run sets on itself), we should attempt Application
    Default Credentials rather than immediately refusing. Whether ADC
    itself resolves successfully depends on a real GCP metadata server,
    which this test environment doesn't have -- initialize_app() is lazy
    either way and won't fail until first actual use. What this test
    actually pins down is narrower but important: taking this branch
    must never produce our own "No Firebase credentials configured"
    refusal, which is the bug this whole file exists to prevent."""
    monkeypatch.setenv("K_SERVICE", "ieltsband")
    try:
        fresh_fas._ensure_initialized()
    except RuntimeError as e:
        assert "No Firebase credentials configured" not in str(e)