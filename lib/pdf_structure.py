"""
Best-effort structural scan of main.pdf to auto-detect page numbers for
Test / Reading Passage / Listening Section / Writing Task boundaries, and
"Questions X-Y" ranges -- so manifest.json's reading/listening/writing
blocks can be generated automatically instead of typed in by hand.

IMPORTANT SCOPE NOTE: this only ever looks at short structural heading
lines (page numbers + a handful of words like "Reading Passage 2" or
"Questions 14-26") to figure out where things are. It never stores,
displays, or reproduces the actual passage/question/prompt text anywhere
-- that stays exactly as before, rendered as an image of your original
PDF page. This is purely a "table of contents" scan.

Because heading wording/format varies across publishers, treat this as a
best guess: it prints exactly what it detected (test/section/page/
question-range) so you can eyeball it once, and it flags anything it
couldn't confidently place instead of silently guessing wrong.
"""
import re

import fitz  # PyMuPDF

# OCR fallback (lazy import -- only needed if a page has no text layer at all,
# which is common for scanned Cambridge PDFs with no embedded text).
try:
    import pytesseract
    from PIL import Image
    import io as _io
    _OCR_AVAILABLE = True
except ImportError:
    _OCR_AVAILABLE = False

_MIN_NATIVE_CHARS = 20  # below this, treat the page as "no real text layer" and try OCR

_TEST_RE = re.compile(r"^\s*Test\s+(\d+)\s*$", re.IGNORECASE | re.MULTILINE)
_READING_RE = re.compile(r"READING\s+PASSAGE\s+(\d+)", re.IGNORECASE)
_LISTENING_RE = re.compile(r"\bSECTION\s+(\d+)\b", re.IGNORECASE)
_WRITING_RE = re.compile(r"WRITING\s+TASK\s+(\d+)", re.IGNORECASE)
_QUESTIONS_RE = re.compile(r"Questions?\s+(\d+)\s*[-–—]\s*(\d+)", re.IGNORECASE)


def _ocr_page_text(page, zoom=2.5):
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    img = Image.open(_io.BytesIO(pix.tobytes("png")))
    return pytesseract.image_to_string(img)


def _page_texts(pdf_path, use_ocr=True, ocr_progress=None):
    """
    Returns (texts, ocr_page_count). Falls back to OCR per-page when the
    native text layer is empty/near-empty (scanned PDFs). OCR is slow
    (~1-2s/page), so it's only used on pages that actually need it, and
    only if pytesseract/Tesseract are installed.
    """
    doc = fitz.open(pdf_path)
    texts = []
    ocr_count = 0
    try:
        for i in range(len(doc)):
            text = doc[i].get_text()
            if len(text.strip()) < _MIN_NATIVE_CHARS and use_ocr and _OCR_AVAILABLE:
                text = _ocr_page_text(doc[i])
                ocr_count += 1
                if ocr_progress:
                    ocr_progress(i + 1, len(doc))
            texts.append(text)
    finally:
        doc.close()
    return texts, ocr_count


def _find_headings(pages_text, pattern):
    """Returns [(page_num_1indexed, int(group(1)))] for the first match on each page."""
    out = []
    for i, text in enumerate(pages_text):
        m = pattern.search(text)
        if m:
            out.append((i + 1, int(m.group(1))))
    return out


def _find_question_ranges(pages_text):
    """Returns [(page_num_1indexed, start, end)] for every match, page can repeat."""
    out = []
    for i, text in enumerate(pages_text):
        for m in _QUESTIONS_RE.finditer(text):
            out.append((i + 1, int(m.group(1)), int(m.group(2))))
    return out


def _span_pages(start_page, next_boundary_page, last_page):
    end = (next_boundary_page - 1) if next_boundary_page else last_page
    end = max(end, start_page)
    return list(range(start_page, end + 1))


def _question_range_in_span(question_ranges, span_pages):
    """Best-guess question range covering a section's page span: widest [min_start, max_end] found."""
    span_set = set(span_pages)
    hits = [(s, e) for (p, s, e) in question_ranges if p in span_set]
    if not hits:
        return None
    return [min(s for s, _ in hits), max(e for _, e in hits)]


