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
import json
import os
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
# Listening: books printed before 2020 say "SECTION N"; from Cambridge 15
# onward they say "PART N" (IELTS renamed listening sections to parts).
# Line-anchored because "part 2" appears constantly in ordinary passage
# prose. Two printed forms exist: the heading alone ("PART 1") or with the
# question range on the same line ("PART 1 Questions 1-10", Cambridge 19+).
_LISTENING_RE = re.compile(
    r"^\s*(?:SECTION|PART)\s+(\d+)\s*(?:[QO]uestions?\s+\d+\s*[-–—~]\s*\d+)?\s*\.?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_WRITING_RE = re.compile(r"WRITING\s+TASK\s+(\d+)", re.IGNORECASE)
# OCR sometimes misreads Q as O ("Ouestions"); allow both.
_QUESTIONS_RE = re.compile(r"[QO]uestions?\s+(\d+)\s*[-–—~]\s*(\d+)", re.IGNORECASE)
# Sample writing answers in the back of the book: "TEST 2, WRITING TASK 1"
_SAMPLE_WRITING_RE = re.compile(r"^\s*TEST\s+(\d+)\s*,\s*WRITING\s+TASK\s+(\d+)", re.IGNORECASE | re.MULTILINE)
_SAMPLE_SECTION_END_RE = re.compile(r"sample\s+answer\s+sheets", re.IGNORECASE)
# Cambridge back-matter: tapescripts and answer keys repeat "Test N",
# "SECTION N", "Questions X-Y" etc. -- everything from the first such page
# onward must be excluded from structure detection.
_BACKMATTER_RE = re.compile(
    r"\btapescripts?\b|\baudioscripts?\b|\banswer\s+keys?\b|\blistening\s+and\s+reading\s+answer",
    re.IGNORECASE,
)


def _ocr_page_text(page, zoom=1.7):
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csGRAY)
    img = Image.open(_io.BytesIO(pix.tobytes("png")))
    return pytesseract.image_to_string(img)


def _ocr_page_worker(args):
    """Module-level worker for multiprocessing: opens the doc per process."""
    pdf_path, page_index, zoom = args
    # Each worker process handles one page at a time; stop tesseract from
    # ALSO spawning its own internal threads, which makes N workers fight
    # over the same cores and go slower than serial.
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")
    doc = fitz.open(pdf_path)
    try:
        pix = doc[page_index].get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csGRAY)
        img = Image.open(_io.BytesIO(pix.tobytes("png")))
        return page_index, pytesseract.image_to_string(img)
    finally:
        doc.close()


def _cache_path(pdf_path):
    """Cache file sits next to the PDF: .pdf_text_cache.json keyed by size+mtime."""
    return os.path.join(os.path.dirname(pdf_path), ".pdf_text_cache.json")


def _cache_key(pdf_path):
    st = os.stat(pdf_path)
    return f"{os.path.basename(pdf_path)}:{st.st_size}:{int(st.st_mtime)}"


def _load_cached_texts(pdf_path):
    try:
        with open(_cache_path(pdf_path)) as f:
            cache = json.load(f)
        if cache.get("key") == _cache_key(pdf_path):
            return cache["texts"], cache.get("ocr_pages_used", 0)
    except (OSError, ValueError, KeyError):
        pass
    return None, 0


def _save_cached_texts(pdf_path, texts, ocr_count):
    try:
        with open(_cache_path(pdf_path), "w") as f:
            json.dump({"key": _cache_key(pdf_path), "texts": texts, "ocr_pages_used": ocr_count}, f)
    except OSError:
        pass  # cache is best-effort; never fail the scan over it


