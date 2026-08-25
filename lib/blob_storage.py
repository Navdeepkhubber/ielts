"""
Optional S3-compatible remote storage for test content (PDFs, audio),
backed by Backblaze B2 -- but written against the generic S3 API, so
switching to Cloudflare R2, Wasabi, or DigitalOcean Spaces later is a
config change (different endpoint/credentials), not a code change.

Entirely inert -- and lib/test_loader.py falls back to reading straight
from the local tests/ folder exactly as before -- unless all four
BLOB_* env vars below are set. Same pattern as Firestore/subdomains
elsewhere in this app: local dev never needs any of this configured.

Files are fetched once and cached on local disk under BLOB_CACHE_DIR --
important on a container instance's ephemeral disk, since a fresh
instance starts with an empty cache and repopulates it lazily as
content is actually requested, rather than needing everything
pre-downloaded up front. This is also why the image itself can now stay
small regardless of how large your test library grows: the source
files never need to be baked into it.

Required env vars (see SETUP.md for the one-time bucket + scoped-key
setup this needs -- note the B2 Master Application Key specifically
does NOT work here; B2's S3-compatible API requires a manually-created,
bucket-scoped application key):
  BLOB_BUCKET_NAME     -- the bucket's name (not its Bucket ID)
  BLOB_ENDPOINT_URL    -- e.g. https://s3.ca-east-006.backblazeb2.com
  BLOB_KEY_ID          -- the scoped application key's keyID
  BLOB_APPLICATION_KEY -- the scoped application key's secret
"""
import os
import threading

_client = None
_client_lock = threading.Lock()

BUCKET = os.environ.get("BLOB_BUCKET_NAME")
ENDPOINT = os.environ.get("BLOB_ENDPOINT_URL")
KEY_ID = os.environ.get("BLOB_KEY_ID")
APP_KEY = os.environ.get("BLOB_APPLICATION_KEY")
# Object keys are "<prefix>/<mock_id>/<relative_path>" -- lets the same
# bucket hold other things under a different prefix later if needed.
PREFIX = os.environ.get("BLOB_KEY_PREFIX", "tests")
CACHE_DIR = os.environ.get("BLOB_CACHE_DIR", "/tmp/ielts-blob-cache")


def is_configured():
    return bool(BUCKET and ENDPOINT and KEY_ID and APP_KEY)


def _get_client():
    global _client
    if _client is not None:
        return _client
    with _client_lock:
        if _client is None:
            import boto3
            _client = boto3.client(
                "s3",
                endpoint_url=ENDPOINT,
                aws_access_key_id=KEY_ID,
                aws_secret_access_key=APP_KEY,
            )
    return _client


def _object_key(relative_path):
    return f"{PREFIX}/{relative_path}"


def _cache_path(relative_path):
    return os.path.join(CACHE_DIR, relative_path)


def fetch_cached(relative_path):
    """
    Ensures a local cached copy of tests/<relative_path> exists,
    downloading it from the bucket on first request. Returns the local
    path, or None if the object genuinely doesn't exist in the bucket
    (a real 404 -- distinguished from a transient error, which raises
    instead so it isn't silently treated as "this file was never
    uploaded").
    """
    local_path = _cache_path(relative_path)
    if os.path.isfile(local_path):
        return local_path

    client = _get_client()
    key = _object_key(relative_path)
    os.makedirs(os.path.dirname(local_path), exist_ok=True)

    # Download to a temp path first, then atomically rename into place --
    # avoids a concurrent request reading a half-written file if two
    # requests race to fetch the same not-yet-cached object.
    tmp_path = f"{local_path}.tmp-{os.getpid()}"
    try:
        client.download_file(BUCKET, key, tmp_path)
    except Exception as e:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        error_code = getattr(e, "response", {}).get("Error", {}).get("Code", "")
        if error_code in ("404", "NoSuchKey"):
            return None
        raise
    os.replace(tmp_path, local_path)
    return local_path


def list_mock_ids():
    """Top-level 'folder' names under the prefix -- one per mock, each
    containing its own mock configuration, PDFs, and audio files."""
    client = _get_client()
    paginator = client.get_paginator("list_objects_v2")
    mock_ids = set()
    for page in paginator.paginate(Bucket=BUCKET, Prefix=f"{PREFIX}/", Delimiter="/"):
        for common_prefix in page.get("CommonPrefixes", []):
            # e.g. "tests/Mock 19/" -> "Mock 19"
            name = common_prefix["Prefix"][len(PREFIX) + 1:].rstrip("/")
            if name:
                mock_ids.add(name)
    return sorted(mock_ids)


def upload_file(local_path, relative_path):
    """Used by scripts/sync_tests_to_blob_storage.py -- never called at
    request-serving time."""
    client = _get_client()
    client.upload_file(local_path, BUCKET, _object_key(relative_path))