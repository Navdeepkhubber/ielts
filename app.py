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
#
# Entirely inert -- and the rest of the app behaves exactly as before --
# unless PUBLIC_BASE_DOMAIN is set. It's only set in production (see
# SETUP.md), specifically so local dev never needs "app.localhost" or any
# DNS setup at all: every existing /login, /signup, /app URL keeps
# working unchanged locally.
#
# Login/signup and the dashboard share ONE subdomain (not two separate
# ones) so the whole site needs only 2 custom domains total (apex +
# this one) -- Render's free tier caps custom domains at 2, and a third
# costs money for no functional benefit here. Sharing one host also
# means login and the dashboard never need a cross-domain redirect at
# all: every `next` value stays a same-host relative path.
#
# This deliberately does NOT use Flask's built-in subdomain_matching +
# SERVER_NAME -- that requires the Host header to match SERVER_NAME
# exactly (including port), which is a well-known footgun for local dev,
# and by default makes every route that doesn't explicitly declare a
# subdomain stop matching non-apex hosts at all. Plain host-based
# redirects in a before_request hook (below) sidestep both problems.
PUBLIC_BASE_DOMAIN = os.environ.get("PUBLIC_BASE_DOMAIN", "").strip().lower() or None


def _app_host():
    return f"app.{PUBLIC_BASE_DOMAIN}" if PUBLIC_BASE_DOMAIN else None


def _app_origin():
    return f"https://{_app_host()}" if PUBLIC_BASE_DOMAIN else None


def _dashboard_url():
    """Where a logged-in visitor belongs. On the apex/local-dev path this
    is unchanged ("/app"); once the subdomain is configured, the
    dashboard lives at its own subdomain root instead."""
    if PUBLIC_BASE_DOMAIN:
        return f"{_app_origin()}/"
    return url_for("app_shell")


def _is_safe_next(value):
    """Used for the `next` param on /login. Same-host relative paths
    only -- there's no cross-domain case to support now that login/
    signup and the dashboard all live on the same app.<domain>
    subdomain, so this stays a plain open-redirect guard rather than
    needing an allowlist of external hosts."""
    return bool(value) and value.startswith("/") and not value.startswith("//")


if PUBLIC_BASE_DOMAIN:
    # Share the session cookie between the apex domain and app.<domain>
    # -- by default Flask's session cookie is host-only (tied to the
    # exact host that set it), which would otherwise mean a session
    # started on one wouldn't be recognized on the other (e.g. an old
    # bookmark to the bare apex /app).
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
        # From the bare apex/www, send /login, /signup, /app to the
        # subdomain -- one canonical URL per page in production.
        if request.path in ("/login", "/signup"):
            qs = f"?{request.query_string.decode()}" if request.query_string else ""
            return redirect(f"{_app_origin()}{request.path}{qs}", code=301)
        if request.path == "/app" or request.path.startswith("/app/"):
            dest = request.path[len("/app"):] or "/"
            return redirect(f"{_app_origin()}{dest}", code=301)
        return None

    if host == app_host and request.path == "/":
        # Serve the app shell directly at the bare subdomain root (rather
        # than redirecting to .../app on the same host), so the address
        # bar shows exactly "app.<domain>" with no extra path.
        if session.get("user_id") is None:
            return redirect("/login", code=302)
        return app_shell.__wrapped__()

    return None


def _run_scaffold_in_background():
    """
    Auto-scaffold newly-dumped mock folders (main.pdf + audio/Test N/...)
    with manifest.json + blank answer files. Runs in a background thread so
    the server is usable immediately -- newly-scanned mocks appear once
    their manifest is written (refresh the page).

    IMPORTANT: this must only be called from the __main__ block, never at
    module import time. On macOS, multiprocessing (used for parallel OCR)
    spawns workers by re-importing the main script; a module-level call
    here would re-trigger scaffolding inside every worker, breaking
    parallel OCR entirely (it silently fell back to slow serial mode).
    """
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


