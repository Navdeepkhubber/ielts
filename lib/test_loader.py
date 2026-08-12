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

Only page numbers, file names, and answer keys are read here. No
passage/question text is ever extracted -- main.pdf pages are rendered as
images by lib/pdf_render.py and shown as-is, so the platform works with any
book that follows this same folder convention.
"""
import json
import os

from lib import blob_storage

TESTS_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests")


def _local_file(mock_id, relative_path):
    local_path = os.path.join(TESTS_ROOT, mock_id, relative_path)
    return local_path if os.path.isfile(local_path) else None


def _local_mock_ids():
    if not os.path.isdir(TESTS_ROOT):
        return []
    return sorted(
        name for name in os.listdir(TESTS_ROOT)
        if os.path.isfile(os.path.join(TESTS_ROOT, name, "manifest.json"))
    )


def _local_dev():
    return os.environ.get("FLASK_DEBUG", "1").strip().lower() in {"1", "true", "yes", "on"}


def cached_file(mock_id, relative_path):
    """
    Return a local filesystem path to a test file.

    Local development prefers the local authoring copy when it exists. This
    is important when B2/blob storage is configured in a shared .env: localhost
    should not silently read a stale/missing remote copy while the developer
    is editing tests/.

    If no local copy exists, configured blob storage is used. In deployed
    environments remote storage remains authoritative.
    """
    local_path = _local_file(mock_id, relative_path)

    if _local_dev() and local_path is not None:
        return local_path

    if not blob_storage.is_configured():
        return local_path

    try:
        return blob_storage.fetch_cached(os.path.join(mock_id, relative_path))
    except Exception:
        if _local_dev() and local_path is not None:
            return local_path
        raise


def list_mocks():
    """Return a summary list of every valid mock package found."""
    out = []

    # Localhost should enumerate the actual local authoring tree first. This
    # avoids an empty B2 listing hiding valid mocks under tests/ when B2 is
    # configured but has a different prefix or contains an older library.
    local_ids = _local_mock_ids() if _local_dev() else []
    if local_ids:
        mock_ids = local_ids
    elif blob_storage.is_configured():
        try:
            mock_ids = blob_storage.list_mock_ids()
        except Exception:
            if not _local_dev():
                raise
            mock_ids = local_ids
    else:
        mock_ids = local_ids

    for name in mock_ids:
        manifest_path = cached_file(name, "manifest.json")
        if manifest_path is None:
            continue
        with open(manifest_path, encoding="utf-8") as f:
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
    with open(path, encoding="utf-8") as f:
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
    to remote storage. Request-serving code never calls this directly.
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
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def answers_exist(mock_id, test_name, section):
    """True only if answers/<test_name>/<section>.json genuinely exists
    at the source -- distinct from load_answers() returning {}."""
    return cached_file(mock_id, os.path.join("answers", test_name, f"{section}.json")) is not None
