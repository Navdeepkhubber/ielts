import io
import json
import os
from flask import Flask, jsonify, request, send_file, render_template, abort

from lib import test_loader, pdf_render, scoring, storage, scaffold

app = Flask(__name__)


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
        except Exception as e:
            print(f"[scaffold] scan failed: {e}")

    threading.Thread(target=_target, name="scaffold", daemon=True).start()


def _combined_id(mock_id, test_name):
    return f"{mock_id}::{test_name}"


# ---------- Pages ----------

@app.route("/")
def index():
    return render_template("index.html")


# ---------- Mock / test discovery ----------

@app.route("/api/mocks")
def api_mocks():
    return jsonify(test_loader.list_mocks())


@app.route("/api/mocks/<mock_id>")
def api_mock_manifest(mock_id):
    try:
        manifest = test_loader.load_manifest(mock_id)
    except FileNotFoundError:
        abort(404)
    return jsonify(manifest)


@app.route("/api/mocks/<mock_id>/tests/<test_name>")
def api_test_config(mock_id, test_name):
    try:
        _, cfg = test_loader.load_test_config(mock_id, test_name)
    except FileNotFoundError:
        abort(404)
    return jsonify(cfg)


@app.route("/api/mocks/<mock_id>/tests/<test_name>/content")
def api_test_content(mock_id, test_name):
    """Extracted section text (content/<Test N>.json) for the text view.
    404 when not extracted -- the frontend falls back to page images."""
    path = os.path.join(test_loader.mock_folder(mock_id), "content", f"{test_name}.json")
    if not os.path.isfile(path):
        abort(404)
    with open(path) as f:
        return jsonify(json.load(f))


# ---------- main.pdf page images (reading & writing both live here) ----------

@app.route("/api/mocks/<mock_id>/page")
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
def api_start_attempt():
    data = request.json
    attempt_id = storage.start_attempt(
        test_id=_combined_id(data["mock_id"], data["test_name"]),
        section=data["section"],
        time_allowed_seconds=data["time_allowed_seconds"],
    )
    return jsonify({"attempt_id": attempt_id})


@app.route("/api/attempts/<int:attempt_id>/submit", methods=["POST"])
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
def api_history():
    test_id = request.args.get("test_id")
    section = request.args.get("section")
    return jsonify(storage.history(test_id=test_id, section=section))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    # With the debug reloader, app.py runs twice; only the serving child
    # process sets WERKZEUG_RUN_MAIN. Without the reloader, it's absent.
    if not debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        _run_scaffold_in_background()
    app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=debug)
