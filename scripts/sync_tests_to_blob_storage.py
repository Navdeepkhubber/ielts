#!/usr/bin/env python3
"""
Uploads (syncs) the local tests/ folder to configured blob storage
(Backblaze B2 or any other S3-compatible provider). Run this locally
whenever you add or change mock content -- it's never run by the
deployed app itself, which only ever reads from the bucket.

Usage:
    python3 scripts/sync_tests_to_blob_storage.py
    python3 scripts/sync_tests_to_blob_storage.py --dry-run
    python3 scripts/sync_tests_to_blob_storage.py --mock "Mock 19"

Requires the same BLOB_* env vars as the deployed app (see SETUP.md):
    BLOB_BUCKET_NAME, BLOB_ENDPOINT_URL, BLOB_KEY_ID, BLOB_APPLICATION_KEY

Skips files that already exist in the bucket with the same size, so
re-running this after adding just one new mock doesn't re-upload
everything else -- only genuinely new/changed files transfer.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Local dev convenience: this script is a standalone entry point (never
# imports app.py), so app.py's own .env loading never runs for it --
# without this, BLOB_* variables set only in .env (not the real shell
# environment) would silently not be picked up here even though
# `python3 app.py` picks them up fine.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from lib import blob_storage  # noqa: E402
from lib.test_loader import TESTS_ROOT  # noqa: E402


def _remote_size(client, relative_path):
    """Returns the object's size in bytes if it exists in the bucket,
    or None if it doesn't -- used to skip re-uploading unchanged files."""
    key = blob_storage._object_key(relative_path)
    try:
        resp = client.head_object(Bucket=blob_storage.BUCKET, Key=key)
        return resp["ContentLength"]
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="List what would upload without uploading")
    parser.add_argument("--mock", help="Only sync this one mock folder (by its exact folder name)")
    args = parser.parse_args()

    if not blob_storage.is_configured():
        print(
            "BLOB_BUCKET_NAME / BLOB_ENDPOINT_URL / BLOB_KEY_ID / BLOB_APPLICATION_KEY\n"
            "aren't all set -- nothing to sync to. See SETUP.md.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not os.path.isdir(TESTS_ROOT):
        print(f"No local tests/ folder found at {TESTS_ROOT}", file=sys.stderr)
        sys.exit(1)

    client = blob_storage._get_client()

    mock_names = [args.mock] if args.mock else sorted(
        name for name in os.listdir(TESTS_ROOT)
        if os.path.isdir(os.path.join(TESTS_ROOT, name))
    )

    uploaded, skipped, failed = 0, 0, 0
    for mock_name in mock_names:
        mock_dir = os.path.join(TESTS_ROOT, mock_name)
        for root, _dirs, files in os.walk(mock_dir):
            for filename in files:
                local_path = os.path.join(root, filename)
                relative_path = os.path.relpath(local_path, TESTS_ROOT)  # "Mock 19/audio/Test 1/part1.mp3"
                local_size = os.path.getsize(local_path)
                remote_size = _remote_size(client, relative_path)

                if remote_size == local_size:
                    skipped += 1
                    continue

                action = "Would upload" if args.dry_run else "Uploading"
                print(f"{action}: {relative_path} ({local_size:,} bytes)")
                if args.dry_run:
                    uploaded += 1
                    continue
                try:
                    blob_storage.upload_file(local_path, relative_path)
                    uploaded += 1
                except Exception as e:
                    print(f"  FAILED: {e}", file=sys.stderr)
                    failed += 1

    verb = "would be uploaded" if args.dry_run else "uploaded"
    print(f"\n{uploaded} file(s) {verb}, {skipped} already up to date, {failed} failed.")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()