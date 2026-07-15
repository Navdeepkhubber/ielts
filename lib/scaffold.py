"""
Auto-scaffolds new mock folders so the only manual work left is:
  1. dropping in main.pdf + audio/Test N/*.mp3
  2. sanity-checking the auto-detected page numbers / question ranges
     against your actual PDF (best-effort text-structure scan, see
     lib/pdf_structure.py) and fixing anything it got wrong
  3. filling in real answers in the generated answers/*.json files

It never overwrites anything you've already filled in. On each run it:
  - creates manifest.json if missing, with "listening" built from audio
    files found on disk, and "reading"/"writing" built from a best-effort
    scan of main.pdf's headings ("READING PASSAGE N", "SECTION N",
    "WRITING TASK N", "Questions X-Y") -- see lib/pdf_structure.py.
  - for an *existing* manifest, backfills any test that's missing a
    "reading" or "writing" block, or whose listening parts have an empty
    "pages" list, using the same PDF scan -- without touching anything
    you've already filled in yourself.
  - adds any newly-appeared "Test N" audio folders to an existing manifest.
  - creates answers/<Test N>/reading.json and listening.json with every
    question number pre-populated and an empty string as a placeholder
    value, if those files don't already exist.

The PDF scan only ever reads short heading lines to find page numbers --
it never stores or displays the actual passage/question/prompt text
anywhere. It's a best guess: run it, then eyeball the log output and the
generated manifest.json once, since heading wording varies across
publishers and it flags anything it wasn't confident about instead of
guessing silently.

Run standalone with `python3 scripts/scaffold_mocks.py`, or it runs
automatically once at app startup (see app.py).
"""
import json
import os
import re

from lib import pdf_render, pdf_structure

TESTS_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests")

QUESTIONS_PER_PART = 10  # fallback if the PDF scan can't find "Questions X-Y" for a listening part
READING_DEFAULT_MINUTES = 60
WRITING_TASK1_DEFAULT_MINUTES = 20
WRITING_TASK2_DEFAULT_MINUTES = 40


