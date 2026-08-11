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

PUBLIC_BASE_DOMAIN = os.environ.get("PUBLIC_BASE_DOMAIN", "").strip().lower() or None


def _app_host():
    return f"app.{PUBLIC_BASE_DOMAIN}" if PUBLIC_BASE_DOMAIN else None


def _app_origin():
    return f"https://{_app_host()}" if PUBLIC_BASE_DOMAIN else None


def _dashboard_url():
    if PUBLIC_BASE_DOMAIN:
        return f"{_app_origin()}/"
    return url_for("app_shell")


def _is_safe_next(value):
    return bool(value) and value.startswith("/") and not value.startswith("//")


def _is_admin():
    """Content-review access control.

    Production uses ADMIN_EMAILS (comma-separated, case-insensitive). For
    local development only, FLASK_DEBUG=1 with ADMIN_EMAILS unset allows a
    signed-in developer to open the review portal without another setup
    step. Production never falls back to this behaviour.
    """
    user = auth.current_user()
    email = (user or {}).get("email", "").strip().lower()
    configured = {
        x.strip().lower()
        for x in os.environ.get("ADMIN_EMAILS", "").split(",")
        if x.strip()
    }
    if configured:
        return email in configured
    return _is_debug and bool(email)


if PUBLIC_BASE_DOMAIN:
    app.config["SESSION_COOKIE_DOMAIN"] = f".{PUBLIC_BASE_DOMAIN}"
    app.config["SESSION_COOKIE_SECURE"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


if PUBLIC_BASE_DOMAIN:
    @app.before_request
    def _route_by_subdomain():
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
    """Auto-scaffold newly-dumped mock folders in a background thread."""
    import threading

    def _target():
        try:
            scaffold.scan_and_scaffold(verbose=True)
            print("[scaffold] scan complete.", flush=True)
            root = os.path.dirname(os.path.abspath(__file__))
            with open(os.path.join(root, "NEEDS_ATTENTION.md"), "w") as f:
                f.write(report.generate_report())
            print("[scaffold] wrote NEEDS_ATTENTION.md", flush=True)
        except Exception as e:
            print(f"[scaffold] scan failed: {e}", flush=True)

    threading.Thread(target=_target, name="scaffold", daemon=True).start()


def _combined_id(mock_id, test_name):
    return f"{mock_id}::{test_name}"


def _own_attempt_or_404(attempt_id):
    attempt = storage.get_attempt(attempt_id)
    if attempt is None or attempt.get("user_id") != session.get("user_id"):
        abort(404, "No such attempt")
    return attempt


# ---------- Pages ----------

@app.route("/")
def landing():
    if session.get("user_id"):
        return redirect(_dashboard_url())
    return render_template("landing.html")


@app.route("/band-calculator")
def band_calculator_page():
    return render_template("band-calculator.html")


@app.route("/signup")
def signup():
    if session.get("user_id"):
        return redirect(_dashboard_url())
    return render_template("signup.html")


@app.route("/login")
def login():
    if session.get("user_id"):
        return redirect(_dashboard_url())
    next_path = request.args.get("next")
    if not _is_safe_next(next_path):
        next_path = "/" if PUBLIC_BASE_DOMAIN else url_for("app_shell")
    return render_template("login.html", next=next_path)


@app.route("/auth/session", methods=["POST"])
def auth_session():
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
        name=decoded.get("name", ""),
    )
    session["user_id"] = user["id"]
    return jsonify({"ok": True})


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    if PUBLIC_BASE_DOMAIN:
        return redirect(f"https://{PUBLIC_BASE_DOMAIN}/")
    return redirect(url_for("landing"))


@app.route("/app")
@login_required
def app_shell():
    return render_template("index.html", user=auth.current_user())


@app.route("/admin/content-review")
@login_required
def admin_content_review():
    """Private OCR/content QA portal for the site owner."""
    if not _is_admin():
        abort(403)
    return render_template("admin-content-review.html", user=auth.current_user())


@app.route("/api/band-calculator", methods=["POST"])
def api_band_calculator():
    data = request.get_json(silent=True) or {}
    section = data.get("section")
    if section not in ("reading", "listening"):
        return jsonify({"error": "section must be 'reading' or 'listening'."}), 400
    variant = data.get("variant", "academic")
    if variant not in ("academic", "general"):
        return jsonify({"error": "variant must be 'academic' or 'general'."}), 400
    try:
        correct_count = int(data.get("correct_count"))
    except (TypeError, ValueError):
        return jsonify({"error": "correct_count must be a whole number."}), 400
    if not 0 <= correct_count <= 40:
        return jsonify({"error": "correct_count must be between 0 and 40."}), 400
    return jsonify(scoring.band_explanation(correct_count, 40, section, variant))


