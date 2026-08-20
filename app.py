import io
import json
import os

# Local dev convenience only: if a .env file is present and python-dotenv
# is installed, load it. Silently does nothing otherwise -- production
# (Render or wherever) sets real environment variables directly, .env is
# gitignored so it's never even present in a deployed container, and
# load_dotenv() never overrides a variable that's already set, so this
# can't clobber real platform config even if it somehow did run there.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from flask import Flask, jsonify, request, send_file, render_template, abort, session, redirect, url_for

import time

_startup_time = time.perf_counter()

from lib import test_loader
print(f"[startup] test_loader: {time.perf_counter() - _startup_time:.2f}s", flush=True)

from lib import pdf_render
print(f"[startup] pdf_render: {time.perf_counter() - _startup_time:.2f}s", flush=True)

from lib import scoring
print(f"[startup] scoring: {time.perf_counter() - _startup_time:.2f}s", flush=True)

from lib import storage
print(f"[startup] storage: {time.perf_counter() - _startup_time:.2f}s", flush=True)

from lib import scaffold
print(f"[startup] scaffold: {time.perf_counter() - _startup_time:.2f}s", flush=True)

from lib import report
print(f"[startup] report: {time.perf_counter() - _startup_time:.2f}s", flush=True)

from lib import auth
print(f"[startup] auth: {time.perf_counter() - _startup_time:.2f}s", flush=True)

from lib import firebase_admin_setup
print(f"[startup] firebase_admin_setup: {time.perf_counter() - _startup_time:.2f}s", flush=True)

from lib.auth import login_required
print(f"[startup] ALL IMPORTS: {time.perf_counter() - _startup_time:.2f}s", flush=True)

app = Flask(__name__)

@app.route("/health")
def health():
    return "OK", 200

_is_debug = os.environ.get("FLASK_DEBUG", "1") == "1"
app.secret_key = os.environ.get("FLASK_SECRET_KEY")
if not app.secret_key:
    if _is_debug:
        # Local dev only -- fine as a single process; restarting just logs
        # everyone out, which is harmless for local testing.
        app.secret_key = os.urandom(24)
    else:
        raise RuntimeError(
            "FLASK_SECRET_KEY must be set outside local development. A "
            "random per-process key breaks sessions the moment more than "
            "one worker process exists (which gunicorn does by default) "
            "-- one worker signs a cookie, a different worker can't "
            "verify it, and logins fail unpredictably. Generate one with: "
            "python3 -c \"import secrets; print(secrets.token_hex(32))\""
        )

# ---------- Subdomain (app.<domain>) ----------
PUBLIC_BASE_DOMAIN = os.environ.get("PUBLIC_BASE_DOMAIN", "").strip().lower() or None


def _app_host():
    return f"app.{PUBLIC_BASE_DOMAIN}" if PUBLIC_BASE_DOMAIN else None


def _app_origin():
    return f"https://{_app_host()}" if PUBLIC_BASE_DOMAIN else None


def _dashboard_url():
    """Where a logged-in visitor belongs. On the apex/local-dev path this
    is unchanged (\"/app\"); once the subdomain is configured, the
    dashboard lives at its own subdomain root instead."""
    if PUBLIC_BASE_DOMAIN:
        return f"{_app_origin()}/"
    return url_for("app_shell")


def _is_safe_next(value):
    """Used for the `next` param on /login. Same-host relative paths only."""
    return bool(value) and value.startswith("/") and not value.startswith("//")


