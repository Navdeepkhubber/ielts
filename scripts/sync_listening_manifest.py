"""Sync listening parts for an existing mock after audio files are added.

Usage:
    python3 scripts/sync_listening_manifest.py --mock "Cambridge 9"

Existing listening page ranges are never treated as authoritative. Page
boundaries are derived from evidence in the PDF. If cached text is
insufficient, a small targeted OCR pass is run only for the test's
pre-Reading window instead of guessing or OCRing the whole book.
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

_QUESTION_RANGE_RE = re.compile(
    r"[QO]uestions?\s+(\d{1,2})\s*[-–—~]\s*(\d{1,2})", re.IGNORECASE
)
# Listening question sheets often expose the numbers as standalone tokens
# even when OCR misses the word "Questions" or mangles the range heading.
_QUESTION_NUMBER_RE = re.compile(r"(?m)^\s*(\d{1,2})\s*[.)]\s+")
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


def _question_starts(pages_text, start_page, end_page, audio_count):
    starts = {}
    candidates = {}
    end_page = min(end_page, len(pages_text))

    for page in range(start_page, end_page + 1):
        text = pages_text[page - 1]
        if _is_non_listening_page(text):
            continue

        # Strong evidence: an explicit Questions X-Y heading.
        for m in _QUESTION_RANGE_RE.finditer(text):
            s, e = int(m.group(1)), int(m.group(2))
            if 1 <= s <= 40 and e == s + 9:
                part = ((s - 1) // 10) + 1
                if 1 <= part <= audio_count:
                    candidates.setdefault(part, []).append((3, page))

        # Medium evidence: standalone question numbers. Score a page by how
        # many numbers from a single canonical 10-question block it contains.
        numbers = {int(m.group(1)) for m in _QUESTION_NUMBER_RE.finditer(text) if 1 <= int(m.group(1)) <= 40}
        for part in range(1, audio_count + 1):
            lo, hi = (part - 1) * 10 + 1, part * 10
            hits = len(numbers & set(range(lo, hi + 1)))
            if hits >= 2:
                candidates.setdefault(part, []).append((min(2, hits), page))

    # Prefer explicit ranges, then the page with the strongest concentration
    # of question numbers. In a tie choose the earliest page. This derives
    # boundaries from the PDF rather than from a fixed page count.
    for part, evidence in candidates.items():
        evidence.sort(key=lambda x: (-x[0], x[1]))
        starts[part] = evidence[0][1]
    return starts


def _heading_part_starts(pages_text, start_page, end_page, audio_count):
    """Find SECTION/PART headings without treating SPEAKING as Listening."""
    pattern = re.compile(
        r"^\s*(?:SECTION|PART)\s+(\d+)\b.*$", re.IGNORECASE | re.MULTILINE
    )
    starts = {}
    end_page = min(end_page, len(pages_text))
    for page in range(start_page, end_page + 1):
        text = pages_text[page - 1]
        if _is_non_listening_page(text):
            continue
        for line in text.splitlines():
            m = pattern.match(line.strip())
            if m:
                n = int(m.group(1))
                if 1 <= n <= audio_count:
                    starts.setdefault(n, page)
    return starts


def _derive_parts(pages_text, start_page, end_page, audio_parts):
    """Derive all part spans from PDF evidence; never use existing page values."""
    if not audio_parts or end_page < start_page:
        return None

    count = len(audio_parts)
    starts = _question_starts(pages_text, start_page, end_page, count)
    headings = _heading_part_starts(pages_text, start_page, end_page, count)

    # Question-range/number evidence is preferred. A section heading fills a
    # gap only when the question sheet itself was not OCR'd reliably.
    for n, page in headings.items():
        starts.setdefault(n, page)

    if any(n not in starts for n in range(1, count + 1)):
        return None

    ordered = [starts[n] for n in range(1, count + 1)]
    if any(ordered[i] >= ordered[i + 1] for i in range(len(ordered) - 1)):
        return None

    audio_by_num = {p.get("part_number"): p for p in audio_parts}
    result = []
    for n in range(1, count + 1):
        start = starts[n]
        stop = starts[n + 1] if n < count else end_page + 1
        audio = audio_by_num.get(n, {})
        result.append({
            "part_number": n,
            "files": audio.get("files", []),
            "questions": [(n - 1) * 10 + 1, n * 10],
            "pages": list(range(start, stop)),
        })
    return result


def _targeted_ocr(pdf_path, pages_text, start_page, end_page):
    """OCR only the unresolved pre-Reading window, keeping memory bounded."""
    if not getattr(pdf_structure, "_OCR_AVAILABLE", False):
        return False
    try:
        import fitz
        doc = fitz.open(pdf_path)
        try:
            zoom = 1.7
            for page_num in range(start_page, end_page + 1):
                page = doc[page_num - 1]
                text = pdf_structure._ocr_page_text(page, zoom=zoom)
                if text and len(text.strip()) >= _MIN_TEXT_CHARS:
                    pages_text[page_num - 1] = text
        finally:
            doc.close()
        return True
    except Exception as exc:
        print(f"  Targeted OCR failed: {exc}")
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
    pages_text, _ = pdf_structure._page_texts(pdf_path)
    changed = False

    for test_name in test_dirs:
        cfg = manifest.setdefault("tests", {}).setdefault(test_name, {})
        generic = _build_listening_block(test_name, audio_root, detected_parts=None)
        audio_parts = generic.get("parts", [])
        bounds = _reading_bounds(manifest, test_name)

        inferred = None
        if bounds:
            inferred = _derive_parts(pages_text, bounds[0], bounds[1], audio_parts)
            if inferred is None:
                print(f"  {test_name}: retrying targeted OCR for pages {bounds[0]}-{bounds[1]}")
                if _targeted_ocr(pdf_path, pages_text, bounds[0], bounds[1]):
                    inferred = _derive_parts(pages_text, bounds[0], bounds[1], audio_parts)

        if inferred:
            new = {"audio_folder": test_name, "parts": inferred}
            old = cfg.get("listening")
            if old != new:
                cfg["listening"] = new
                changed = True
                print(f"  {test_name}: listening derived from PDF")
                for part in inferred:
                    print(
                        f"    Part {part['part_number']}: "
                        f"questions={part['questions']}, pages={part['pages']}"
                    )
            else:
                print(f"  {test_name}: listening derived from PDF and up to date")
        else:
            unresolved = {
                "audio_folder": test_name,
                "parts": [
                    {
                        "part_number": p.get("part_number"),
                        "files": p.get("files", []),
                        "questions": p.get("questions"),
                        "pages": [],
                    }
                    for p in audio_parts
                ],
            }
            old = cfg.get("listening")
            if old != unresolved:
                cfg["listening"] = unresolved
                changed = True
            print(f"  {test_name}: UNRESOLVED - no reliable PDF boundaries")

    if changed:
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)
            f.write("\n")
        print(f"Updated: {manifest_path}")
    else:
        print("No manifest changes needed.")


if __name__ == "__main__":
    main()
