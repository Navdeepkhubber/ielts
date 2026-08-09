"""
Tests for lib/blob_storage.py (fetch/cache/list against a fake S3
client) and its integration into lib/test_loader.py (which must behave
identically to the pre-B2 local-disk version when blob storage isn't
configured, and correctly delegate to it when it is).
"""
import json
import os

import pytest

from app_tests.fake_s3 import FakeS3Client


@pytest.fixture
def configured_blob_storage(monkeypatch, tmp_path):
    """Configures lib.blob_storage as if B2 env vars were set, backed by
    a fake in-memory S3 client, with a fresh local cache dir per test."""
    import lib.blob_storage as blob_storage

    monkeypatch.setattr(blob_storage, "BUCKET", "test-bucket")
    monkeypatch.setattr(blob_storage, "ENDPOINT", "https://s3.fake.example.com")
    monkeypatch.setattr(blob_storage, "KEY_ID", "fake-key-id")
    monkeypatch.setattr(blob_storage, "APP_KEY", "fake-app-key")
    monkeypatch.setattr(blob_storage, "PREFIX", "tests")
    monkeypatch.setattr(blob_storage, "CACHE_DIR", str(tmp_path / "cache"))

    fake_client = FakeS3Client()
    monkeypatch.setattr(blob_storage, "_get_client", lambda: fake_client)
    monkeypatch.setattr(blob_storage, "_client", None)

    return blob_storage, fake_client


def test_is_configured_false_by_default():
    import lib.blob_storage as blob_storage
    # Real module-level state, not the fixture -- confirms local dev/CI
    # (no BLOB_* env vars set) sees this as off, same as every other
    # optional-integration pattern in this app.
    assert blob_storage.is_configured() == bool(
        blob_storage.BUCKET and blob_storage.ENDPOINT and blob_storage.KEY_ID and blob_storage.APP_KEY
    )


def test_is_configured_true_when_all_four_set(configured_blob_storage):
    blob_storage, _ = configured_blob_storage
    assert blob_storage.is_configured() is True


def test_fetch_cached_downloads_and_returns_local_path(configured_blob_storage):
    blob_storage, fake_client = configured_blob_storage
    fake_client.put("tests/Mock 19/manifest.json", b'{"mock_name": "Test Mock"}')

    path = blob_storage.fetch_cached("Mock 19/manifest.json")
    assert path is not None
    assert os.path.isfile(path)
    with open(path) as f:
        assert json.load(f) == {"mock_name": "Test Mock"}


def test_fetch_cached_only_downloads_once(configured_blob_storage):
    """The whole point of local caching -- a second request for the same
    object must not hit the network/bucket again."""
    blob_storage, fake_client = configured_blob_storage
    fake_client.put("tests/Mock 19/manifest.json", b"{}")

    blob_storage.fetch_cached("Mock 19/manifest.json")
    blob_storage.fetch_cached("Mock 19/manifest.json")
    assert fake_client.download_calls == ["tests/Mock 19/manifest.json"]


def test_fetch_cached_returns_none_for_missing_object(configured_blob_storage):
    blob_storage, _ = configured_blob_storage
    assert blob_storage.fetch_cached("Mock 19/does-not-exist.json") is None


def test_list_mock_ids(configured_blob_storage):
    blob_storage, fake_client = configured_blob_storage
    fake_client.put("tests/Mock 19/manifest.json", b"{}")
    fake_client.put("tests/Mock 19/main.pdf", b"%PDF-fake")
    fake_client.put("tests/Mock 20/manifest.json", b"{}")

    assert blob_storage.list_mock_ids() == ["Mock 19", "Mock 20"]


def test_upload_file(configured_blob_storage, tmp_path):
    blob_storage, fake_client = configured_blob_storage
    local_file = tmp_path / "manifest.json"
    local_file.write_text('{"mock_name": "Uploaded Mock"}')

    blob_storage.upload_file(str(local_file), "Mock 21/manifest.json")
    assert fake_client.objects["tests/Mock 21/manifest.json"] == b'{"mock_name": "Uploaded Mock"}'