if PUBLIC_BASE_DOMAIN:
    app.config["SESSION_COOKIE_DOMAIN"] = f".{PUBLIC_BASE_DOMAIN}"
    app.config["SESSION_COOKIE_SECURE"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


@app.before_request
def _route_by_subdomain():
    if not PUBLIC_BASE_DOMAIN:
        return None

    host = request.host.split(":")[0].lower()
    app_host = _app_host()

    if host in (PUBLIC_BASE_DOMAIN, f"www.{PUBLIC_BASE_DOMAIN}"):
        if request.path in ("/login", "/signup"):
            qs = f"?{request.query_string.decode()}" if request.query_string else ""
            return redirect(f"{_app_origin()}{request.path}{qs}", code=301)
        if request.path == "/app" or request.path.startswith("/app/"):
            dest = request.path[len("/app"):] or "/"
            return redirect(f"{_app_origin()}{dest}", code=301)
        return None

    if host == app_host and request.path == "/":
        if session.get("user_id") is None:
            return redirect("/login", code=302)
        return app_shell.__wrapped__()

    return None


def _run_scaffold_in_background():
    import threading

    def _target():
        try:
            scaffold.scan_and_scaffold(verbose=True)
            print("[scaffold] scan complete.")
            root = os.path.dirname(os.path.abspath(__file__))
            with open(os.path.join(root, "NEEDS_ATTENTION.md"), "w") as f:
                f.write(report.generate_report())
            print("[scaffold] wrote NEEDS_ATTENTION.md")
        except Exception as e:
            print(f"[scaffold] scan failed: {e}")

    threading.Thread(target=_target, name="scaffold", daemon=True).start()


def _combined_id(mock_id, test_name):
    return f"{mock_id}::{test_name}"


def _own_attempt_or_404(attempt_id):
    """Fetches an attempt and 404s (not 403, to avoid confirming which
    attempt ids exist) if it isn't the logged-in user's -- old pre-account
    attempts (user_id NULL) are treated as belonging to no one."""
    attempt = storage.get_attempt(attempt_id)
    if attempt is None or attempt.get("user_id") != session.get("user_id"):
        abort(404, "No such attempt")
    return attempt


# ---------- Pages ----------

@app.route("/")
def landing():
    """Public marketing/welcome page. Logged-in visitors are sent straight
    to the app instead of seeing the pitch for something they already use."""
    if session.get("user_id"):
        return redirect(_dashboard_url())
    return render_template("landing.html")


@app.route("/band-calculator")
def band_calculator_page():
    """Public, no-login IELTS band score calculator."""
    return render_template("band-calculator.html")


@app.route("/signup")
def signup():
    """Rendering only -- the actual account creation happens client-side
    via the Firebase SDK in production."""
    if auth._local_dev_enabled():
        session.setdefault("user_id", auth.LOCAL_DEV_USER_ID)
        return redirect(_dashboard_url())
    if session.get("user_id"):
        return redirect(_dashboard_url())
    return render_template("signup.html")


@app.route("/login")
def login():
    """Production login page; localhost/local-dev skips Firebase login."""
    if auth._local_dev_enabled():
        session.setdefault("user_id", auth.LOCAL_DEV_USER_ID)
        return redirect(_dashboard_url())
    if session.get("user_id"):
        return redirect(_dashboard_url())
    next_path = request.args.get("next")
    if not _is_safe_next(next_path):
        next_path = "/" if PUBLIC_BASE_DOMAIN else url_for("app_shell")
    return render_template("login.html", next=next_path)


@app.route("/auth/session", methods=["POST"])
def auth_session():
    """
    Called by login.html/signup.html once Firebase has authenticated the
    person in the browser. Localhost never needs this endpoint, but it stays
    fully enforced for production hosts.
    """
    if auth._local_dev_enabled():
        session["user_id"] = auth.LOCAL_DEV_USER_ID
        return jsonify({"ok": True, "local_dev": True})

    data = request.get_json(silent=True) or {}
    id_token = data.get("idToken")
    if not id_token:
        return jsonify({"error": "Missing idToken."}), 400

    try:
        decoded = firebase_admin_setup.verify_id_token(id_token)
    except Exception as e:
        app.logger.exception("Firebase ID token verification failed")
        message = "That sign-in couldn't be verified. Please try again."
        if app.debug:
            message += f" (debug detail: {e})"
        return jsonify({"error": message}), 401

    provider = decoded.get("firebase", {}).get("sign_in_provider")
    if provider != "google.com" and not decoded.get("email_verified"):
        return jsonify({"error": "Please verify your email address first, then log in."}), 403

    user = auth.get_or_create_user(
        firebase_uid=decoded["uid"],
        email=decoded.get("email", ""),
        name=decoded.get("name") or decoded.get("email", "").split("@")[0],
    )
    session["user_id"] = user["id"]
    return jsonify({"ok": True})
