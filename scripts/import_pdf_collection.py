#!/usr/bin/env python3
"""Import IELTS PDF books as local, renderable test packages.

Listening/audio is deliberately skipped for now. Reading, Writing and
Speaking content remains in the original PDF and the manifest records the
page ranges used by the existing application renderer.
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
        cfg = {"variant": test.get("variant", "academic")}
        for section in ("reading", "writing", "speaking"):
            if test.get(section):
                cfg[section] = test[section]
        tests[test["name"]] = cfg

    return {
        "mock_name": display_name(source_pdf.stem),
        "pdf_file": "main.pdf",
        "source": {
            "filename": source_pdf.name,
            "page_count": parsed["page_count"],
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
        pdfs = [
            p for p in pdfs
            if any(fragment.lower() in p.name.lower() for fragment in args.only)
        ]
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
        if not parsed["tests"]:
            print(f"SKIP {pdf.name}: no practice tests detected")
            continue

        manifest = manifest_from_parsed(parsed, pdf)
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pdf, destination / "main.pdf")
        (destination / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        reading_tests = sum(
            bool(test.get("reading", {}).get("passages")) for test in parsed["tests"]
        )
        writing_tests = sum(bool(test.get("writing")) for test in parsed["tests"])
        speaking_tests = sum(bool(test.get("speaking")) for test in parsed["tests"])
        print(
            f"IMPORTED {pdf.name} -> tests/{book_id} "
            f"({len(parsed['tests'])} tests; "
            f"Reading {reading_tests}, Writing {writing_tests}, Speaking {speaking_tests}; "
            f"Listening skipped)"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