def _page_texts(pdf_path, use_ocr=True, ocr_progress=None):
    """
    Returns (texts, ocr_page_count). Falls back to OCR when the native text
    layer is empty/near-empty (scanned PDFs). Results are cached on disk next
    to the PDF (invalidated automatically if the PDF changes), so the slow
    OCR pass only ever happens once per book. OCR runs in parallel across
    CPU cores.
    """
    cached, cached_ocr = _load_cached_texts(pdf_path)
    if cached is not None:
        return cached, 0  # 0 = no OCR performed *this run*; it came from cache

    doc = fitz.open(pdf_path)
    try:
        texts = [doc[i].get_text() for i in range(len(doc))]
    finally:
        doc.close()

    needs_ocr = [i for i, t in enumerate(texts) if len(t.strip()) < _MIN_NATIVE_CHARS]
    ocr_count = 0
    if needs_ocr and use_ocr and _OCR_AVAILABLE:
        total = len(needs_ocr)
        zoom = 1.7  # lower render scale = faster OCR; headings are large text and survive this fine
        try:
            import multiprocessing as mp
            workers = max(1, min(mp.cpu_count() - 1, 8))
            with mp.Pool(workers) as pool:
                done = 0
                for page_index, text in pool.imap_unordered(
                    _ocr_page_worker, [(pdf_path, i, zoom) for i in needs_ocr]
                ):
                    texts[page_index] = text
                    done += 1
                    ocr_count += 1
                    if ocr_progress:
                        ocr_progress(done, total)
        except Exception as e:
            # Parallel OCR can fail in odd environments -- fall back to serial,
            # but say so loudly, because serial is several times slower.
            print(f"[pdf_structure] WARNING: parallel OCR failed ({e!r}); falling back to slow serial OCR.")
            doc = fitz.open(pdf_path)
            try:
                for done, i in enumerate(needs_ocr, 1):
                    texts[i] = _ocr_page_text(doc[i], zoom)
                    ocr_count += 1
                    if ocr_progress:
                        ocr_progress(done, total)
            finally:
                doc.close()

    _save_cached_texts(pdf_path, texts, ocr_count)
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


