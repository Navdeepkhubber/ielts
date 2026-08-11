"""Structured text extraction for IELTS reading/listening content.

Keeps the existing `text` field for backwards compatibility while adding
`blocks`, `questions`, and QA metadata. Question boundaries are constrained
by the manifest question range, but scanned/multi-column PDF layouts are
handled with a dedicated OCR pass when the native PDF text is incomplete.
"""
import io
import json
import os
import re

_NOISE_RES = [
    re.compile(r"^\s*Test\s+\d+\s*$", re.IGNORECASE),
    re.compile(r"^\s*(LISTENING|READING|WRITING|ACADEMIC READING)\s*$", re.IGNORECASE),
    re.compile(r"^\s*@\w+\s*$"),
    re.compile(r"^\s*[|>_\-~•·=]{1,4}\s*$"),
    re.compile(r"^\s*IELTS\s+\d+\s*$", re.IGNORECASE),
]
_HEADING_LIKE_RES = [
    re.compile(r"^\s*[QO]uestions?\s+\d+.*$", re.IGNORECASE),
    re.compile(r"^\s*READING PASSAGE\s+\d+.*$", re.IGNORECASE),
    re.compile(r"^\s*(?:SECTION|PART)\s+\d+\s*$", re.IGNORECASE),
    re.compile(r"^\s*[A-H]\s*$"),
    re.compile(r"^\s*[A-Z][A-Z\s'.,\-]{3,60}$"),
    re.compile(r"^\s*Complete the .{3,80}$", re.IGNORECASE),
    re.compile(r"^\s*Choose .{3,80}$", re.IGNORECASE),
    re.compile(r"^\s*Write (?:ONE|NO MORE|TRUE|FALSE) .{0,80}$", re.IGNORECASE),
]
_GAP_RE = re.compile(r"\d{1,2}\s*(?:[.…·]{3,}|_{3,})")
_QUESTION_START_RE = re.compile(r"^\s*(\d{1,2})(?:\s*[.)/:]\s*(.*)|\s+(.+?))\s*$")
_LONE_QUESTION_NUMBER_RE = re.compile(r"^\s*(\d{1,2})\s*$")
_EMBEDDED_QUESTION_RE = re.compile(r"(?:^|\s)[\[(]?(\d{1,2})[\])\.]?(?=\s|$)")


def _is_heading_like(line):
    return any(rx.match(line) for rx in _HEADING_LIKE_RES)


def _question_start(line, q_from, q_to):
    if not q_range_valid(q_from, q_to):
        return None
    m = _QUESTION_START_RE.match(line)
    if m:
        q = int(m.group(1))
        if q_from <= q <= q_to:
            return q
    m = _LONE_QUESTION_NUMBER_RE.match(line)
    if m:
        q = int(m.group(1))
        if q_from <= q <= q_to:
            return q
    for m in _EMBEDDED_QUESTION_RE.finditer(line):
        q = int(m.group(1))
        if q_from <= q <= q_to:
            prefix = line[:m.start(1)].strip()
            if not prefix or len(prefix) <= 4:
                return q
    return None


def q_range_valid(q_from, q_to):
    return isinstance(q_from, int) and isinstance(q_to, int) and q_from <= q_to


def _clean_lines(text):
    return [
        line
        for raw in text.splitlines()
        for line in [raw.rstrip()]
        if not any(rx.match(line) for rx in _NOISE_RES)
    ]


def _reflow(lines, mode):
    if mode == "list":
        return [ln.strip() for ln in lines if ln.strip()]
    blocks, buf = [], []

    def flush():
        if not buf:
            return
        text = ""
        for ln in buf:
            if text.endswith("-") and len(text) > 1 and text[-2].isalpha():
                text = text[:-1] + ln
            elif text:
                text += " " + ln
            else:
                text = ln
        blocks.append(text.strip())
        buf.clear()

    for raw in lines:
        line = raw.strip()
        if not line:
            flush()
            continue
        if _is_heading_like(line) or _GAP_RE.search(line):
            flush()
            blocks.append(line)
        else:
            buf.append(line)
    flush()
    return [b for b in blocks if b]


def _normalise_question(lines, mode):
    return "\n".join(x.strip() for x in lines if x.strip()) if mode == "list" else "\n\n".join(_reflow(lines, "prose"))


def _extract_page(lines, q_range, mode, page):
    prose_lines, prose_blocks, questions, current = [], [], [], None

    def flush_question():
        nonlocal current
        if not current:
            return
        text = _normalise_question(current["lines"], mode)
        if text:
            questions.append({"page": page, "question": current["question"], "text": text})
        current = None

    def flush_prose():
        if not prose_lines:
            return
        prose_blocks.extend(_reflow(prose_lines, mode))
        prose_lines.clear()

    for raw in lines:
        line = raw.strip()
        if not line:
            if current:
                current["lines"].append("")
            else:
                flush_prose()
            continue
        q = _question_start(line, q_range[0], q_range[1]) if q_range else None
        if q is not None:
            flush_prose()
            flush_question()
            current = {"question": q, "lines": [line]}
            continue
        if current:
            current["lines"].append(line)
        else:
            prose_lines.append(line)

    flush_question()
    flush_prose()
    return prose_blocks, questions


def _expected_questions(q_range):
    if not q_range or len(q_range) != 2:
        return []
    try:
        start, end = int(q_range[0]), int(q_range[1])
    except (TypeError, ValueError):
        return []
    return list(range(start, end + 1)) if start <= end else []


