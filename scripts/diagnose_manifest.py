"""Inspect manifest structure for mocks that cannot be fully re-extracted.

Usage:
    python3 scripts/diagnose_manifest.py "Cambridge 10"
    python3 scripts/diagnose_manifest.py "Cambridge 20"

This does not modify any files. It reports test names and the exact
reading/listening blocks, page ranges, and question ranges available to the
extractor. This is useful when QA is empty because the problem is the
manifest/source mapping rather than OCR.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_ROOT = os.path.join(ROOT, "tests")


def _describe_section(label, section):
    if not isinstance(section, dict):
        print(f"    {label}: <not an object>")
        return
    pages = section.get("pages")
    questions = section.get("questions")
    files = section.get("files")
    part_number = section.get("part_number")
    bits = [f"pages={pages or 'MISSING'}", f"questions={questions or 'MISSING'}"]
    if part_number is not None:
        bits.append(f"part_number={part_number}")
    if files:
        bits.append(f"files={files}")
    print(f"    {label}: " + ", ".join(bits))


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(1)

    mock = sys.argv[1]
    mock_dir = os.path.join(TESTS_ROOT, mock)
    manifest_path = os.path.join(mock_dir, "manifest.json")
    if not os.path.isfile(manifest_path):
        print(f"manifest.json not found: {manifest_path}")
        raise SystemExit(1)

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    print(f"=== {mock} ===")
    print(f"manifest keys: {sorted(manifest.keys())}")
    tests = manifest.get("tests", {})
    print(f"tests: {list(tests.keys())}")

    for test_name, cfg in tests.items():
        print(f"\n[{test_name}]")
        if not isinstance(cfg, dict):
            print(f"  config type: {type(cfg).__name__}")
            continue
        print(f"  config keys: {sorted(cfg.keys())}")

        reading = cfg.get("reading")
        if reading is None:
            print("  reading: MISSING")
        else:
            passages = reading.get("passages", []) if isinstance(reading, dict) else []
            print(f"  reading passages: {len(passages)}")
            for i, passage in enumerate(passages, 1):
                _describe_section(f"Reading Passage {i}", passage)

        listening = cfg.get("listening")
        if listening is None:
            print("  listening: MISSING")
        else:
            parts = listening.get("parts", []) if isinstance(listening, dict) else []
            print(f"  listening parts: {len(parts)}")
            for i, part in enumerate(parts, 1):
                _describe_section(f"Listening Part {i}", part)

        writing = cfg.get("writing")
        if writing is None:
            print("  writing: MISSING")
        else:
            print(f"  writing keys: {sorted(writing.keys()) if isinstance(writing, dict) else type(writing).__name__}")

    print("\nNo files were modified.")


if __name__ == "__main__":
    main()