def _natural_key(name):
    """Sort 'Test 2' before 'Test 10', 'part2.mp3' before 'part10.mp3'."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def _discover_test_dirs(audio_root):
    if not os.path.isdir(audio_root):
        return []
    return sorted(
        (d for d in os.listdir(audio_root) if os.path.isdir(os.path.join(audio_root, d))),
        key=_natural_key,
    )


def _discover_audio_files(test_audio_dir):
    if not os.path.isdir(test_audio_dir):
        return []
    exts = (".mp3", ".m4a", ".wav", ".ogg")
    return sorted(
        (f for f in os.listdir(test_audio_dir) if f.lower().endswith(exts)),
        key=_natural_key,
    )


def _build_listening_block(test_name, audio_root, detected_parts=None):
    """
    detected_parts, if given, is pdf_structure's per-test "listening_parts"
    list: [{"pages": [...], "questions": [s, e] or None}, ...], matched to
    audio files in order. Falls back to a naive 10-question-per-part split
    for any part beyond what was detected, or if nothing was detected.
    """
    files = _discover_audio_files(os.path.join(audio_root, test_name))
    parts = []
    for i, filename in enumerate(files):
        detected = detected_parts[i] if detected_parts and i < len(detected_parts) else None
        if detected and detected.get("questions"):
            start, end = detected["questions"]
        else:
            start = i * QUESTIONS_PER_PART + 1
            end = start + QUESTIONS_PER_PART - 1
        pages = detected["pages"] if detected else []
        parts.append({"file": filename, "questions": [start, end], "pages": pages})
    return {"audio_folder": test_name, "parts": parts}


def _build_reading_block(detected_passages):
    if not detected_passages:
        return None
    passages = []
    for p in detected_passages:
        if not p.get("questions"):
            return None  # incomplete detection -- don't guess a broken reading block
        passages.append({"pages": p["pages"], "questions": p["questions"]})
    return {"duration_minutes": READING_DEFAULT_MINUTES, "passages": passages}


def _build_writing_block(detected_writing):
    if not detected_writing or "task1" not in detected_writing or "task2" not in detected_writing:
        return None
    return {
        "task1": {"page": detected_writing["task1"]["page"], "duration_minutes": WRITING_TASK1_DEFAULT_MINUTES},
        "task2": {"page": detected_writing["task2"]["page"], "duration_minutes": WRITING_TASK2_DEFAULT_MINUTES},
    }


def _placeholder_answers(question_ranges):
    """question_ranges: list of [start, end] inclusive -> {"1": "", "2": "", ...}"""
    out = {}
    for start, end in question_ranges:
        for q in range(start, end + 1):
            out[str(q)] = ""
    return out


def _find_pdf(mock_dir):
    """
    Returns the filename (not full path) of the PDF to use for this mock, or
    None if there isn't exactly one unambiguous candidate.
    Prefers a file literally named main.pdf if present; otherwise, if there
    is exactly one .pdf file in the folder, uses that.
    """
    if os.path.isfile(os.path.join(mock_dir, "main.pdf")):
        return "main.pdf"
    pdfs = sorted(f for f in os.listdir(mock_dir) if f.lower().endswith(".pdf"))
    if len(pdfs) == 1:
        return pdfs[0]
    return None  # zero or multiple PDFs -- can't guess, skip until resolved


def scan_and_scaffold(tests_root=None, verbose=True):
    """
    Scans tests_root (defaults to the app's tests/ folder) and creates/
    backfills manifest.json + answers/*.json for every mock folder that has
    a PDF. Never overwrites a field you've already filled in. Returns a
    list of human-readable log lines describing what it did (or found wrong).
    """
    tests_root = tests_root or TESTS_ROOT
    log = []
    if not os.path.isdir(tests_root):
        return log

    for mock_name in sorted(os.listdir(tests_root)):
        mock_dir = os.path.join(tests_root, mock_name)
        if not os.path.isdir(mock_dir):
            continue
        pdf_filename = _find_pdf(mock_dir)
        audio_root = os.path.join(mock_dir, "audio")
        if pdf_filename is None:
            pdfs = [f for f in os.listdir(mock_dir) if f.lower().endswith(".pdf")]
            if len(pdfs) > 1:
                log.append(
                    f"[{mock_name}] SKIPPED: found {len(pdfs)} PDFs ({', '.join(pdfs)}) "
                    f"and none is named 'main.pdf' -- rename one to main.pdf, or add "
                    f"manifest.json by hand with the correct \"pdf_file\"."
                )
            continue  # not a (complete) mock folder yet -- nothing to scaffold
        pdf_path = os.path.join(mock_dir, pdf_filename)

        manifest_path = os.path.join(mock_dir, "manifest.json")
        test_dirs = _discover_test_dirs(audio_root)

        try:
            total_pages = pdf_render.page_count(pdf_path)
        except Exception as e:
            total_pages = None
            log.append(f"[{mock_name}] WARNING: could not open {pdf_filename} ({e})")

        try:
            def _ocr_progress(done, total):
                if done == 1 or done % 10 == 0 or done == total:
                    print(f"[scaffold] [{mock_name}] OCR-scanning page {done}/{total}...")
            structure = pdf_structure.detect_structure(pdf_path, ocr_progress=_ocr_progress)
        except Exception as e:
            structure = {"tests": {}, "warnings": [f"PDF structure scan failed: {e}"], "ocr_pages_used": 0, "ocr_available": False}
        for w in structure["warnings"]:
            log.append(f"[{mock_name}] {w}")
        if structure.get("ocr_pages_used"):
            log.append(
                f"[{mock_name}] {structure['ocr_pages_used']} page(s) had no text layer -- "
                f"used OCR to read them instead (slower, and less reliable than a real text layer, "
                f"so double-check the results more carefully)."
            )
        detected_tests = structure["tests"]  # keyed "Test 1", "Test 2", ... from PDF headings

        if not os.path.isfile(manifest_path):
            manifest = {"mock_name": mock_name, "pdf_file": pdf_filename, "tests": {}}
            for test_name in test_dirs:
                det = detected_tests.get(test_name, {})
                reading = _build_reading_block(det.get("reading_passages"))
                writing = _build_writing_block(det.get("writing"))
                cfg = {"listening": _build_listening_block(test_name, audio_root, det.get("listening_parts"))}
                if reading:
                    cfg["reading"] = reading
                if writing:
                    cfg["writing"] = writing
                manifest["tests"][test_name] = cfg
            with open(manifest_path, "w") as f:
                json.dump(manifest, f, indent=2)
            filled = [t for t in test_dirs if "reading" in manifest["tests"][t] or "writing" in manifest["tests"][t]]
            log.append(
                f"[{mock_name}] created manifest.json with {len(test_dirs)} test(s) "
                f"({', '.join(test_dirs) or 'none found'})."
                + (f" Auto-detected reading/writing for: {', '.join(filled)}." if filled else
                   " Could not confidently detect reading/writing structure -- add those blocks by hand.")
                + (f" {pdf_filename} has {total_pages} pages." if total_pages else "")
                + " Double-check the generated page numbers against your actual PDF before relying on it."
            )
        else:
            with open(manifest_path) as f:
                manifest = json.load(f)
            changed = False

            for test_name in test_dirs:
                det = detected_tests.get(test_name, {})
                if test_name not in manifest.get("tests", {}):
                    reading = _build_reading_block(det.get("reading_passages"))
                    writing = _build_writing_block(det.get("writing"))
                    cfg = {"listening": _build_listening_block(test_name, audio_root, det.get("listening_parts"))}
                    if reading:
                        cfg["reading"] = reading
                    if writing:
                        cfg["writing"] = writing
                    manifest.setdefault("tests", {})[test_name] = cfg
                    changed = True
                    log.append(f"[{mock_name}] added newly-found '{test_name}' to manifest.json.")
                    continue

                cfg = manifest["tests"][test_name]

                if "reading" not in cfg:
                    reading = _build_reading_block(det.get("reading_passages"))
                    if reading:
                        cfg["reading"] = reading
                        changed = True
                        log.append(f"[{mock_name}/{test_name}] backfilled 'reading' from PDF scan.")

                if "writing" not in cfg:
                    writing = _build_writing_block(det.get("writing"))
                    if writing:
                        cfg["writing"] = writing
                        changed = True
                        log.append(f"[{mock_name}/{test_name}] backfilled 'writing' from PDF scan.")

                if "listening" in cfg and det.get("listening_parts"):
                    parts = cfg["listening"].get("parts", [])
                    detected_parts = det["listening_parts"]
                    if len(parts) == len(detected_parts):
                        any_filled = False
                        for part, dparts in zip(parts, detected_parts):
                            if not part.get("pages") and dparts.get("pages"):
                                part["pages"] = dparts["pages"]
                                any_filled = True
                        if any_filled:
                            changed = True
                            log.append(f"[{mock_name}/{test_name}] backfilled listening 'pages' from PDF scan.")
                    elif any(not p.get("pages") for p in parts):
                        log.append(
                            f"[{mock_name}/{test_name}] found {len(detected_parts)} listening section(s) "
                            f"in the PDF but {len(parts)} audio file(s) -- counts don't match, so pages "
                            f"weren't auto-filled. Add them by hand."
                        )

            if changed:
                with open(manifest_path, "w") as f:
                    json.dump(manifest, f, indent=2)

        # --- answers/<Test N>/{reading,listening}.json ---
        for test_name, cfg in manifest.get("tests", {}).items():
            answers_dir = os.path.join(mock_dir, "answers", test_name)
            for section in ("reading", "listening"):
                if section not in cfg:
                    continue
                answers_path = os.path.join(answers_dir, f"{section}.json")
                if os.path.isfile(answers_path):
                    continue
                if section == "reading":
                    ranges = [p["questions"] for p in cfg["reading"].get("passages", [])]
                else:
                    ranges = [p["questions"] for p in cfg["listening"].get("parts", [])]
                if not ranges:
                    continue
                os.makedirs(answers_dir, exist_ok=True)
                with open(answers_path, "w") as f:
                    json.dump(_placeholder_answers(ranges), f, indent=2)
                log.append(
                    f"[{mock_name}/{test_name}] created answers/{test_name}/{section}.json "
                    f"with {sum(e - s + 1 for s, e in ranges)} blank placeholder answers -- "
                    f"fill in the real answer key."
                )

    if verbose:
        for line in log:
            print("[scaffold]", line)
    return log
