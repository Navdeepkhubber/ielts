"""
Diagnoses why mocks uploaded to Backblaze B2 (or any configured S3-
compatible bucket) aren't showing up on the portal. Checks every link
in the chain -- env vars, credentials, bucket contents, and key
structure -- and tells you exactly which one is broken.

    python3 scripts/diagnose_blob_storage.py

Requires the same BLOB_* env vars as the deployed app (see SETUP.md).
Run this with the SAME environment the deployed app actually uses --
if you're testing against production, set the four BLOB_* vars in your
local shell/.env to the same values you set on Render (or wherever you
deployed), not just run it with nothing configured.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from lib import blob_storage  # noqa: E402


def _mask(secret):
    if not secret:
        return "(not set)"
    if len(secret) <= 8:
        return "*" * len(secret)
    return secret[:4] + "*" * (len(secret) - 8) + secret[-4:]


def main():
    print("=== 1. Environment variables ===")
    checks = {
        "BLOB_BUCKET_NAME": blob_storage.BUCKET,
        "BLOB_ENDPOINT_URL": blob_storage.ENDPOINT,
        "BLOB_KEY_ID": blob_storage.KEY_ID,
        "BLOB_APPLICATION_KEY": _mask(blob_storage.APP_KEY),
    }
    for name, value in checks.items():
        status = "OK" if (blob_storage.APP_KEY if name == "BLOB_APPLICATION_KEY" else value) else "MISSING"
        print(f"  {name:22s} = {value!r:40s} [{status}]")
    print(f"  BLOB_KEY_PREFIX        = {blob_storage.PREFIX!r} (objects must live under \"{blob_storage.PREFIX}/...\")")

    if not blob_storage.is_configured():
        print(
            "\nSTOP: not all four BLOB_* vars are set, so is_configured() is False.\n"
            "The app is silently falling back to reading the LOCAL tests/ folder\n"
            "instead of the bucket -- that alone would fully explain nothing\n"
            "showing up. Set all four (see SETUP.md) and re-run this script."
        )
        sys.exit(1)

    print("\n=== 2. Can we authenticate and talk to the bucket at all? ===")
    try:
        client = blob_storage._get_client()
        client.list_objects_v2(Bucket=blob_storage.BUCKET, MaxKeys=1)
        print("  OK -- credentials work and the bucket is reachable.")
    except Exception as e:
        print(f"  FAILED: {e}")
        print(
            "\nSTOP: this is almost always one of --\n"
            "  - Using the B2 MASTER key instead of a scoped Application Key\n"
            "    (B2's docs say the Master key does not work with the S3 API)\n"
            "  - The scoped key wasn't given \"Allow List All Bucket Names\"\n"
            "    (required for the S3 SDK even on a bucket-restricted key)\n"
            "  - BLOB_ENDPOINT_URL doesn't match your bucket's actual region\n"
            "    (copy it exactly from the bucket's page in the B2 Console)"
        )
        sys.exit(1)

    print("\n=== 3. Raw objects actually in the bucket (first 30) ===")
    try:
        resp = client.list_objects_v2(Bucket=blob_storage.BUCKET, MaxKeys=30)
        keys = [obj["Key"] for obj in resp.get("Contents", [])]
    except Exception as e:
        print(f"  FAILED to list objects: {e}")
        sys.exit(1)

    if not keys:
        print(
            "  The bucket is EMPTY (0 objects).\n\n"
            "STOP: nothing was actually uploaded, or it went to a different\n"
            "bucket than BLOB_BUCKET_NAME points at. If you dragged files into\n"
            "the bucket via the Backblaze web console, that's likely the issue --\n"
            "use the app's own sync script instead, which uploads with the\n"
            "correct key structure automatically:\n\n"
            "  python3 scripts/sync_tests_to_blob_storage.py --dry-run\n"
            "  python3 scripts/sync_tests_to_blob_storage.py"
        )
        sys.exit(1)

    for k in keys:
        print(f"  {k}")
    if len(keys) == 30:
        print("  ... (truncated at 30)")

    print(f"\n=== 4. Do any objects live under the expected \"{blob_storage.PREFIX}/\" prefix? ===")
    under_prefix = [k for k in keys if k.startswith(f"{blob_storage.PREFIX}/")]
    if not under_prefix:
        print(
            f"  NONE of the objects above start with \"{blob_storage.PREFIX}/\".\n\n"
            "STOP: this is almost certainly the problem. The app only looks for\n"
            f"objects under the \"{blob_storage.PREFIX}/\" prefix (e.g.\n"
            f"  \"{blob_storage.PREFIX}/Mock 19/manifest.json\"), but your uploaded\n"
            "keys don't have that prefix. This typically happens when a folder is\n"
            "dragged straight into the bucket root via the B2 web console instead\n"
            "of using the sync script, which builds the correct key path\n"
            "automatically:\n\n"
            "  python3 scripts/sync_tests_to_blob_storage.py --dry-run\n"
            "  python3 scripts/sync_tests_to_blob_storage.py"
        )
        sys.exit(1)
    print(f"  Found {len(under_prefix)} object(s) under the prefix -- good.")

    print("\n=== 5. What list_mock_ids() (what the portal actually calls) sees ===")
    mock_ids = blob_storage.list_mock_ids()
    if not mock_ids:
        print(
            "  Empty. Objects exist under the prefix, but none of them look like\n"
            f"  \"{blob_storage.PREFIX}/<Mock Name>/...\" one level deep -- check the\n"
            "  key structure above against SETUP.md's expected layout."
        )
        sys.exit(1)
    print(f"  {mock_ids}")

    print("\n=== 6. Does each mock have a fetchable manifest.json? ===")
    from lib import test_loader
    all_ok = True
    for mock_id in mock_ids:
        path = test_loader.cached_file(mock_id, "manifest.json")
        status = "OK" if path else "MISSING manifest.json"
        if not path:
            all_ok = False
        print(f"  {mock_id:30s} [{status}]")

    if all_ok:
        print("\nEverything checks out -- these mocks should be visible on /app now.")
        print("If they still aren't, restart/redeploy the app (it may have an")
        print("older empty listing cached from before the upload finished).")
    else:
        print(
            "\nSTOP: at least one mock is missing manifest.json in the bucket.\n"
            "list_mocks() silently skips any mock without one -- re-run the\n"
            "sync script to make sure it uploaded."
        )


if __name__ == "__main__":
    main()