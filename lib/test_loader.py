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

TESTS_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests")


def list_mocks():
    """Return a summary list of every valid mock package found."""
    out = []
    if not os.path.isdir(TESTS_ROOT):
        return out
    for name in sorted(os.listdir(TESTS_ROOT)):
        folder = os.path.join(TESTS_ROOT, name)
        manifest_path = os.path.join(folder, "manifest.json")
        if os.path.isdir(folder) and os.path.isfile(manifest_path):
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
    folder = os.path.join(TESTS_ROOT, mock_id)
    manifest_path = os.path.join(folder, "manifest.json")
    if not os.path.isfile(manifest_path):
        raise FileNotFoundError(f"No manifest.json for mock '{mock_id}'")
    with open(manifest_path) as f:
        return json.load(f)


def load_test_config(mock_id, test_name):
    manifest = load_manifest(mock_id)
    tests = manifest.get("tests", {})
    if test_name not in tests:
        raise FileNotFoundError(f"'{test_name}' not found in mock '{mock_id}'")
    return manifest, tests[test_name]


def mock_folder(mock_id):
    return os.path.join(TESTS_ROOT, mock_id)


def main_pdf_path(mock_id, manifest=None):
    manifest = manifest or load_manifest(mock_id)
    return os.path.join(mock_folder(mock_id), manifest.get("pdf_file", "main.pdf"))


def audio_path(mock_id, test_name, filename, test_cfg=None):
    if test_cfg is None:
        _, test_cfg = load_test_config(mock_id, test_name)
    audio_folder = test_cfg["listening"]["audio_folder"]
    return os.path.join(mock_folder(mock_id), "audio", audio_folder, filename)


def load_answers(mock_id, test_name, section):
    """section is 'reading' or 'listening'. Returns {} if no file present."""
    path = os.path.join(mock_folder(mock_id), "answers", test_name, f"{section}.json")
    if not os.path.isfile(path):
        return {}
    with open(path) as f:
        return json.load(f)
