"""Sync listening parts for an existing mock after audio files are added.

Unlike scaffold_mocks.py this intentionally touches ONLY the listening block
for the selected mock. It does not rebuild reading/writing or regenerate all
mock manifests, making it safe to use when audio is added later.

Usage:
    python3 scripts/sync_listening_manifest.py --mock "Cambridge 9"
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_ROOT = os.path.join(ROOT, "tests")
sys.path.insert(0, ROOT)

from lib import pdf_structure  # noqa: E402
from lib.scaffold import _build_listening_block, _discover_test_dirs  # noqa: E402


def _test_number(name):
    m = re.search(r"test\s*(\d+)", name, re.IGNORECASE)
    return int(m.group(1)) if m else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", required=True)
    args = parser.parse_args()

    mock_dir = os.path.join(TESTS_ROOT, args.mock)
    manifest_path = os.path.join(mock_dir, "manifest.json")
    audio_root = os.path.join(mock_dir, "audio")

    if not os.path.isfile(manifest_path):
        raise SystemExit(f"Manifest not found: {manifest_path}")
    if not os.path.isdir(audio_root):
        raise SystemExit(f"Audio directory not found: {audio_root}")

    with open(manifest_path) as f:
        manifest = json.load(f)

    pdf_file = manifest.get("pdf_file", "main.pdf")
    pdf_path = os.path.join(mock_dir, pdf_file)
    if not os.path.isfile(pdf_path):
        raise SystemExit(f"PDF not found: {pdf_path}")

    test_dirs = _discover_test_dirs(audio_root)
    if not test_dirs:
        raise SystemExit(f"No audio/Test N folders found under {audio_root}")

    print(f"[{args.mock}] syncing listening manifest for {len(test_dirs)} audio tests")

    def progress(done, total):
        if done == 1 or done % 10 == 0 or done == total:
            print(f"  OCR structure scan: {done}/{total} pages")

    structure = pdf_structure.detect_structure(pdf_path, ocr_progress=progress)
    detected_tests = structure.get("tests", {})

    changed = False
    for test_name in test_dirs:
        cfg = manifest.setdefault("tests", {}).setdefault(test_name, {})
        detected = detected_tests.get(test_name, {})
        detected_parts = detected.get("listening_parts", [])
        old = cfg.get("listening")
        new = _build_listening_block(test_name, audio_root, detected_parts=detected_parts)

        # Only replace the listening block. Reading/writing and any other
        # test-specific fields remain untouched.
        if old != new:
            cfg["listening"] = new
            changed = True
            print(f"  {test_name}: listening parts={len(new['parts'])}")
            for part in new["parts"]:
                print(f"    Part {part.get('part_number', '?')}: questions={part['questions']}, pages={part['pages']}")
        else:
            print(f"  {test_name}: listening already up to date")

    if not changed:
        print("No manifest changes needed.")
        return

    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    print(f"Updated: {manifest_path}")


if __name__ == "__main__":
    main()
