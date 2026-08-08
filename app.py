import io
import json
import os
from flask import Flask, jsonify, request, send_file, render_template, abort

from lib import test_loader, pdf_render, scoring, storage, scaffold, report

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
            root = os.path.dirname(os.path.abspath(__file__))
            with open(os.path.join(root, "NEEDS_ATTENTION.md"), "w") as f:
                f.write(report.generate_report())
            print("[scaffold] wrote NEEDS_ATTENTION.md")
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


@app.route("/api/mocks/<mock_id>/tests/<test_name>/answer-key-page")
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
    meta_path = os.path.join(test_loader.mock_folder(mock_id), ".answer_key_meta.json")
    if not os.path.isfile(meta_path):
        abort(404)
    with open(meta_path) as f:
        meta = json.load(f)
    entry = meta.get(test_name, {}).get(section)
    if not entry or not entry.get("page"):
        abort(404)
    return jsonify({"page": entry["page"]})


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


def _variant_for_test_id(test_id):
    """Best-effort lookup of a test's variant from its manifest; falls
    back to "academic" if the mock/test no longer exists on disk."""
    try:
        mock_id, test_name = test_id.split("::", 1)
        _, test_cfg = test_loader.load_test_config(mock_id, test_name)
        return test_cfg.get("variant", "academic")
    except Exception:
        return "academic"


@app.route("/api/attempts/<int:attempt_id>/manual-score", methods=["POST"])
def api_manual_score(attempt_id):
    """
    Fills in (or corrects) a score by hand -- for an attempt that was
    recorded as unmarked because the answer key wasn't available at the
    time, or simply to self-tally against the answer-key page instead of
    typing every individual answer. Band is calculated automatically from
    the entered raw score using the same tables as auto-marking.
    """
    attempt = storage.get_attempt(attempt_id)
    if attempt is None:
        abort(404, "No such attempt")
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


@app.route("/api/attempts/<int:attempt_id>/detail")
def api_attempt_detail(attempt_id):
    """
    Full reconstructed result for a past attempt -- same shape the results
    page uses right after submitting (results/correct_count/total/
    band_estimate), plus mock_id/test_name/section, so a historical
    attempt from Progress can be viewed with the exact same analysis UI
    (tiles, per-part breakdown, filterable review, answer-key page viewer)
    instead of just a bare band number.
    """
    attempt = storage.get_attempt(attempt_id)
    if attempt is None:
        abort(404, "No such attempt")
    if attempt["section"] not in ("reading", "listening"):
        abort(400, "Only reading/listening sections have a full analysis view")
    if not attempt["detail_json"]:
        abort(404, "No per-question detail recorded for this attempt")

    mock_id, test_name = attempt["test_id"].split("::", 1)
    results = json.loads(attempt["detail_json"])
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


@app.route("/api/attempts/<int:attempt_id>/remark", methods=["POST"])
def api_remark_attempt(attempt_id):
    """
    Re-marks a past attempt against the CURRENT answer key -- for when a
    mistake in the answer key (a common occurrence with OCR-extracted
    keys) gets fixed after the fact. Without this, a corrected key only
    affects attempts taken from then on; the already-stored correct_count/
    band for earlier attempts stays frozen against the old, wrong key.
    Re-scores using the answers the person actually gave (from the stored
    detail_json), never asks them to retype anything.

    Refuses (hard guard, not just a UI hide) to touch an attempt whose
    score was entered by hand (manually_scored=1) -- that count came from
    the person checking their own answers against the physical book, which
    the JSON answer key may still be entirely or partially blank for.
    Re-deriving from that blank/partial key would silently overwrite a
    real manual tally with nothing (or a wrong partial count), which is
    exactly the kind of silent data loss this endpoint must never cause.
    """
    attempt = storage.get_attempt(attempt_id)
    if attempt is None:
        abort(404, "No such attempt")
    if attempt["section"] not in ("reading", "listening"):
        abort(400, "Only reading/listening sections can be re-marked")
    if attempt["manually_scored"]:
        abort(400, "This score was entered by hand, not derived from the answer key -- "
                    "re-checking would risk overwriting it with an incomplete auto-mark. "
                    "Edit the score directly with 'Enter score' instead if it needs correcting.")
    if not attempt["detail_json"]:
        abort(404, "No per-question detail recorded for this attempt -- nothing to re-mark")

    mock_id, test_name = attempt["test_id"].split("::", 1)
    old_results = json.loads(attempt["detail_json"])
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

    answers_path = os.path.join(test_loader.mock_folder(mock_id), "answers", test_name, f"{attempt['section']}.json")
    if not os.path.isfile(answers_path):
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


@app.route("/api/attempts/<int:attempt_id>/band-explanation")
def api_band_explanation(attempt_id):
    """Full working behind an attempt's band estimate, for the 'how was
    this calculated' popup -- works whether the score was auto-marked or
    entered by hand."""
    attempt = storage.get_attempt(attempt_id)
    if attempt is None or attempt["correct_count"] is None:
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