# ---------- Mock / test discovery ----------

@app.route("/api/mocks")
@login_required
def api_mocks():
    return jsonify(test_loader.list_mocks())


@app.route("/api/mocks/<mock_id>")
@login_required
def api_mock_manifest(mock_id):
    try:
        manifest = test_loader.load_manifest(mock_id)
    except FileNotFoundError:
        abort(404)
    return jsonify(manifest)


@app.route("/api/mocks/<mock_id>/tests/<test_name>")
@login_required
def api_test_config(mock_id, test_name):
    try:
        _, cfg = test_loader.load_test_config(mock_id, test_name)
    except FileNotFoundError:
        abort(404)
    return jsonify(cfg)


@app.route("/api/mocks/<mock_id>/tests/<test_name>/content")
@login_required
def api_test_content(mock_id, test_name):
    path = test_loader.cached_file(mock_id, os.path.join("content", f"{test_name}.json"))
    if path is None:
        abort(404)
    with open(path) as f:
        return jsonify(json.load(f))


@app.route("/api/mocks/<mock_id>/tests/<test_name>/answer-key-page")
@login_required
def api_answer_key_page(mock_id, test_name):
    section = request.args.get("section", "")
    meta_path = test_loader.cached_file(mock_id, ".answer_key_meta.json")
    if meta_path is None:
        abort(404)
    with open(meta_path) as f:
        meta = json.load(f)
    entry = meta.get(test_name, {}).get(section)
    if not entry or not entry.get("page"):
        abort(404)
    return jsonify({"page": entry["page"]})


# ---------- main.pdf page images (reading & writing both live here) ----------

@app.route("/api/mocks/<mock_id>/page")
@login_required
def api_pdf_page(mock_id):
    page = int(request.args.get("page", 1))
    try:
        path = test_loader.main_pdf_path(mock_id)
        png = pdf_render.render_page(path, page)
    except (FileNotFoundError, IndexError) as e:
        abort(404, str(e))
    return send_file(io.BytesIO(png), mimetype="image/png")


# ---------- Listening audio ----------

@app.route("/api/mocks/<mock_id>/tests/<test_name>/audio")
@login_required
def api_listening_audio(mock_id, test_name):
    file = request.args.get("file")
    try:
        path = test_loader.audio_path(mock_id, test_name, file)
    except FileNotFoundError:
        abort(404)
    if not os.path.isfile(path):
        abort(404)
    return send_file(path, mimetype="audio/mpeg")


# ---------- Attempt lifecycle ----------

@app.route("/api/attempts/start", methods=["POST"])
@login_required
def api_start_attempt():
    data = request.json
    attempt_id = storage.start_attempt(
        test_id=_combined_id(data["mock_id"], data["test_name"]),
        section=data["section"],
        time_allowed_seconds=data["time_allowed_seconds"],
        user_id=session["user_id"],
    )
    return jsonify({"attempt_id": attempt_id})


@app.route("/api/attempts/<attempt_id>/submit", methods=["POST"])
@login_required
def api_submit_attempt(attempt_id):
    data = request.json
    mock_id = data["mock_id"]
    test_name = data["test_name"]
    section = data["section"]
    user_answers = data.get("answers", {})
    auto_submitted = data.get("auto_submitted", False)

    if section in ("reading", "listening"):
        answer_key = test_loader.load_answers(mock_id, test_name, section)
        _, test_cfg = test_loader.load_test_config(mock_id, test_name)
        variant = test_cfg.get("variant", "academic")
        result = scoring.mark_section(user_answers, answer_key, section=section, variant=variant)
        time_taken = storage.submit_attempt(
            attempt_id,
            correct_count=result["correct_count"],
            total=result["total"],
            band_estimate=result["band_estimate"],
            detail=result["results"],
            auto_submitted=auto_submitted,
        )
        result["time_taken_seconds"] = time_taken
        return jsonify(result)

    if section == "writing":
        time_taken = storage.submit_attempt(
            attempt_id,
            detail={"essay": user_answers.get("essay", "")},
            auto_submitted=auto_submitted,
        )
        return jsonify({"time_taken_seconds": time_taken})

    abort(400, "Unknown section")


@app.route("/api/writing/feedback", methods=["POST"])
@login_required
def api_writing_feedback():
    from lib import writing_feedback
    data = request.json
    result = writing_feedback.get_feedback(
        task_type=data.get("task_type", "task2"),
        prompt_description=data.get("prompt_description", ""),
        essay_text=data.get("essay_text", ""),
    )
    return jsonify(result)
