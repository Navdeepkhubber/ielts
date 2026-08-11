"""Force-regenerate structured Reading/Listening content from existing manifests.

This leaves manifest.json and answers untouched and overwrites only
content/<Test N>.json. It prints QA summaries and, when PaddleOCR is installed,
uses its layout-aware OCR as an additional source for scanned pages before the
existing Tesseract fallback.

Examples:
    python3 scripts/reextract_content.py
    python3 scripts/reextract_content.py --mock "Cambridge 21"
    python3 scripts/reextract_content.py --mock "Cambridge 21" --test "Test 1"
"""
import argparse
import copy
import json
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from lib import content_extract, pdf_structure

TESTS_ROOT = os.path.join(ROOT, "tests")


def _find_pdf(mock_dir):
    main = os.path.join(mock_dir, "main.pdf")
    if os.path.isfile(main):
        return main
    pdfs = sorted(
        os.path.join(mock_dir, f)
        for f in os.listdir(mock_dir)
        if f.lower().endswith(".pdf")
    )
    return pdfs[0] if len(pdfs) == 1 else None


def _load_manifest(mock_dir):
    path = os.path.join(mock_dir, "manifest.json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_content(mock_dir, test_name, content):
    out_dir = os.path.join(mock_dir, "content")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{test_name}.json")
    tmp_path = out_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(content, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp_path, out_path)
    return out_path


def _canonical_questions(section, index, total):
    """Return standard ranges only for the normal three-passage Reading layout.

    Listening ranges are deliberately left untouched because some Cambridge
    manifests represent multiple audio segments in ways that don't map 1:1 to
    the printed question ranges. We should not infer those ranges from audio
    filenames during content extraction.
    """
    if section == "reading":
        ranges = ([1, 13], [14, 26], [27, 40])
        if total == 3 and index < len(ranges):
            return ranges[index]
    return None


def _content_cfg(cfg):
    out = copy.deepcopy(cfg)

    reading = out.get("reading", {})
    passages = reading.get("passages", [])
    for i, passage in enumerate(passages):
        canonical = _canonical_questions("reading", i, len(passages))
        if canonical:
            passage["questions"] = canonical

    # Preserve Listening ranges from the source manifest. A single IELTS
    # section may be represented by multiple audio files, so filenames are not
    # a safe basis for rewriting its question numbers.
    return out


def _section_summary(label, section):
    qa = section.get("qa", {})
    expected = qa.get("expected_count", 0)
    detected = qa.get("detected_count", 0)
    missing = qa.get("missing_questions", [])
    duplicates = qa.get("duplicate_questions", [])
    unexpected = qa.get("unexpected_questions", [])
    ok = qa.get("ok", False)
    marker = "OK" if ok else "CHECK"
    details = []
    if missing:
        details.append("missing=" + ",".join(map(str, missing)))
    if duplicates:
        details.append("duplicates=" + ",".join(map(str, duplicates)))
    if unexpected:
        details.append("unexpected=" + ",".join(map(str, unexpected)))
    suffix = f" ({'; '.join(details)})" if details else ""
    print(f"    {label}: {detected}/{expected} questions [{marker}]{suffix}")
    return ok


def _print_qa(test_name, content):
    all_ok = True
    print("  QA:")
    reading = content.get("reading", {}).get("passages", [])
    for i, section in enumerate(reading, 1):
        all_ok = _section_summary(f"Reading Passage {i}", section) and all_ok

    listening = content.get("listening", {}).get("parts", [])
    for i, section in enumerate(listening, 1):
        all_ok = _section_summary(f"Listening Part {i}", section) and all_ok

    reading_expected = sum(s.get("qa", {}).get("expected_count", 0) for s in reading)
    reading_detected = sum(s.get("qa", {}).get("detected_count", 0) for s in reading)
    listening_expected = sum(s.get("qa", {}).get("expected_count", 0) for s in listening)
    listening_detected = sum(s.get("qa", {}).get("detected_count", 0) for s in listening)
    if reading:
        print(f"    Reading total: {reading_detected}/{reading_expected} {'OK' if reading_detected == reading_expected and all(s.get('qa', {}).get('ok') for s in reading) else 'CHECK'}")
    if listening:
        print(f"    Listening total: {listening_detected}/{listening_expected} {'OK' if listening_detected == listening_expected and all(s.get('qa', {}).get('ok') for s in listening) else 'CHECK'}")
    return all_ok


def _test_pages(cfg):
    pages = set()
    for section_name, key in (("reading", "passages"), ("listening", "parts")):
        for section in cfg.get(section_name, {}).get(key, []):
            pages.update(int(p) for p in (section.get("pages") or []) if str(p).isdigit())
    return sorted(pages)


def _add_paddle_ocr_text(pdf_path, pages_text, pages):
    """Append layout-aware PaddleOCR text to selected pages when installed."""
    try:
        from lib import paddle_ocr
        import fitz
        from PIL import Image
    except ImportError:
        return 0

    # Avoid paying the model startup cost if PaddleOCR isn't installed.
    if paddle_ocr._get_ocr() is None:
        return 0

    added = 0
    doc = fitz.open(pdf_path)
    try:
        with tempfile.TemporaryDirectory(prefix="ielts-paddle-") as tmp:
            for page_number in pages:
                if page_number < 1 or page_number > len(doc):
                    continue
                page = doc[page_number - 1]
                pix = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), colorspace=fitz.csRGB, alpha=False)
                image_path = os.path.join(tmp, f"page-{page_number}.png")
                pix.save(image_path)
                lines = paddle_ocr.ocr_page(image_path)
                if not lines:
                    continue
                # Keep native/cached text and append PaddleOCR as an additional
                # representation. The downstream parser deduplicates question
                # numbers and chooses the longest question text.
                pages_text[page_number - 1] = pages_text[page_number - 1].rstrip() + "\n\n" + "\n".join(lines)
                added += 1
    finally:
        doc.close()
    return added


