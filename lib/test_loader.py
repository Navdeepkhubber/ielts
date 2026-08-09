"""
Scans the primary tests folder for "mock" packages and loads their
manifest + answer keys.

Expected folder convention (one folder per mock/book):

tests/                              <- primary root
  Mock 19/
    main.pdf                         <- the WHOLE book: all reading passages,
                                         question sheets, listening question
                                         sheets, and writing prompts for all
                                         4 tests, exactly as printed.
    audio/
      Test 1/
        part1.mp3
        part2.mp3
        part3.mp3
        part4.mp3
      Test 2/
        ...
      Test 3/
      Test 4/
    answers/
      Test 1/
        reading.json                 <- {"1": "TRUE", ...}
        listening.json
      Test 2/
        ...
    manifest.json                    <- required, maps Test N -> page/audio refs

manifest.json shape:
{
  "mock_name": "Cambridge Mock 19",
  "pdf_file": "main.pdf",
  "tests": {
    "Test 1": {
      "variant": "academic",   // optional: "academic" (default) or "general".
                               // GT uses a stricter Reading band table.
      "reading": {
        "duration_minutes": 60,
        "passages": [
          {"pages": [5, 6, 7], "questions": [1, 13]},
          {"pages": [8, 9, 10], "questions": [14, 26]},
          {"pages": [11, 12, 13, 14], "questions": [27, 40]}
        ]
      },
      "listening": {
        "audio_folder": "Test 1",
        "parts": [
          {"file": "part1.mp3", "questions": [1, 10], "pages": [15, 16]},
          {"file": "part2.mp3", "questions": [11, 20], "pages": [17, 18]},
          {"file": "part3.mp3", "questions": [21, 30], "pages": [19, 20]},
          {"file": "part4.mp3", "questions": [31, 40], "pages": [21, 22]}
        ]
      },
      "writing": {
        "task1": {"page": 20, "duration_minutes": 20},
        "task2": {"page": 21, "duration_minutes": 40}
      }
    },
    "Test 2": { ... },
    "Test 3": { ... },
    "Test 4": { ... }
  }
}

Only page numbers, file names, and answer keys are read here. No
passage/question text is ever extracted -- main.pdf pages are rendered as
images by lib/pdf_render.py and shown as-is, so the platform works with any
book that follows this same folder convention.

`pages` on a listening part works exactly like `pages` on a reading
passage: 1-indexed page numbers within main.pdf covering that part's
printed question sheet (diagrams, multiple-choice options, map labels,
etc.). It's optional/omittable while you're still filling in a manifest,
but without it a test-taker only hears the audio and never sees the
question sheet -- which for listening is essential, not cosmetic.
"""
import json
import os

from lib import blob_storage

TESTS_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests")


def cached_file(mock_id, relative_path):
    """
    Returns a local filesystem path to tests/<mock_id>/<relative_path>,
    or None if that file doesn't exist at the source.

    When remote blob storage isn't configured (the default, and always
    true for local dev), this is just a thin existence check against the
    local tests/ folder -- nothing changes from before. When configured
    (see lib/blob_storage.py / SETUP.md), it fetches from the bucket on
    first access and caches the download locally, so repeat requests
    for the same page/audio file don't re-download it.
    """
    if not blob_storage.is_configured():
        local_path = os.path.join(TESTS_ROOT, mock_id, relative_path)
        return local_path if os.path.isfile(local_path) else None
    return blob_storage.fetch_cached(os.path.join(mock_id, relative_path))


def list_mocks():
    """Return a summary list of every valid mock package found."""
    out = []
    if blob_storage.is_configured():
        mock_ids = blob_storage.list_mock_ids()
    else:
        if not os.path.isdir(TESTS_ROOT):
            return out
        mock_ids = sorted(
            name for name in os.listdir(TESTS_ROOT)
            if os.path.isfile(os.path.join(TESTS_ROOT, name, "manifest.json"))
        )

    for name in mock_ids:
        manifest_path = cached_file(name, "manifest.json")
        if manifest_path is None:
            continue
        with open(manifest_path) as f:
            manifest = json.load(f)
        tests = {}
        for test_name, cfg in manifest.get("tests", {}).items():
            tests[test_name] = {
                "has_reading": "reading" in cfg,
                "has_listening": "listening" in cfg,
                "has_writing": "writing" in cfg,
            }
        out.append({
            "id": name,
            "mock_name": manifest.get("mock_name", name),
            "tests": tests,
        })
    return out


def load_manifest(mock_id):
    path = cached_file(mock_id, "manifest.json")
    if path is None:
        raise FileNotFoundError(f"No manifest.json for mock '{mock_id}'")
    with open(path) as f:
        return json.load(f)


def load_test_config(mock_id, test_name):
    manifest = load_manifest(mock_id)
    tests = manifest.get("tests", {})
    if test_name not in tests:
        raise FileNotFoundError(f"'{test_name}' not found in mock '{mock_id}'")
    return manifest, tests[test_name]


def mock_folder(mock_id):
    """
    Local authoring path (tests/<mock_id>) -- used only by local tooling
    (scaffold.py, fill_answer_keys_local.py, diagnose_mock.py, report.py)
    that works directly against the source folder BEFORE it's uploaded
    to remote storage. Request-serving code never calls this directly
    -- see cached_file() instead, which is the one that's actually aware
    of remote storage.
    """
    return os.path.join(TESTS_ROOT, mock_id)


def main_pdf_path(mock_id, manifest=None):
    manifest = manifest or load_manifest(mock_id)
    pdf_file = manifest.get("pdf_file", "main.pdf")
    path = cached_file(mock_id, pdf_file)
    if path is None:
        raise FileNotFoundError(f"{pdf_file} missing for mock '{mock_id}'")
    return path


def audio_path(mock_id, test_name, filename, test_cfg=None):
    if test_cfg is None:
        _, test_cfg = load_test_config(mock_id, test_name)
    audio_folder = test_cfg["listening"]["audio_folder"]
    rel = os.path.join("audio", audio_folder, filename)
    path = cached_file(mock_id, rel)
    if path is None:
        raise FileNotFoundError(f"{rel} missing for mock '{mock_id}'")
    return path


def load_answers(mock_id, test_name, section):
    """section is 'reading' or 'listening'. Returns {} if no file present."""
    path = cached_file(mock_id, os.path.join("answers", test_name, f"{section}.json"))
    if path is None:
        return {}
    with open(path) as f:
        return json.load(f)


def answers_exist(mock_id, test_name, section):
    """True only if answers/<test_name>/<section>.json genuinely exists
    at the source -- distinct from load_answers() returning {}, which
    also happens for a file that exists but is legitimately blank."""
    return cached_file(mock_id, os.path.join("answers", test_name, f"{section}.json")) is not None