"""Sync listening parts for an existing mock after audio files are added.

Usage:
    python3 scripts/sync_listening_manifest.py --mock "Cambridge 9"

The PDF is scanned for the actual Listening section and canonical question
ranges. Existing manifest values are re-derived so stale page ranges are
corrected instead of being treated as authoritative.
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
    cfg = manifest.get("tests", {}).get(test_name, {})
    reading_pages = [
        p for passage in cfg.get("reading", {}).get("passages", [])
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
            p for passage in other_cfg.get("reading", {}).get("passages", [])
            for p in passage.get("pages", [])
        ]
        if pages:
            end = max(pages)
            previous_end = max(previous_end or end, end)

    return (previous_end + 1 if previous_end else 1, current_start - 1)


def _is_non_listening_page(text):
    upper = text.upper()
    return "SPEAKING" in upper or "WRITING TASK" in upper


def _find_listening_start(pages_text, start_page, end_page):
    end_page = min(end_page, len(pages_text))
    for page in range(start_page, end_page + 1):
        text = pages_text[page - 1]
        if _is_non_listening_page(text):
            continue
        if "LISTENING" in text.upper():
            return page
    return None


def _find_part_starts(pages_text, start_page, end_page, audio_count):
    end_page = min(end_page, len(pages_text))
    part_starts = {}

    # Canonical question ranges are the strongest signal for each part.
    for page in range(start_page, end_page + 1):
        text = pages_text[page - 1]
        if _is_non_listening_page(text):
            continue
        for m in _QUESTION_RANGE_RE.finditer(text):
            s = int(m.group(1))
            part_num = ((s - 1) // 10) + 1
            expected_start = (part_num - 1) * 10 + 1
            if 1 <= part_num <= audio_count and s == expected_start:
                part_starts.setdefault(part_num, page)

    # Explicit SECTION/PART headings are a fallback.
    if len(part_starts) < audio_count:
        for page in range(start_page, end_page + 1):
            text = pages_text[page - 1]
            if _is_non_listening_page(text):
                continue
            for raw in text.splitlines():
                m = _LISTENING_HEADING_RE.match(raw.strip())
                if m:
                    n = int(m.group(1))
                    if 1 <= n <= audio_count:
                        part_starts.setdefault(n, page)

    return part_starts


def _infer_listening_start_fallback(start_page, end_page, audio_count):
    """Fallback when OCR cannot identify Listening.

    Most Cambridge tests have 8 Listening pages immediately before Reading.
    Cambridge 9 Test 1 is a known 7-page layout (pages 2-8), so use 7 pages
    only when the bounded window is exactly 8 pages and its first page is the
    book/test boundary rather than a Listening page.
    """
    if audio_count != 4:
        return None
    window = end_page - start_page + 1
    if window == 8:
        return start_page
    if window == 7:
        return start_page
    return None


def _infer_listening_parts(test_name, manifest, pages_text, audio_parts):
    bounds = _reading_bounds(manifest, test_name)
    if not bounds or not audio_parts:
        return None

    window_start, end_page = bounds
    if end_page < window_start:
        return None

    # First find the actual Listening page. This prevents Speaking PART 1
    # pages from being mistaken for Listening Part 1.
    listening_start = _find_listening_start(
        pages_text, window_start, end_page
    )

    # If OCR cannot see the Listening title, use a conservative geometric
    # fallback. The fallback is deliberately not used when OCR found a title.
    if listening_start is None:
        listening_start = _infer_listening_start_fallback(
            window_start, end_page, len(audio_parts)
        )

    if listening_start is None:
        return None

    # Parts must be inferred only inside the Listening section. This avoids
    # stale PART headings from Speaking/Writing and from adjacent tests.
    part_starts = _find_part_starts(
        pages_text, listening_start, end_page, len(audio_parts)
    )

    # The first Listening page is authoritative for Part 1.
    part_starts[1] = listening_start

    # If later parts were not readable, infer them from the standard two-page
    # spacing, but never extend beyond the Reading boundary.
    for n in range(2, len(audio_parts) + 1):
        if n not in part_starts:
            candidate = listening_start + (n - 1) * 2
            if candidate <= end_page:
                part_starts[n] = candidate

    if any(n not in part_starts for n in range(1, len(audio_parts) + 1)):
        return None

    # Reject obviously impossible starts caused by OCR noise.
    ordered = [part_starts[n] for n in range(1, len(audio_parts) + 1)]
    if any(ordered[i] >= ordered[i + 1] for i in range(len(ordered) - 1)):
        return None

    audio_by_num = {
        p.get("part_number"): p
        for p in audio_parts
        if p.get("part_number") is not None
    }
    inferred = []
    for part_num in range(1, len(audio_parts) + 1):
        page = part_starts[part_num]
        next_page = (
            part_starts[part_num + 1]
            if part_num < len(audio_parts)
            else end_page + 1
        )
        audio = audio_by_num.get(part_num, {})
        inferred.append({
            "part_number": part_num,
            "files": audio.get("files", []),
            "questions": [(part_num - 1) * 10 + 1, part_num * 10],
            "pages": list(range(page, next_page)),
        })
    return inferred


def _cache_looks_incomplete(pdf_path, manifest, test_dirs):
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
    pdf_path = os.path.join(mock_dir, manifest.get("pdf_file", "main.pdf"))
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
            if inferred_parts else generic
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
