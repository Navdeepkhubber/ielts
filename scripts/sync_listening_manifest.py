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
    """Return (search_start, search_end) for a test's Listening pages.

    The Reading pages are a much more reliable boundary than the structural
    scanner's Test N heading on older scanned Cambridge PDFs. Listening sits
    immediately before Reading, while Speaking/Writing may sit between tests.
    """
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
    """Infer Listening page spans from section headings inside the test window.

    This fixes older scanned books where the generic structural scanner anchors
    a Test N boundary too late (often on a page carrying a running header),
    which can shift Listening pages by several pages. The existing Reading
    manifest gives us a reliable upper boundary, so we only inspect the pages
    immediately preceding Reading for this test.
    """
    bounds = _reading_bounds(manifest, test_name)
    if not bounds:
        return None
    start_page, end_page = bounds
    if end_page < start_page:
        return None

    candidates = []
    for page in range(start_page, min(end_page, len(pages_text)) + 1):
        text = pages_text[page - 1]
        for raw in text.splitlines():
            line = raw.strip()
            m = _LISTENING_HEADING_RE.match(line)
            if m:
                candidates.append((page, int(m.group(1))))

    # Collapse repeated OCR/header hits on the same part.
    collapsed = []
    for page, part_num in candidates:
        if not collapsed or collapsed[-1][1] != part_num:
            collapsed.append((page, part_num))

    if not collapsed:
        return None

    # Speaking pages can contain "PART 1/2/3" before Listening. The first
    # genuine Listening heading is the first section heading on a page that
    # also contains the word LISTENING. Subsequent section headings are then
    # taken in sequence.
    first_idx = None
    for i, (page, part_num) in enumerate(collapsed):
        text = pages_text[page - 1]
        if re.search(r"\bLISTENING\b", text, re.IGNORECASE):
            first_idx = i
            break
    if first_idx is None:
        return None
    collapsed = collapsed[first_idx:]

    # Keep only the real IELTS sequence 1..4. Ignore later answer-key/tape-
    # script headings that may fall in a broad page window.
    valid = []
    expected = 1
    for page, part_num in collapsed:
        if part_num == expected:
            valid.append((page, part_num))
            expected += 1
        elif valid and part_num > expected:
            break
    if not valid:
        return None

    audio_by_num = {p.get("part_number"): p for p in audio_parts if p.get("part_number") is not None}
    inferred = []
    for i, (page, part_num) in enumerate(valid):
        next_page = valid[i + 1][0] if i + 1 < len(valid) else end_page + 1
        pages = list(range(page, next_page))
        q_range = None
        for p in pages:
            if p > len(pages_text):
                continue
            for m in _QUESTION_RANGE_RE.finditer(pages_text[p - 1]):
                s, e = int(m.group(1)), int(m.group(2))
                if s == (part_num - 1) * 10 + 1 and e == part_num * 10:
                    q_range = [s, e]
                    break
            if q_range:
                break
        if not q_range:
            q_range = [(part_num - 1) * 10 + 1, part_num * 10]

        audio = audio_by_num.get(part_num, {})
        inferred.append({
            "part_number": part_num,
            "files": audio.get("files", []),
            "questions": q_range,
            "pages": pages,
        })

    if len(inferred) != len(audio_parts):
        return None
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

    def progress(done, total):
        if done == 1 or done % 10 == 0 or done == total:
            print(f"  OCR structure scan: {done}/{total} pages")

    structure = pdf_structure.detect_structure(pdf_path, ocr_progress=progress)
    pages_text, _ = pdf_structure._page_texts(pdf_path)
    detected_tests = structure.get("tests", {})

    changed = False
    for test_name in test_dirs:
        cfg = manifest.setdefault("tests", {}).setdefault(test_name, {})
        detected = detected_tests.get(test_name, {})
        detected_parts = detected.get("listening_parts", [])
        old = cfg.get("listening")

        # Prefer the Reading-bounded inference for older scanned books. Fall
        # back to the generic structural detector for books where the Reading
        # block is unavailable or the audio layout is genuinely unusual.
        generic = _build_listening_block(test_name, audio_root, detected_parts=detected_parts)
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
