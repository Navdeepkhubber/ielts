#!/usr/bin/env python3
"""Import a local PDF collection into the app's existing test-package format.

Source PDFs are copied into tests/<book-id>/main.pdf, which is already
ignored by git. Only small JSON manifests are committed. The source
aggregator branding is not used as the app's test name. External audio and
answer-key URLs embedded in the PDFs are retained in the manifest.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lib.pdf_book_parser import parse_book  # noqa: E402


def slugify(name: str) -> str:
    name = re.sub(r"^KeenIELTS\s*-\s*", "", name, flags=re.I)
    name = re.sub(r"\s*\((?:academic|general)\)\s*$", "", name, flags=re.I)
    name = re.sub(r"\s+", " ", name).strip()
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def display_name(name: str) -> str:
    name = re.sub(r"^KeenIELTS\s*-\s*", "", name, flags=re.I)
    name = re.sub(r"\s*\((?:academic|general)\)\s*$", "", name, flags=re.I)
    return re.sub(r"\s+", " ", name).strip()


def manifest_from_parsed(parsed: dict, source_pdf: Path) -> dict:
    tests = {}
    for test in parsed["tests"]:
        cfg = {"variant": "academic"}
        for section in ("reading", "writing", "speaking"):
            if test.get(section):
                cfg[section] = test[section]
        if test.get("listening"):
            cfg["listening"] = test["listening"]
        if test.get("answer_keys"):
            cfg["answer_keys"] = test["answer_keys"]
        tests[test["name"]] = cfg

    return {
        "mock_name": display_name(source_pdf.stem),
        "pdf_file": "main.pdf",
        "source": {
            "filename": source_pdf.name,
            "page_count": parsed["page_count"],
            "audio_available": parsed["audio_available"],
            "answer_keys_available": parsed["answer_keys_available"],
        },
        "tests": tests,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="Directory containing PDF files")
    parser.add_argument("--only", nargs="*", help="Optional PDF filename fragments")
    parser.add_argument("--force", action="store_true", help="Replace an existing imported package")
    args = parser.parse_args()

    source = args.source.expanduser().resolve()
    if not source.is_dir():
        parser.error(f"Not a directory: {source}")

    pdfs = sorted(source.glob("*.pdf"))
    if args.only:
        pdfs = [p for p in pdfs if any(fragment.lower() in p.name.lower() for fragment in args.only)]
    if not pdfs:
        parser.error("No PDF files found")

    tests_root = ROOT / "tests"
    tests_root.mkdir(exist_ok=True)
    (tests_root / ".gitkeep").touch(exist_ok=True)

    for pdf in pdfs:
        book_id = slugify(pdf.stem)
        destination = tests_root / book_id
        if destination.exists() and not args.force:
            print(f"SKIP {pdf.name}: tests/{book_id} already exists (use --force)")
            continue

        parsed = parse_book(pdf)
        manifest = manifest_from_parsed(parsed, pdf)
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pdf, destination / "main.pdf")
        (destination / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

        reading_layouts = sum(bool(test.get("reading") and test["reading"].get("passages")) for test in parsed["tests"])
        audio_tests = sum(bool(test.get("listening", {}).get("audio_url")) for test in parsed["tests"])
        key_tests = sum(bool(test.get("answer_keys")) for test in parsed["tests"])
        print(
            f"IMPORTED {pdf.name} -> tests/{book_id} "
            f"({len(parsed['tests'])} tests, {reading_layouts} reading layouts, "
            f"{audio_tests} audio links, {key_tests} answer-key sets)"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
