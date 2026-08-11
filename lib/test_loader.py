"""
Test-package loader.

A test package lives under tests/<mock_id> during local authoring and may
also be mirrored to the optional S3-compatible blob store for deployed
instances. Request-serving code should use cached_file() so it can work
with either source transparently.
"""
import json
import os

from lib import blob_storage

TESTS_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests")


def _local_file(mock_id, relative_path):
    local_path = os.path.join(TESTS_ROOT, mock_id, relative_path)
    return local_path if os.path.isfile(local_path) else None


def cached_file(mock_id, relative_path):
    """
    Return a local filesystem path to a test file.

    In normal local development, files are read directly from tests/. If
    blob storage is configured, remote storage is preferred. When running
    locally with FLASK_DEBUG enabled, a remote read failure (for example a
    B2 403 caused by a scoped key without read permission) falls back to
    the local authoring copy when that copy exists. This keeps local review
    and authoring usable even when the optional remote storage credentials
    are stale or intentionally unavailable.

    In non-debug/deployed environments, remote errors are deliberately
    re-raised rather than silently serving a potentially stale local copy.
    """
    local_path = _local_file(mock_id, relative_path)

    if not blob_storage.is_configured():
        return local_path

    try:
        return blob_storage.fetch_cached(os.path.join(mock_id, relative_path))
    except Exception:
        if os.environ.get("FLASK_DEBUG", "1") == "1" and local_path is not None:
            return local_path
        raise


def list_mocks():
    """Return a summary list of every valid mock package found."""
    out = []
    if blob_storage.is_configured():
        try:
            mock_ids = blob_storage.list_mock_ids()
        except Exception:
            if os.environ.get("FLASK_DEBUG", "1") != "1" or not os.path.isdir(TESTS_ROOT):
                raise
            mock_ids = sorted(
                name for name in os.listdir(TESTS_ROOT)
                if os.path.isfile(os.path.join(TESTS_ROOT, name, "manifest.json"))
            )
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
    """Local authoring path (tests/<mock_id>) used by local tooling."""
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