@app.route("/signup")
def signup():
    """Rendering only -- the actual account creation happens client-side
    via the Firebase SDK (Google popup, or createUserWithEmailAndPassword
    + a verification email), which then calls POST /auth/session below."""
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
    """
    Called by login.html/signup.html once Firebase has authenticated the
    person in the browser. Verifies the ID token server-side (never trust
    a client-asserted uid/email) before creating our own session cookie.

    Google sign-ins are accepted immediately -- Google has already done
    the verifying. Email/password sign-ins are only accepted once
    Firebase reports the address as verified, so a stolen or mistyped
    email can't be used to create/access an account.
    """
    data = request.get_json(silent=True) or {}
    id_token = data.get("idToken")
    if not id_token:
        return jsonify({"error": "Missing idToken."}), 400

    try:
        decoded = firebase_admin_setup.verify_id_token(id_token)
    except Exception as e:
        # Always log the real reason server-side -- swallowing it entirely
        # (the previous version of this handler did) makes this failure
        # mode undiagnosable. Common causes: serviceAccountKey.json missing/
        # wrong path, or belonging to a DIFFERENT Firebase project than the
        # one static/js/firebase-config.js points the browser at (the token's
        # audience won't match what the Admin SDK expects); the server's
        # system clock being off; or Firebase Admin never having initialized
        # at all (check for an earlier "Could not initialize Firebase Admin"
        # error in the logs, from lib/firebase_admin_setup.py).
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
    return redirect(url_for("landing"))


@app.route("/app")
@login_required
def app_shell():
    """The actual exam portal (mock tests + progress) -- everything that
    used to live at '/'. Only reachable once logged in."""
    return render_template("index.html", user=auth.current_user())


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
    """Extracted section text (content/<Test N>.json) for the text view.
    404 when not extracted -- the frontend falls back to page images."""
    path = test_loader.cached_file(mock_id, os.path.join("content", f"{test_name}.json"))
    if path is None:
        abort(404)
    with open(path) as f:
        return jsonify(json.load(f))


@app.route("/api/mocks/<mock_id>/tests/<test_name>/answer-key-page")
@login_required
def api_answer_key_page(mock_id, test_name):
    """
    ?section=reading|listening -- returns {"page": N} for the PDF page
    holding that section's printed answer key, so the results view can
    show it for manual comparison regardless of whether auto-extraction
    succeeded. Uses the .answer_key_meta.json breadcrumb the scaffolder
    leaves behind; 404 if that page was never identified (e.g. a book
    whose answer-key layout wasn't recognised at all).
    """
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
    """?page=7"""
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
    """?file=part1.mp3"""
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

    elif section == "writing":
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


# ---------- Progress dashboard ----------

@app.route("/api/history")
@login_required
def api_history():
    test_id = request.args.get("test_id")
    section = request.args.get("section")
    return jsonify(storage.history(test_id=test_id, section=section, user_id=session["user_id"]))


@app.route("/api/me")
@login_required
def api_me():
    return jsonify(auth.current_user())


def _variant_for_test_id(test_id):
    """Best-effort lookup of a test's variant from its manifest; falls
    back to "academic" if the mock/test no longer exists on disk."""
    try:
        mock_id, test_name = test_id.split("::", 1)
        _, test_cfg = test_loader.load_test_config(mock_id, test_name)
        return test_cfg.get("variant", "academic")
    except Exception:
        return "academic"


@app.route("/api/attempts/<attempt_id>/manual-score", methods=["POST"])
@login_required
def api_manual_score(attempt_id):
    """
    Fills in (or corrects) a score by hand -- for an attempt that was
    recorded as unmarked because the answer key wasn't available at the
    time, or simply to self-tally against the answer-key page instead of
    typing every individual answer. Band is calculated automatically from
    the entered raw score using the same tables as auto-marking.
    """
    attempt = _own_attempt_or_404(attempt_id)
    if attempt["section"] not in ("reading", "listening"):
        abort(400, "Only reading/listening sections have a numeric score")

    data = request.json or {}
    correct_count = data.get("correct_count")
    total = attempt["total"] or 40
    if not isinstance(correct_count, int) or not (0 <= correct_count <= total):
        abort(400, f"correct_count must be an integer between 0 and {total}")

    variant = _variant_for_test_id(attempt["test_id"])
    band = scoring.raw_score_to_band(correct_count, total, attempt["section"], variant)
    storage.update_manual_score(attempt_id, correct_count, band)
    return jsonify({"correct_count": correct_count, "total": total, "band_estimate": band})


@app.route("/api/attempts/<attempt_id>/detail")
@login_required
def api_attempt_detail(attempt_id):
    """
    Full reconstructed result for a past attempt -- same shape the results
    page uses right after submitting (results/correct_count/total/
    band_estimate), plus mock_id/test_name/section, so a historical
    attempt from Progress can be viewed with the exact same analysis UI
    (tiles, per-part breakdown, filterable review, answer-key page viewer)
    instead of just a bare band number.
    """
    attempt = _own_attempt_or_404(attempt_id)
    if attempt["section"] not in ("reading", "listening"):
        abort(400, "Only reading/listening sections have a full analysis view")
    if not attempt.get("detail"):
        abort(404, "No per-question detail recorded for this attempt")

    mock_id, test_name = attempt["test_id"].split("::", 1)
    results = attempt["detail"]
    unmarkable_count = sum(1 for r in results.values() if r.get("is_correct") is None)
    return jsonify({
        "mock_id": mock_id,
        "test_name": test_name,
        "section": attempt["section"],
        "results": results,
        "correct_count": attempt["correct_count"],
        "total": attempt["total"],
        "unmarkable_count": unmarkable_count,
        "band_estimate": attempt["band_estimate"],
        "time_taken_seconds": attempt["time_taken_seconds"],
        "manually_scored": bool(attempt["manually_scored"]),
        "unmarked": attempt["correct_count"] is None and attempt["total"] is not None
                    and unmarkable_count == len(results),
    })