def reextract_mock(mock_name, test_filter=None):
    mock_dir = os.path.join(TESTS_ROOT, mock_name)
    if not os.path.isdir(mock_dir):
        raise FileNotFoundError(f"Mock folder not found: {mock_dir}")

    manifest = _load_manifest(mock_dir)
    if not manifest:
        raise FileNotFoundError(f"manifest.json not found for {mock_name}")

    pdf_path = _find_pdf(mock_dir)
    if not pdf_path:
        raise FileNotFoundError(f"Could not identify a PDF for {mock_name}")

    print(f"[{mock_name}] reading PDF text/OCR: {os.path.basename(pdf_path)}", flush=True)
    pages_text, _ = pdf_structure._page_texts(pdf_path)

    tests = manifest.get("tests", {})
    selected = [test_filter] if test_filter else list(tests.keys())
    missing = [name for name in selected if name not in tests]
    if missing:
        raise ValueError(f"Tests not found in manifest: {', '.join(missing)}")

    for test_name in selected:
        cfg = _content_cfg(tests[test_name])
        paddle_pages = _add_paddle_ocr_text(pdf_path, pages_text, _test_pages(cfg))
        if paddle_pages:
            print(f"  PaddleOCR: processed {paddle_pages} section pages", flush=True)
        content = content_extract.build_content_for_test(pages_text, cfg, pdf_path=pdf_path)
        path = _write_content(mock_dir, test_name, content)
        print(f"  {test_name}: {path}")
        _print_qa(test_name, content)


def main():
    parser = argparse.ArgumentParser(description="Force-regenerate structured mock content without changing manifests or answers.")
    parser.add_argument("--mock", help="Exact mock directory name under tests/")
    parser.add_argument("--test", dest="test_name", help="Exact test name from manifest.json, e.g. 'Test 1'")
    args = parser.parse_args()

    if args.test_name and not args.mock:
        parser.error("--test requires --mock")

    mock_names = [args.mock] if args.mock else sorted(
        d for d in os.listdir(TESTS_ROOT)
        if os.path.isdir(os.path.join(TESTS_ROOT, d))
    )
    for mock_name in mock_names:
        try:
            reextract_mock(mock_name, args.test_name)
        except (FileNotFoundError, ValueError) as exc:
            print(f"[{mock_name}] SKIPPED: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