def detect_structure(pdf_path, use_ocr=True, ocr_progress=None):
    """
    Returns:
      {
        "tests": {...},
        "warnings": [str, ...],
        "ocr_pages_used": int,   # how many pages needed OCR fallback (0 = normal text-layer PDF)
        "ocr_available": bool,   # whether pytesseract/Tesseract are installed at all
      }
    All page numbers are 1-indexed, matching main.pdf directly.
    """
    pages_text, ocr_count = _page_texts(pdf_path, use_ocr=use_ocr, ocr_progress=ocr_progress)
    last_page = len(pages_text)
    warnings = []
    if not _OCR_AVAILABLE:
        empty_pages = sum(1 for t in pages_text if len(t.strip()) < _MIN_NATIVE_CHARS)
        if empty_pages > last_page * 0.5:
            warnings.append(
                f"{empty_pages}/{last_page} pages have little or no extractable text -- this looks "
                f"like a scanned PDF with no text layer. Install OCR support to fix detection: "
                f"pip install pytesseract, plus the Tesseract binary itself "
                f"(macOS: brew install tesseract, Ubuntu/Debian: apt install tesseract-ocr)."
            )

    test_headings = _find_headings(pages_text, _TEST_RE)
    if not test_headings:
        # No "Test N" headings found at all -- treat the whole book as one test.
        test_headings = [(1, 1)]
        warnings.append(
            "No 'Test N' heading found anywhere in the PDF -- treating the "
            "entire document as a single 'Test 1'. If your book has multiple "
            "tests, check that each starts with a page whose only text is "
            "e.g. 'Test 2'."
        )

    reading_headings = _find_headings(pages_text, _READING_RE)
    listening_headings = _find_headings(pages_text, _LISTENING_RE)
    writing_headings = _find_headings(pages_text, _WRITING_RE)
    question_ranges = _find_question_ranges(pages_text)

    tests = {}
    for idx, (start_page, test_num) in enumerate(test_headings):
        next_test_page = test_headings[idx + 1][0] if idx + 1 < len(test_headings) else None
        test_end = (next_test_page - 1) if next_test_page else last_page
        test_name = f"Test {test_num}"

        def _within_test(headings):
            return [(p, n) for (p, n) in headings if start_page <= p <= test_end]

        r_heads = sorted(_within_test(reading_headings))
        l_heads = sorted(_within_test(listening_headings))
        w_heads = sorted(_within_test(writing_headings))

        passages = []
        for i, (p, n) in enumerate(r_heads):
            next_p = r_heads[i + 1][0] if i + 1 < len(r_heads) else (
                l_heads[0][0] if l_heads else (w_heads[0][0] if w_heads else None)
            )
            span = _span_pages(p, next_p, test_end)
            qrange = _question_range_in_span(question_ranges, span)
            if qrange is None:
                warnings.append(f"[{test_name}] Reading Passage {n} (page {p}): no 'Questions X-Y' found nearby -- fill in manually.")
            passages.append({"pages": span, "questions": qrange})

        parts = []
        for i, (p, n) in enumerate(l_heads):
            next_p = l_heads[i + 1][0] if i + 1 < len(l_heads) else (
                w_heads[0][0] if w_heads else None
            )
            span = _span_pages(p, next_p, test_end)
            qrange = _question_range_in_span(question_ranges, span)
            if qrange is None:
                warnings.append(f"[{test_name}] Listening Section {n} (page {p}): no 'Questions X-Y' found nearby -- fill in manually.")
            parts.append({"pages": span, "questions": qrange})

        writing = {}
        for p, n in w_heads:
            if n in (1, 2):
                writing[f"task{n}"] = {"page": p}

        if not r_heads:
            warnings.append(f"[{test_name}]: no 'READING PASSAGE N' headings found.")
        if not l_heads:
            warnings.append(f"[{test_name}]: no 'SECTION N' (listening) headings found.")
        if not w_heads:
            warnings.append(f"[{test_name}]: no 'WRITING TASK N' headings found.")

        tests[test_name] = {
            "reading_passages": passages,
            "listening_parts": parts,
            "writing": writing,
        }

    return {
        "tests": tests,
        "warnings": warnings,
        "ocr_pages_used": ocr_count,
        "ocr_available": _OCR_AVAILABLE,
    }