@app.route("/api/attempts/<attempt_id>/remark", methods=["POST"])
@login_required
def api_remark_attempt(attempt_id):
    """
    Re-marks a past attempt against the CURRENT answer key -- for when a
    mistake in the answer key (a common occurrence with OCR-extracted
    keys) gets fixed after the fact. Without this, a corrected key only
    affects attempts taken from then on; the already-stored correct_count/
    band for earlier attempts stays frozen against the old, wrong key.
    Re-scores using the answers the person actually gave (from the stored
    detail), never asks them to retype anything.

    Refuses (hard guard, not just a UI hide) to touch an attempt whose
    score was entered by hand (manually_scored=1) -- that count came from
    the person checking their own answers against the physical book, which
    the JSON answer key may still be entirely or partially blank for.
    Re-deriving from that blank/partial key would silently overwrite a
    real manual tally with nothing (or a wrong partial count), which is
    exactly the kind of silent data loss this endpoint must never cause.
    """
    attempt = _own_attempt_or_404(attempt_id)
    if attempt["section"] not in ("reading", "listening"):
        abort(400, "Only reading/listening sections can be re-marked")
    if attempt["manually_scored"]:
        abort(400, "This score was entered by hand, not derived from the answer key -- "
                    "re-checking would risk overwriting it with an incomplete auto-mark. "
                    "Edit the score directly with 'Enter score' instead if it needs correcting.")
    if not attempt.get("detail"):
        abort(404, "No per-question detail recorded for this attempt -- nothing to re-mark")

    mock_id, test_name = attempt["test_id"].split("::", 1)
    old_results = attempt["detail"]
    given_answers = {q: r.get("given", "") for q, r in old_results.items()}

    # Confirm the mock/test still genuinely exists BEFORE touching anything.
    # load_answers() returns {} both when a mock/test is gone AND when the
    # answers file just hasn't been created -- neither should be silently
    # treated as "the key is blank, mark this unmarked", or a real existing
    # score would get destroyed by a missing-file/missing-mock condition
    # rather than an actual, legitimate blank key.
    try:
        test_loader.load_test_config(mock_id, test_name)
    except FileNotFoundError:
        abort(404, "This mock/test no longer exists on disk -- nothing was changed")

    if not test_loader.answers_exist(mock_id, test_name, attempt["section"]):
        abort(404, f"answers/{test_name}/{attempt['section']}.json is missing entirely -- nothing was changed")

    answer_key = test_loader.load_answers(mock_id, test_name, attempt["section"])
    variant = _variant_for_test_id(attempt["test_id"])
    result = scoring.mark_section(given_answers, answer_key, section=attempt["section"], variant=variant)

    if result.get("unmarked"):
        storage.update_full_score(attempt_id, None, result["total"], None, result["results"])
    else:
        storage.update_full_score(
            attempt_id, result["correct_count"], result["total"], result["band_estimate"], result["results"]
        )
    result["mock_id"] = mock_id
    result["test_name"] = test_name
    result["section"] = attempt["section"]
    result["time_taken_seconds"] = attempt["time_taken_seconds"]
    return jsonify(result)


@app.route("/api/attempts/<attempt_id>/band-explanation")
@login_required
def api_band_explanation(attempt_id):
    """Full working behind an attempt's band estimate, for the 'how was
    this calculated' popup -- works whether the score was auto-marked or
    entered by hand."""
    attempt = _own_attempt_or_404(attempt_id)
    if attempt["correct_count"] is None:
        abort(404, "No score recorded for this attempt yet")
    variant = _variant_for_test_id(attempt["test_id"])
    return jsonify(scoring.band_explanation(
        attempt["correct_count"], attempt["total"] or 40, attempt["section"], variant
    ))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    # With the debug reloader, app.py runs twice; only the serving child
    # process sets WERKZEUG_RUN_MAIN. Without the reloader, it's absent.
    if not debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        _run_scaffold_in_background()
    app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=debug)