def _qa_for_section(q_range, questions):
    expected = _expected_questions(q_range)
    detected = [q["question"] for q in questions]
    seen = set()
    duplicates = []
    for n in detected:
        if n in seen:
            duplicates.append(n)
        seen.add(n)
    missing = [n for n in expected if n not in seen]
    unexpected = [n for n in detected if n not in set(expected)]
    ordered = detected == sorted(detected) and len(detected) == len(set(detected))
    return {
        "expected_count": len(expected),
        "detected_count": len(detected),
        "expected_questions": expected,
        "detected_questions": detected,
        "missing_questions": missing,
        "duplicate_questions": duplicates,
        "unexpected_questions": unexpected,
        "ordered": ordered,
        "ok": bool(expected) and len(detected) == len(expected) and not missing and not duplicates and not unexpected and ordered,
    }


def _preprocess_for_ocr(image):
    from PIL import ImageOps, ImageFilter
    image = ImageOps.grayscale(image)
    image = ImageOps.autocontrast(image)
    return image.filter(ImageFilter.SHARPEN)


def _ocr_page_variants(pdf_path, page_number):
    """Run several OCR layouts, including left/right crops for two-column pages."""
    try:
        import fitz
        import pytesseract
        from PIL import Image
    except ImportError:
        return []

    texts = []
    try:
        doc = fitz.open(pdf_path)
        try:
            page = doc[page_number - 1]
            pix = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), colorspace=fitz.csGRAY, alpha=False)
            image = _preprocess_for_ocr(Image.open(io.BytesIO(pix.tobytes("png"))))
            os.environ.setdefault("OMP_THREAD_LIMIT", "1")

            # Whole-page modes. PSM 3 lets Tesseract infer columns; 6 assumes
            # one uniform block; 11 handles sparse question sheets.
            for psm in (3, 6, 11):
                texts.append(pytesseract.image_to_string(image, config=f"--oem 3 --psm {psm}"))

            # Many Cambridge pages use two visual columns. OCR each column
            # independently so the question number and its text stay in the
            # same reading region instead of being interleaved by Tesseract.
            width, height = image.size
            overlap = max(20, int(width * 0.025))
            mid = width // 2
            crops = [
                image.crop((0, 0, min(width, mid + overlap), height)),
                image.crop((max(0, mid - overlap), 0, width, height)),
            ]
            for crop in crops:
                for psm in (6, 11):
                    texts.append(pytesseract.image_to_string(crop, config=f"--oem 3 --psm {psm}"))
        finally:
            doc.close()
    except Exception:
        return []
    return texts


def _section_content(pages_text, pages, mode, q_range, pdf_path=None):
    prose_blocks, questions = [], []
    for p in pages:
        if not 1 <= p <= len(pages_text):
            continue
        native_lines = _clean_lines(pages_text[p - 1])
        page_prose, page_questions = _extract_page(native_lines, q_range, mode, p)
        prose_blocks.extend({"type": "text", "page": p, "text": x} for x in page_prose if x)
        questions.extend(page_questions)

    if not _qa_for_section(q_range, questions)["ok"] and pdf_path:
        for p in pages:
            for ocr_text in _ocr_page_variants(pdf_path, p):
                ocr_lines = _clean_lines(ocr_text)
                _, ocr_questions = _extract_page(ocr_lines, q_range, mode, p)
                questions.extend(ocr_questions)

    by_question = {}
    for q in questions:
        n = q["question"]
        existing = by_question.get(n)
        if existing is None or len(q.get("text", "")) > len(existing.get("text", "")):
            by_question[n] = q
    unique_questions = [by_question[n] for n in sorted(by_question)]
    qa = _qa_for_section(q_range, unique_questions)

    return {
        "text": "\n\n".join(x["text"] for x in prose_blocks + [{"text": q["text"]} for q in unique_questions]),
        "blocks": prose_blocks,
        "questions": unique_questions,
        "question_range": list(q_range) if q_range else None,
        "qa": qa,
    }


def build_content_for_test(pages_text, test_cfg, pdf_path=None):
    content = {"schema_version": 3}
    listening = test_cfg.get("listening", {})
    parts, any_listening = [], False
    for part in listening.get("parts", []):
        pages = part.get("pages") or []
        section = _section_content(pages_text, pages, "list", part.get("questions"), pdf_path=pdf_path)
        any_listening = any_listening or bool(section["text"])
        parts.append(section)
    if any_listening:
        content["listening"] = {"parts": parts}

    reading = test_cfg.get("reading", {})
    passages, any_reading = [], False
    for passage in reading.get("passages", []):
        pages = passage.get("pages") or []
        section = _section_content(pages_text, pages, "prose", passage.get("questions"), pdf_path=pdf_path)
        any_reading = any_reading or bool(section["text"])
        passages.append(section)
    if any_reading:
        content["reading"] = {"passages": passages}
    return content


def scaffold_content_files(mock_dir, manifest, pages_text, log, mock_name, force=False):
    for test_name, cfg in manifest.get("tests", {}).items():
        out_dir = os.path.join(mock_dir, "content")
        out_path = os.path.join(out_dir, f"{test_name}.json")
        if os.path.isfile(out_path) and not force:
            continue
        content = build_content_for_test(pages_text, cfg, pdf_path=os.path.join(mock_dir, manifest.get("pdf_file", "main.pdf")))
        if not any(k in content for k in ("reading", "listening")):
            continue
        os.makedirs(out_dir, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(content, f, indent=2, ensure_ascii=False)
        sections = []
        for kind, key in (("reading", "passages"), ("listening", "parts")):
            for i, section in enumerate(content.get(kind, {}).get(key, []), 1):
                qa = section.get("qa", {})
                sections.append(f"{kind.title()} {i}: {qa.get('detected_count', 0)}/{qa.get('expected_count', 0)}")
        log.append(f"[{mock_name}/{test_name}] extracted {' + '.join(sections) or 'no sections'}.")