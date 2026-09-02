"""Refresh manifest structure from the native PDF detector."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import pdf_structure


TESTS_ROOT = Path(__file__).resolve().parents[1] / "tests"


def refresh_manifest(mock_dir):
    manifest_path = mock_dir / "manifest.json"
    if not manifest_path.is_file():
        return False
    with manifest_path.open() as file:
        manifest = json.load(file)

    pdf_path = mock_dir / manifest.get("pdf_file", "main.pdf")
    if not pdf_path.is_file():
        return False
    detected = pdf_structure.detect_structure(str(pdf_path), use_ocr=True)["tests"]
    changed = False

    for test_name, config in manifest.get("tests", {}).items():
        found = detected.get(test_name)
        if not found:
            continue

        reading = found.get("reading_passages") or []
        if reading and "reading" in config:
            config["reading"]["passages"] = [
                {"pages": item["pages"], "questions": item["questions"]}
                for item in reading
            ]
            changed = True

        listening = found.get("listening_parts") or []
        parts = config.get("listening", {}).get("parts", [])
        if listening and len(parts) == len(listening):
            for part, item in zip(parts, listening):
                part["pages"] = item["pages"]
                part["questions"] = item["questions"]
            changed = True

    if changed:
        with manifest_path.open("w") as file:
            json.dump(manifest, file, indent=2)
            file.write("\n")
    return changed


def main():
    refreshed = 0
    for mock_dir in sorted(TESTS_ROOT.iterdir()):
        if mock_dir.is_dir() and refresh_manifest(mock_dir):
            refreshed += 1
            print(f"refreshed {mock_dir.name}/manifest.json")
    print(f"Refreshed {refreshed} manifest(s).")


if __name__ == "__main__":
    main()