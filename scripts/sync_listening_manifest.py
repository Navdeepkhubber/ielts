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
_MIN_TEXT_CHARS = 20


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


def _cache_looks_incomplete(pdf_path, manifest, test_dirs):
    """Detect an old/incomplete OCR cache before targeted listening inference.

    Cambridge 9 has scanned Listening pages with almost no native PDF text.
    An older cache can therefore contain only the tiny footer/watermark text,
    causing the targeted inference to believe the Listening headings are
    missing. If a listening window is mostly empty in the cache, invalidate it
    once so pdf_structure performs a fresh OCR pass.
    """
    cache_path = pdf_structure._cache_path(pdf_path)
    try:
        with open(cache_path) as f:
            cache = json.load(f)
        if cache.get("key") != pdf_structure._cache_key(pdf_path):
            return True
        texts = cache.get("texts", [])
        windows = []
        for test_name in test_dirs:
            bounds = _reading_bounds(manifest, test_name)
            if bounds:
                start, end = bounds
                if end >= start:
                    windows.append((max(1, start), min(len(texts), end)))
        for start, end in windows:
            window = texts[start - 1:end]
            if not window:
                continue
            meaningful = sum(len(t.strip()) >= _MIN_TEXT_CHARS for t in window)
            # A normal text-layer window is not expected to be overwhelmingly
            # empty. Scanned Cambridge listening pages commonly are.
            if meaningful < max(1, len(window) // 2):
                return True
        return False
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _refresh_incomplete_cache(pdf_path, manifest, test_dirs):
    if not _cache_looks_incomplete(pdf_path, manifest, test_dirs):
        return False
    cache_path = pdf_structure._cache_path(pdf_path)
    try:
        os.remove(cache_path)
        print("  Existing PDF text cache is incomplete for the Listening pages; refreshing OCR cache.")
        return True
    except OSError:
        return False


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

    # A scanned first Listening page may have no usable text at all. If later
    # parts are found, the Listening window itself is the only safe start for
    # Part 1. Likewise, if Part 4's heading is missing but Parts 1-3 are found,
    # the last part occupies the remaining pages before Reading.
    if 1 not in part_starts and any(n in part_starts for n in (2, 3, 4)):
        part_starts[1] = start_page
    if 4 not in part_starts and all(n in part_starts for n in (1, 2, 3)):
        # If the 31-40 range wasn't OCR'd, use the last known part boundary
        # only when there are pages left before Reading. We split at the last
        # page of the Listening window, preserving at least one page for Part 4.
        last_known = part_starts[3]
        if end_page >= last_known + 1:
            part_starts[4] = end_page - 1

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

    # Cambridge scanned books can have an older cache produced before OCR
    # improvements. Refresh it only when the relevant Listening windows are
    # mostly empty; normal text-layer books keep the fast cached path.
    _refresh_incomplete_cache(pdf_path, manifest, test_dirs)
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
