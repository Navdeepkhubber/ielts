def test_landing_page_loads(client):
    assert client.get("/").status_code == 200


def test_login_and_signup_pages_render(client):
    r_login = client.get("/login")
    r_signup = client.get("/signup")
    assert r_login.status_code == 200
    assert r_signup.status_code == 200

    signup_html = r_signup.data.decode()
    assert "check-length" in signup_html
    assert "check-number" in signup_html
    assert "check-special" in signup_html
    assert "password-toggle" in signup_html
    assert "contact@ieltsband.com" in signup_html

    login_html = r_login.data.decode()
    assert "password-toggle" in login_html
    assert "contact@ieltsband.com" in login_html


def test_app_shell_requires_login(client):
    r = client.get("/app")
    assert r.status_code == 302


def test_protected_api_requires_login(client):
    r = client.get("/api/mocks")
    assert r.status_code == 401
    assert r.get_json()["error"] == "login required"


def test_verified_email_login_creates_session(client, verified_token):
    r = client.post("/auth/session", json={"idToken": "fake"})
    assert r.status_code == 200
    assert r.get_json() == {"ok": True}
    assert client.get("/app").status_code == 200
    assert client.get("/api/me").get_json()["email"] == "test@example.com"


def test_unverified_email_password_is_rejected(client, monkeypatch):
    import lib.firebase_admin_setup as fas
    import app as flaskapp

    def fake_verify(id_token):
        return {
            "uid": "unverified-uid", "email": "unverified@example.com",
            "email_verified": False, "name": "Unverified",
            "firebase": {"sign_in_provider": "password"},
        }

    monkeypatch.setattr(fas, "verify_id_token", fake_verify)
    monkeypatch.setattr(flaskapp.firebase_admin_setup, "verify_id_token", fake_verify)

    r = client.post("/auth/session", json={"idToken": "fake"})
    assert r.status_code == 403
    assert client.get("/app").status_code == 302


def test_google_signin_bypasses_email_verification(client, monkeypatch):
    import lib.firebase_admin_setup as fas
    import app as flaskapp

    def fake_verify(id_token):
        return {
            "uid": "google-uid", "email": "googleuser@example.com",
            "email_verified": False,  # Firebase doesn't set this for Google, by design
            "name": "Google User", "firebase": {"sign_in_provider": "google.com"},
        }

    monkeypatch.setattr(fas, "verify_id_token", fake_verify)
    monkeypatch.setattr(flaskapp.firebase_admin_setup, "verify_id_token", fake_verify)

    r = client.post("/auth/session", json={"idToken": "fake"})
    assert r.status_code == 200


def test_missing_id_token_is_rejected(client):
    r = client.post("/auth/session", json={})
    assert r.status_code == 400


def test_token_verification_failure_gives_diagnosable_error(client, monkeypatch):
    """Regression test: a verification failure must not silently swallow
    the real reason. In debug mode (as tests run), the response should
    include the underlying exception detail rather than only the generic
    user-facing message, so this failure mode is actually diagnosable."""
    import lib.firebase_admin_setup as fas
    import app as flaskapp

    def fake_verify_raises(id_token):
        raise ValueError("service account project does not match token audience")

    monkeypatch.setattr(fas, "verify_id_token", fake_verify_raises)
    monkeypatch.setattr(flaskapp.firebase_admin_setup, "verify_id_token", fake_verify_raises)

    r = client.post("/auth/session", json={"idToken": "fake"})
    assert r.status_code == 401
    assert "debug detail" in r.get_json()["error"]
    assert "does not match token audience" in r.get_json()["error"]


def test_attempt_lifecycle_and_history(client, verified_token):
    import lib.storage as storage_mod

    client.post("/auth/session", json={"idToken": "fake"})

    attempt_id = storage_mod.start_attempt(
        "Mock 19::Test 1", "reading", 3600, user_id="test-uid"
    )
    assert isinstance(attempt_id, str)  # Firestore doc ids are strings, not ints

    detail = {"1": {"given": "TRUE", "correct": "TRUE", "is_correct": True}}
    storage_mod.submit_attempt(
        attempt_id, correct_count=1, total=1, band_estimate=9.0, detail=detail
    )

    r = client.get(f"/api/attempts/{attempt_id}/detail")
    assert r.status_code == 200
    body = r.get_json()
    assert body["correct_count"] == 1
    assert body["results"] == detail

    r = client.get("/api/history")
    assert r.status_code == 200
    assert len(r.get_json()) == 1

    r = client.get(f"/api/attempts/{attempt_id}/band-explanation")
    assert r.status_code == 200


def test_manual_score_then_remark_is_refused(client, verified_token):
    import lib.storage as storage_mod

    client.post("/auth/session", json={"idToken": "fake"})
    attempt_id = storage_mod.start_attempt(
        "Mock 19::Test 1", "reading", 3600, user_id="test-uid"
    )
    storage_mod.submit_attempt(
        attempt_id, correct_count=None, total=40,
        detail={str(i): {"given": "", "correct": "X", "is_correct": None} for i in range(1, 41)},
    )

    r = client.post(f"/api/attempts/{attempt_id}/manual-score", json={"correct_count": 30})
    assert r.status_code == 200
    assert r.get_json()["correct_count"] == 30

    # A hand-tallied score must never be silently overwritten by re-marking
    # against the (possibly still-blank) JSON answer key.
    r = client.post(f"/api/attempts/{attempt_id}/remark")
    assert r.status_code == 400


def test_cross_user_cannot_see_or_touch_others_attempt(client, verified_token, monkeypatch):
    import app as flaskapp
    import lib.firebase_admin_setup as fas
    import lib.storage as storage_mod

    client.post("/auth/session", json={"idToken": "fake"})
    attempt_id = storage_mod.start_attempt(
        "Mock 19::Test 1", "reading", 3600, user_id="test-uid"
    )
    storage_mod.submit_attempt(attempt_id, correct_count=1, total=1, band_estimate=9.0, detail={})

    def fake_verify_bob(id_token):
        return {
            "uid": "bob-uid", "email": "bob@example.com", "email_verified": True,
            "name": "Bob", "firebase": {"sign_in_provider": "google.com"},
        }

    monkeypatch.setattr(fas, "verify_id_token", fake_verify_bob)
    monkeypatch.setattr(flaskapp.firebase_admin_setup, "verify_id_token", fake_verify_bob)

    bob_client = flaskapp.app.test_client()
    bob_client.post("/auth/session", json={"idToken": "fake-bob"})

    assert bob_client.get(f"/api/attempts/{attempt_id}/detail").status_code == 404
    assert bob_client.get("/api/history").get_json() == []


def test_logout_clears_session(client, verified_token):
    client.post("/auth/session", json={"idToken": "fake"})
    assert client.get("/app").status_code == 200

    r = client.post("/logout")
    assert r.status_code == 302
    assert client.get("/app").status_code == 302