def _find_sample_writing_pages(pages_text):
    """
    Locate the "Sample Writing answers" pages at the back of the book.
    Returns {(test_num, task_num): [pages]} where each entry spans from its
    "TEST N, WRITING TASK M" heading up to the next heading (or the sample
    answer sheets section). These are model candidate answers with examiner
    band comments -- gold for studying writing.
    """
    marks = []  # (page_1indexed, test, task)
    end_page = len(pages_text)
    for i, text in enumerate(pages_text):
        m = _SAMPLE_WRITING_RE.search(text)
        if m:
            marks.append((i + 1, int(m.group(1)), int(m.group(2))))
        elif marks and _SAMPLE_SECTION_END_RE.search(text[:400]):
            end_page = i  # sample section over
            break
    out = {}
    for idx, (page, test, task) in enumerate(marks):
        nxt = marks[idx + 1][0] if idx + 1 < len(marks) else end_page + 1
        out[(test, task)] = list(range(page, max(page, nxt - 1) + 1))
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

    # --- Exclude back-matter (tapescripts / answer keys) ---
    # Cambridge books repeat "Test N", "SECTION N", "Questions X-Y" inside
    # tapescripts and answer keys at the back; structural headings found
    # there are false positives. Cut everything from the first back-matter
    # page onward. Only look for the marker after ~40% of the book so a
    # stray front-matter mention can't truncate the whole scan.
    backmatter_start = None
    for i in range(int(last_page * 0.4), last_page):
        if _BACKMATTER_RE.search(pages_text[i]):
            backmatter_start = i + 1  # 1-indexed page number
            break
    scan_end = (backmatter_start - 1) if backmatter_start else last_page
    scannable = pages_text[:scan_end]
    if backmatter_start:
        warnings.append(
            f"Detected tapescripts/answer-key back-matter starting around page "
            f"{backmatter_start}; pages from there on are excluded from structure detection."
        )

    test_headings = _find_headings(scannable, _TEST_RE)
    # Cambridge prints "Test N" as a running header on EVERY page of a test,
    # so collapse consecutive same-number matches into a single boundary:
    # a new test starts only where the test number changes.
    collapsed = []
    for page, n in test_headings:
        if not collapsed or collapsed[-1][1] != n:
            collapsed.append((page, n))
    test_headings = collapsed
    if not test_headings:
        # No "Test N" headings found at all -- treat the whole book as one test.
        test_headings = [(1, 1)]
        warnings.append(
            "No 'Test N' heading found anywhere in the PDF -- treating the "
            "entire document as a single 'Test 1'. If your book has multiple "
            "tests, check that each starts with a page whose only text is "
            "e.g. 'Test 2'."
        )

    reading_headings = _find_headings(scannable, _READING_RE)
    listening_headings = _find_headings(scannable, _LISTENING_RE)
    writing_headings = _find_headings(scannable, _WRITING_RE)
    question_ranges = _find_question_ranges(scannable)
    last_page = scan_end  # spans must not extend into back-matter
    # Sample writing answers live IN the back-matter, so scan the full text.
    sample_writing_pages = _find_sample_writing_pages(pages_text)

    def _collapse_runs(headings):
        """Keep only the first page of each consecutive run of the same
        number -- section headings repeat on every page they span."""
        out = []
        for page, n in headings:
            if not out or out[-1][1] != n:
                out.append((page, n))
        return out

    tests = {}
    for idx, (start_page, test_num) in enumerate(test_headings):
        next_test_page = test_headings[idx + 1][0] if idx + 1 < len(test_headings) else None
        test_end = (next_test_page - 1) if next_test_page else last_page
        test_name = f"Test {test_num}"
        if test_name in tests:
            warnings.append(
                f"'{test_name}' heading appears again at page {start_page} after other tests -- "
                f"ignoring the repeat (likely OCR noise or an unusual layout)."
            )
            continue

        def _within_test(headings):
            return [(p, n) for (p, n) in headings if start_page <= p <= test_end]

        r_heads = _collapse_runs(sorted(_within_test(reading_headings)))
        l_heads = _collapse_runs(sorted(_within_test(listening_headings)))
        w_heads = _collapse_runs(sorted(_within_test(writing_headings)))

        # Cambridge order within a test is always Listening -> Reading ->
        # Writing. "PART N" lines that appear after reading has started
        # (divider pages, track listings, answer sheets) are false
        # positives -- drop any listening heading at or beyond the first
        # reading/writing page.
        first_r = r_heads[0][0] if r_heads else None
        first_w = w_heads[0][0] if w_heads else None
        listening_cutoff = min(x for x in (first_r, first_w, test_end + 1) if x is not None)
        l_heads = [(p, n) for (p, n) in l_heads if p < listening_cutoff]

        def _first_after(page, *heading_lists):
            candidates = [p for heads in heading_lists for (p, _n) in heads if p > page]
            return min(candidates) if candidates else None

        passages = []
        for i, (p, n) in enumerate(r_heads):
            next_p = _first_after(p, r_heads, w_heads)
            span = _span_pages(p, next_p, test_end)
            qrange = _question_range_in_span(question_ranges, span)
            if qrange is None:
                warnings.append(f"[{test_name}] Reading Passage {n} (page {p}): no 'Questions X-Y' found nearby -- fill in manually.")
            passages.append({"pages": span, "questions": qrange})

        # Academic reading is nearly always 1-13 / 14-26 / 27-40; use it as a
        # fallback for exactly-3-passage tests where a range wasn't found.
        if len(passages) == 3:
            _CANON_READING = [[1, 13], [14, 26], [27, 40]]
            for i, passage in enumerate(passages):
                if passage["questions"] is None:
                    passage["questions"] = _CANON_READING[i]
                    warnings.append(
                        f"[{test_name}] Reading Passage {i + 1}: assumed standard questions "
                        f"{_CANON_READING[i][0]}-{_CANON_READING[i][1]} -- verify against the PDF."
                    )

        parts = []
        for i, (p, n) in enumerate(l_heads):
            next_p = _first_after(p, l_heads, r_heads, w_heads)
            span = _span_pages(p, next_p, test_end)
            # IELTS listening is invariant: 4 parts, exactly 10 questions
            # each (1-10 / 11-20 / 21-30 / 31-40). Extraction of the
            # "Questions X-Y" line is flaky (e.g. "1-10" reads as "1-1"),
            # so canonicalize by part position rather than trusting it.
            canonical = [i * 10 + 1, i * 10 + 10]
            detected = _question_range_in_span(question_ranges, span)
            if detected is not None and detected != canonical:
                warnings.append(
                    f"[{test_name}] Listening Part {i + 1} (page {p}): detected questions "
                    f"{detected[0]}-{detected[1]} but IELTS listening parts are always 10 "
                    f"questions -- using {canonical[0]}-{canonical[1]}."
                )
            parts.append({"pages": span, "questions": canonical})
        if parts and len(parts) != 4:
            warnings.append(
                f"[{test_name}]: found {len(parts)} listening part heading(s) instead of the "
                f"expected 4 -- double-check the listening pages in the generated manifest."
            )

        writing = {}
        for p, n in w_heads:
            if n in (1, 2):
                writing[f"task{n}"] = {"page": p}
                sample = sample_writing_pages.get((test_num, n))
                if sample:
                    writing[f"task{n}"]["sample_pages"] = sample

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

    seen = set()
    deduped_warnings = [w for w in warnings if not (w in seen or seen.add(w))]
    return {
        "tests": tests,
        "warnings": deduped_warnings,
        "ocr_pages_used": ocr_count,
        "ocr_available": _OCR_AVAILABLE,
    }
