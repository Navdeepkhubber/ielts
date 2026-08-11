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


_LISTENING_HEADING_RE = re.compile(
    r"^\s*(?:SECTION|PART)\s+(\d+)\s*(?:[QO]uestions?\s+\d+\s*[-–—~]\s*\d+)?\s*\.?\s*$",
    re.IGNORECASE,
)
_QUESTION_RANGE_RE = re.compile(
    r"[QO]uestions?\s+(\d{1,2})\s*[-–—~]\s*(\d{1,2})",
    re.IGNORECASE,
)


def _test_number(name):
    m = re.search(r"test\s*(\d+)", name, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _reading_bounds(manifest, test_name):
    """Return the PDF window immediately before this test's Reading section."""
    cfg = manifest.get("tests", {}).get(test_name, {})
    reading_pages = [
        p
        for passage in cfg.get("reading", {}).get("passages", [])
        for p in passage.get("pages", [])
    ]
    if not reading_pages:
        return None

    current_reading_start = min(reading_pages)
    current_num = _test_number(test_name)
    previous_reading_end = None
    for other_name, other_cfg in manifest.get("tests", {}).items():
        other_num = _test_number(other_name)
        if current_num is None or other_num is None or other_num >= current_num:
            continue
        other_pages = [
            p
            for passage in other_cfg.get("reading", {}).get("passages", [])
            for p in passage.get("pages", [])
        ]
        if other_pages:
            end = max(other_pages)
            previous_reading_end = max(previous_reading_end or end, end)

    return (previous_reading_end + 1 if previous_reading_end else 1, current_reading_start - 1)


def _infer_listening_parts(test_name, manifest, pages_text, audio_parts):
    """Infer Listening page spans using the reliable Reading boundary.

    Older scanned Cambridge books can have a misleading/missing ``Test N``
    heading. In that case the generic structural detector can shift the whole
    Listening section. We instead inspect only the pages between the previous
    test's Reading and the current test's Reading.

    Question-range starts are preferred over SECTION/PART headings because
    headings are sometimes missing from the OCR while ``Questions 1-10`` (or
    ``Questions 11-13``, etc.) is still readable. For each IELTS part we only
    need the first question-range beginning at 1, 11, 21 or 31.
    """
    bounds = _reading_bounds(manifest, test_name)
    if not bounds:
        return None
    start_page, end_page = bounds
    if end_page < start_page:
        return None
    end_page = min(end_page, len(pages_text))

    # First find the first page for each canonical part from a question range
    # whose START number matches that part. This handles ranges such as
    # 11-13 / 14-16 / 17-20 and 21-24 / 25-30.
    part_starts = {}
    for page in range(start_page, end_page + 1):
        text = pages_text[page - 1]
        for m in _QUESTION_RANGE_RE.finditer(text):
            s = int(m.group(1))
            part_num = ((s - 1) // 10) + 1
            expected_start = (part_num - 1) * 10 + 1
            if s == expected_start and part_num not in part_starts:
                part_starts[part_num] = page

    # If question ranges weren't readable, fall back to explicit SECTION/PART
    # headings. Do not mix a partial range result with a partial heading result
    # unless both identify the same part.
    if len(part_starts) < len(audio_parts):
        heading_starts = {}
        for page in range(start_page, end_page + 1):
            text = pages_text[page - 1]
            for raw in text.splitlines():
                m = _LISTENING_HEADING_RE.match(raw.strip())
                if m:
                    n = int(m.group(1))
                    if 1 <= n <= 4 and n not in heading_starts:
                        heading_starts[n] = page
        for n, page in heading_starts.items():
            part_starts.setdefault(n, page)

    audio_by_num = {p.get("part_number"): p for p in audio_parts if p.get("part_number") is not None}
    if any(n not in part_starts for n in range(1, len(audio_parts) + 1)):
        return None

    inferred = []
    for part_num in range(1, len(audio_parts) + 1):
        page = part_starts[part_num]
        next_starts = [p for n, p in part_starts.items() if n > part_num and p > page]
        next_page = min(next_starts) if next_starts else end_page + 1
        pages = list(range(page, next_page))

        audio = audio_by_num.get(part_num, {})
        inferred.append({
            "part_number": part_num,
            "files": audio.get("files", []),
            "questions": [(part_num - 1) * 10 + 1, part_num * 10],
            "pages": pages,
        })

    return inferred


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

    # Do not call detect_structure() here. It can perform a full OCR structure
    # scan and, on older scanned books, can anchor Test N too late. The cached
    # page text is enough for the targeted Reading-bounded inference.
    pages_text, _ = pdf_structure._page_texts(pdf_path)

    changed = False
    for test_name in test_dirs:
        cfg = manifest.setdefault("tests", {}).setdefault(test_name, {})
        old = cfg.get("listening")

        # Generic audio grouping gives us the actual filenames/part numbers;
        # Reading-bounded inference supplies the reliable page ranges.
        generic = _build_listening_block(test_name, audio_root, detected_parts=None)
        inferred_parts = _infer_listening_parts(
            test_name, manifest, pages_text, generic.get("parts", [])
        )
        if inferred_parts:
            new = {"audio_folder": test_name, "parts": inferred_parts}
        else:
            new = generic

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
