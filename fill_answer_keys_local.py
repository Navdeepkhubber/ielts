#!/usr/bin/env python3
"""
fill_answer_keys_local.py -- one-time batch fill using the local
Qwen2.5-VL model via Ollama (lib/free_answer_ocr.py), driven by the
scaffold log so you don't have to click through the UI page by page.

Free. Runs entirely on your Mac. No API key needed.

USAGE
-----
1. Make sure lib/free_answer_ocr.py (Ollama edition) is in your lib/ folder.
2. Save your scaffold server log to a file, e.g. scaffold_log.txt
3. Run:
       python3 fill_answer_keys_local.py scaffold_log.txt
   Optionally restrict to one mock:
       python3 fill_answer_keys_local.py scaffold_log.txt --mock "Mock 10"

This writes directly into answers/<Test N>/{reading,listening}.json for
every answer-key page the scaffold log found. Re-run any single page by
hand afterwards (via the /api/mocks/<mock_id>/ocr-answers route + review
widget) if a particular result looks off -- this batch pass is meant to
get you 90% of the way there in one go, not replace spot-checking.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import test_loader, free_answer_ocr  # noqa: E402

LOG_LINE_RE = re.compile(
    r"\[Mock (?P<mock>[^\]/]+)\]\s*Answer key page for "
    r"(?P<test>Test \d+) (?P<section>listening|reading) "
    r"\(page (?P<page>\d+)\)"
)


def resolve_test_key(test_number: int, manifest: dict) -> str | None:
    """Log lines always say generic 'Test N' -- match that to the real
    manifest key, which might be 'Part 1', 'CAM-15 Test 1 audios', etc."""
    keys = list(manifest.get("tests", {}).keys())

    for k in keys:
        if re.search(r"test\s*0*" + str(test_number) + r"\b", k, re.I):
            return k
    for k in keys:
        nums = re.findall(r"\d+", k)
        if len(nums) == 1 and int(nums[0]) == test_number:
            return k
    if test_number == 1:
        digitless = [k for k in keys if not re.search(r"\d", k)]
        if len(digitless) == 1:
            return digitless[0]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logfile")
    ap.add_argument("--mock", help="only process this mock, e.g. 'Mock 10'")
    args = ap.parse_args()

    log_text = Path(args.logfile).read_text()
    matches = list(LOG_LINE_RE.finditer(log_text))
    if args.mock:
        matches = [m for m in matches
                   if (m["mock"] if m["mock"].startswith("Mock") else f"Mock {m['mock']}") == args.mock]

    print(f"Found {len(matches)} answer-key page reference(s) to process.\n")

    manifest_cache = {}
    written, skipped = 0, 0

    for m in matches:
        mock_id = m["mock"] if m["mock"].startswith("Mock") else f"Mock {m['mock']}"
        test_number = int(m["test"].split()[1])
        section = m["section"]
        page = int(m["page"])

        try:
            if mock_id not in manifest_cache:
                manifest_cache[mock_id] = test_loader.load_manifest(mock_id)
            manifest = manifest_cache[mock_id]
        except FileNotFoundError:
            print(f"SKIP {mock_id}: manifest.json not found")
            skipped += 1
            continue

        test_key = resolve_test_key(test_number, manifest)
        if test_key is None:
            print(f"SKIP {mock_id} Test {test_number} {section}: "
                  f"couldn't confidently match a manifest test key -- fix manually")
            skipped += 1
            continue

        label = f"{mock_id} / {test_key} / {section} (page {page})"
        print(f"{label} ...", end=" ", flush=True)

        pdf_path = test_loader.main_pdf_path(mock_id)
        result = free_answer_ocr.fill_answer_key_page(pdf_path, page, expected_count=40)

        if result["confidence"] == "low":
            print(f"LOW CONFIDENCE ({result['found']}/{result['expected']}) "
                  f"-- writing anyway, but review this one by hand")

        out_path = Path(test_loader.mock_folder(mock_id)) / "answers" / test_key / f"{section}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(result["answers"], f, indent=2, ensure_ascii=False)
        print(f"wrote {result['found']} answers -> {out_path}")
        written += 1

    print(f"\nDone. {written} file(s) written, {skipped} skipped.")
    print("Spot-check the low-confidence ones against the real PDF before trusting them.")


if __name__ == "__main__":
    main()