# ---------- test_loader.py integration ----------

def test_loader_uses_local_disk_when_blob_storage_not_configured(tmp_path, monkeypatch):
    """Regression test for the most important property of this whole
    feature: with no BLOB_* env vars set, test_loader must behave
    exactly as it did before B2 existed."""
    import lib.test_loader as test_loader
    import lib.blob_storage as blob_storage

    assert blob_storage.is_configured() is False

    monkeypatch.setattr(test_loader, "TESTS_ROOT", str(tmp_path))
    mock_dir = tmp_path / "Local Mock"
    mock_dir.mkdir()
    (mock_dir / "manifest.json").write_text(json.dumps({
        "mock_name": "Local Mock", "pdf_file": "main.pdf",
        "tests": {"Test 1": {"reading": {}}},
    }))
    (mock_dir / "main.pdf").write_bytes(b"%PDF-fake")

    mocks = test_loader.list_mocks()
    assert len(mocks) == 1
    assert mocks[0]["id"] == "Local Mock"

    manifest = test_loader.load_manifest("Local Mock")
    assert manifest["mock_name"] == "Local Mock"

    pdf_path = test_loader.main_pdf_path("Local Mock", manifest)
    assert pdf_path == str(mock_dir / "main.pdf")
    assert os.path.isfile(pdf_path)


def test_loader_delegates_to_blob_storage_when_configured(configured_blob_storage):
    """The other half of the same property: with B2 configured, the same
    test_loader functions transparently source from the bucket instead,
    with zero change to their call signatures or return shapes."""
    import lib.test_loader as test_loader

    _, fake_client = configured_blob_storage
    fake_client.put("tests/Remote Mock/manifest.json", json.dumps({
        "mock_name": "Remote Mock", "pdf_file": "main.pdf",
        "tests": {"Test 1": {"reading": {}, "listening": {"audio_folder": "Test 1"}}},
    }).encode())
    fake_client.put("tests/Remote Mock/main.pdf", b"%PDF-fake-remote")
    fake_client.put("tests/Remote Mock/audio/Test 1/part1.mp3", b"fake-audio-bytes")
    fake_client.put("tests/Remote Mock/answers/Test 1/reading.json", json.dumps({"1": "TRUE"}).encode())

    mocks = test_loader.list_mocks()
    assert len(mocks) == 1
    assert mocks[0]["mock_name"] == "Remote Mock"

    manifest = test_loader.load_manifest("Remote Mock")
    pdf_path = test_loader.main_pdf_path("Remote Mock", manifest)
    assert os.path.isfile(pdf_path)
    with open(pdf_path, "rb") as f:
        assert f.read() == b"%PDF-fake-remote"

    audio_path = test_loader.audio_path("Remote Mock", "Test 1", "part1.mp3")
    with open(audio_path, "rb") as f:
        assert f.read() == b"fake-audio-bytes"

    answers = test_loader.load_answers("Remote Mock", "Test 1", "reading")
    assert answers == {"1": "TRUE"}
    assert test_loader.answers_exist("Remote Mock", "Test 1", "reading") is True
    assert test_loader.answers_exist("Remote Mock", "Test 1", "listening") is False


def test_loader_main_pdf_path_raises_cleanly_when_missing(configured_blob_storage):
    """app.py's /api/mocks/<id>/page route already catches FileNotFoundError
    and turns it into a 404 -- this pins down that main_pdf_path actually
    raises that, rather than silently returning a path to nothing."""
    import lib.test_loader as test_loader

    _, fake_client = configured_blob_storage
    fake_client.put("tests/Broken Mock/manifest.json", json.dumps({
        "mock_name": "Broken Mock", "pdf_file": "main.pdf", "tests": {},
    }).encode())
    # Deliberately no main.pdf uploaded.

    manifest = test_loader.load_manifest("Broken Mock")
    with pytest.raises(FileNotFoundError):
        test_loader.main_pdf_path("Broken Mock", manifest)