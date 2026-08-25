#!/usr/bin/env python3
"""Upload the local PDF/audio mock files to configured S3-compatible storage.

Usage:
    python3 scripts/sync_tests_to_blob_storage.py
    python3 scripts/sync_tests_to_blob_storage.py --dry-run
    python3 scripts/sync_tests_to_blob_storage.py --mock "Cambridge 21"
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from lib import blob_storage  # noqa: E402
from lib.test_loader import TESTS_ROOT  # noqa: E402


def _remote_size(client, relative_path):
    key = blob_storage._object_key(relative_path)
    try:
        response = client.head_object(Bucket=blob_storage.BUCKET, Key=key)
        return response["ContentLength"]
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--mock")
    args = parser.parse_args()

    if not blob_storage.is_configured():
        print("BLOB_BUCKET_NAME, BLOB_ENDPOINT_URL, BLOB_KEY_ID, and "
              "BLOB_APPLICATION_KEY must all be set.", file=sys.stderr)
        return 1
    if not os.path.isdir(TESTS_ROOT):
        print(f"No local tests folder found at {TESTS_ROOT}", file=sys.stderr)
        return 1

    client = blob_storage._get_client()
    mock_names = [args.mock] if args.mock else sorted(
        name for name in os.listdir(TESTS_ROOT)
        if os.path.isdir(os.path.join(TESTS_ROOT, name))
    )
    uploaded = skipped = failed = 0

    for mock_name in mock_names:
        mock_dir = os.path.join(TESTS_ROOT, mock_name)
        for root, _dirs, files in os.walk(mock_dir):
            for filename in files:
                local_path = os.path.join(root, filename)
                relative_path = os.path.relpath(local_path, TESTS_ROOT)
                local_size = os.path.getsize(local_path)
                if _remote_size(client, relative_path) == local_size:
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
                except Exception as error:
                    print(f"  FAILED: {error}", file=sys.stderr)
                    failed += 1

    verb = "would be uploaded" if args.dry_run else "uploaded"
    print(f"\n{uploaded} file(s) {verb}, {skipped} already up to date, "
          f"{failed} failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())