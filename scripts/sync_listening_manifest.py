"""Sync listening parts for an existing mock after audio files are added.

Usage:
    python3 scripts/sync_listening_manifest.py --mock "Cambridge 9"

The PDF is scanned for the first page of each canonical IELTS Listening part.
Question-range headings (Questions 1-10, 11-20, 21-30, 31-40) are preferred;
SECTION/PART headings are only a fallback. Speaking/other PART headings are
explicitly ignored so e.g. Cambridge 9 Test 2's Speaking PART 1 page cannot
be mistaken for Listening Part 1.
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
    """Return the PDF window between the previous Reading section and this one."""
    cfg = manifest.get("tests", {}).get(test_name, {})
    reading_pages = [
        p
        for passage in cfg.get("reading", {}).get("passages", [])
        for p in passage.get("pages", [])
    ]
    if not reading_pages:
        return None

    current_start = min(reading_pages)
    current_num = _test_number(test_name)
    previous_end = None
    for other_name, other_cfg in manifest.get("tests", {}).items():
        other_num = _test_number(other_name)
        if current_num is None or other_num is None or other_num >= current_num:
            continue
        pages = [
            p
            for passage in other_cfg.get("reading", {}).get("passages", [])
            for p in passage.get("pages", [])
        ]
        if pages:
            end = max(pages)
            previous_end = max(previous_end or end, end)

    return (previous_end + 1 if previous_end else 1, current_start - 1)


def _is_non_listening_page(text):
    """Reject obvious Speaking/Writing pages from PART/SECTION fallback."""
    upper = text.upper()
    return "SPEAKING" in upper or "WRITING TASK" in upper


def _find_part_starts(pages_text, start_page, end_page, audio_count):
    """Find first page of Listening Parts 1..N within a bounded test window."""
    end_page = min(end_page, len(pages_text))
    part_starts = {}

    # Strong signal: the printed question ranges. A page containing
    # Questions 1-10 is Part 1, 11-20 is Part 2, etc. This avoids false
    # positives from Speaking PART 1 / PART 2.
    for page in range(start_page, end_page + 1):
        text = pages_text[page - 1]
        for m in _QUESTION_RANGE_RE.finditer(text):
            s = int(m.group(1))
            part_num = ((s - 1) // 10) + 1
            expected_start = (part_num - 1) * 10 + 1
            if 1 <= part_num <= audio_count and s == expected_start:
                part_starts.setdefault(part_num, page)

    # Fallback: explicit SECTION/PART headings, but never accept a heading
    # from a page that clearly belongs to Speaking or Writing.
    if len(part_starts) < audio_count:
        for page in range(start_page, end_page + 1):
            text = pages_text[page - 1]
            if _is_non_listening_page(text):
                continue
            for raw in text.splitlines():
                m = _LISTENING_HEADING_RE.match(raw.strip())
                if not m:
                    continue
                n = int(m.group(1))
                if 1 <= n <= audio_count:
                    part_starts.setdefault(n, page)

    return part_starts


def _infer_missing_first_part(part_starts, start_page, end_page, audio_count):
    """Infer a missing Part 1 without mistaking Speaking PART 1 for Listening.

    In scanned Cambridge books the first Listening page can be almost entirely
    unreadable, while Part 2/3/4 headings are OCR-visible. In that case the
    old fallback used the beginning of the test window, which can be a Speaking
    page. If a later Listening part is known, infer the missing first part from
    the nearest later part using the normal two-page Listening-part span.
    """
    if 1 in part_starts or audio_count < 2:
        return

    later = sorted(p for n, p in part_starts.items() if n > 1)
    if not later:
        return

    candidate = later[0] - 2
    if candidate >= start_page and candidate < part_starts[later.index(later[0]) if False else 2] if False else True:
        # Keep the candidate inside the bounded Listening window. The explicit
        # check below also avoids reintroducing a page before the window.
        if start_page <= candidate < later[0] <= end_page:
            part_starts[1] = candidate


def _infer_listening_parts(test_name, manifest, pages_text, audio_parts):
    bounds = _reading_bounds(manifest, test_name)
    if not bounds or not audio_parts:
        return None

    start_page, end_page = bounds
    if end_page < start_page:
        return None

    part_starts = _find_part_starts(
        pages_text, start_page, end_page, len(audio_parts)
    )

    # Do not use start_page as Part 1. It can be Speaking/Writing when the
    # Listening first-page OCR is blank. Infer Part 1 from the next detected
    # Listening part instead.
    _infer_missing_first_part(
        part_starts, start_page, end_page, len(audio_parts)
    )

    # If Part 4 alone is unreadable, use the last two pages before Reading only
    # when Parts 1-3 are known.
    if 4 <= len(audio_parts) and 4 not in part_starts and all(
        n in part_starts for n in (1, 2, 3)
    ):
        if end_page >= part_starts[3] + 2:
            part_starts[4] = end_page - 1

    if any(n not in part_starts for n in range(1, len(audio_parts) + 1)):
        return None

    audio_by_num = {
        p.get("part_number"): p
        for p in audio_parts
        if p.get("part_number") is not None
    }

    inferred = []
    for part_num in range(1, len(audio_parts) + 1):
        page = part_starts[part_num]
        next_starts = [
            p for n, p in part_starts.items()
            if n > part_num and p > page
        ]
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


def _cache_looks_incomplete(pdf_path, manifest, test_dirs):
    """Detect an old OCR cache that is mostly empty in Listening windows."""
    cache_path = pdf_structure._cache_path(pdf_path)
    try:
        with open(cache_path) as f:
            cache = json.load(f)
        if cache.get("key") != pdf_structure._cache_key(pdf_path):
            return True
        texts = cache.get("texts", [])
        for test_name in test_dirs:
            bounds = _reading_bounds(manifest, test_name)
            if not bounds:
                continue
            start, end = bounds
            if end < start or not texts:
                continue
            window = texts[max(0, start - 1):min(len(texts), end)]
            meaningful = sum(len(t.strip()) >= _MIN_TEXT_CHARS for t in window)
            if window and meaningful < max(1, len(window) // 2):
                return True
        return False
    except (OSError, ValueError, KeyError, TypeError):
        return False


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

    if _cache_looks_incomplete(pdf_path, manifest, test_dirs):
        cache_path = pdf_structure._cache_path(pdf_path)
        try:
            os.remove(cache_path)
            print("  Existing PDF text cache is incomplete; refreshing OCR cache.")
        except OSError:
            pass

    pages_text, _ = pdf_structure._page_texts(pdf_path)
    changed = False

    for test_name in test_dirs:
        cfg = manifest.setdefault("tests", {}).setdefault(test_name, {})
        old = cfg.get("listening")

        generic = _build_listening_block(
            test_name, audio_root, detected_parts=None
        )
        inferred_parts = _infer_listening_parts(
            test_name, manifest, pages_text, generic.get("parts", [])
        )
        new = (
            {"audio_folder": test_name, "parts": inferred_parts}
            if inferred_parts
            else generic
        )

        if old != new:
            cfg["listening"] = new
            changed = True
            print(f"  {test_name}: listening parts={len(new['parts'])}")
            for part in new["parts"]:
                print(
                    f"    Part {part.get('part_number', '?')}: "
                    f"questions={part['questions']}, pages={part['pages']}"
                )
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
