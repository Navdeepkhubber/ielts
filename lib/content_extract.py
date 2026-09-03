"""Layout-faithful PDF extraction for the IELTS text view.

The old extractor converted PDF text into prose. This module deliberately does
not do that. It keeps the PDF's page geometry and text spans, so the browser can
recreate the printed page as HTML: headings stay where they are, tables retain
rows/columns, and multi-column question sheets don't collapse into a text wall.
"""
import json
import os
import re

import fitz

SCHEMA_VERSION = 3

_BRAND_RE = re.compile(r"(?:keenielts\\.com|Practice smarter\\.\\s*Score higher)", re.I)
_SECTION_HEADER_RE = re.compile(r"^(?:Test\\s+\\d+|Listening|Reading|Writing|Academic Reading)\\s*$", re.I)
_PAGE_NUMBER_RE = re.compile(r"^\\s*\\d{1,3}\\s*$")
_GAP_RE = re.compile(r"^\\s*(\\d{1,2})\\s*(?:[.…·]{3,}|_{3,})\\s*$")
_INLINE_GAP_RE = re.compile(r"\\b(\\d{1,2})\\s*(?:[.…·]{3,}|_{3,})")


def _norm(text):
    return re.sub(r"\\s+", " ", text or "").strip()


def _is_noise(span, page):
    text = _norm(span.get("text", ""))
    if not text:
        return True
    if _BRAND_RE.search(text) or _SECTION_HEADER_RE.match(text):
        return True
    y0 = span["bbox"][1]
    if y0 > page.rect.height * 0.93 and _PAGE_NUMBER_RE.match(text):
        return True
    return False


def _font_style(span):
    flags = int(span.get("flags", 0))
    font = (span.get("font") or "").lower()
    bold = bool(flags & 16) or "bold" in font or "semibold" in font or "heavy" in font
    italic = bool(flags & 2) or "italic" in font or "oblique" in font
    return bold, italic


def _span_payload(span):
    bold, italic = _font_style(span)
    return {
        "bbox": [round(v, 2) for v in span["bbox"]],
        "text": span.get("text", ""),
        "size": round(float(span.get("size", 10)), 2),
        "font": span.get("font"),
        "bold": bold,
        "italic": italic,
        "color": int(span.get("color", 0)),
    }


def _extract_page(page, page_number, q_from=None, q_to=None):
    data = page.get_text("dict")
    spans = []
    answer_boxes = []
    for block in data.get("blocks", []):
        if "lines" not in block:
            continue
        for line in block.get("lines", []):
            for raw in line.get("spans", []):
                if _is_noise(raw, page):
                    continue
                payload = _span_payload(raw)
                spans.append(payload)
                text = payload["text"]
                m = _GAP_RE.match(text)
                if m:
                    q = int(m.group(1))
                    if (q_from is None or q >= q_from) and (q_to is None or q <= q_to):
                        answer_boxes.append({"question": q, "bbox": payload["bbox"], "mode": "replace_gap"})
                else:
                    for match in _INLINE_GAP_RE.finditer(text):
                        q = int(match.group(1))
                        if (q_from is None or q >= q_from) and (q_to is None or q <= q_to):
                            answer_boxes.append({"question": q, "bbox": payload["bbox"], "mode": "inline_gap"})
    return {"page": page_number, "width": round(page.rect.width, 2), "height": round(page.rect.height, 2), "spans": spans, "answer_boxes": answer_boxes}


def _page_numbers_for_test(test_cfg):
    reading = []
    for passage in test_cfg.get("reading", {}).get("passages", []):
        reading.extend((p, passage["questions"]) for p in passage.get("pages", []))
    listening = []
    for part in test_cfg.get("listening", {}).get("parts", []):
        listening.extend((p, part["questions"]) for p in part.get("pages", []))
    writing = []
    for task in ("task1", "task2"):
        if test_cfg.get("writing", {}).get(task, {}).get("page"):
            writing.append((test_cfg["writing"][task]["page"], None))
    return reading, listening, writing


def _build_pages(pdf_path, refs):
    document = fitz.open(pdf_path)
    try:
        pages = []
        seen = set()
        for page_number, qrange in refs:
            if page_number in seen or not 1 <= page_number <= len(document):
                continue
            seen.add(page_number)
            pages.append(_extract_page(document[page_number - 1], page_number, *(qrange or (None, None))))
        pages.sort(key=lambda p: p["page"])
        return pages
    finally:
        document.close()


def build_content_for_test(pages_text, test_cfg, pdf_path=None):
    """Return a layout document. `pages_text` remains accepted for scaffold API compatibility."""
    if not pdf_path:
        raise ValueError("pdf_path is required for layout extraction")
    reading_refs, listening_refs, writing_refs = _page_numbers_for_test(test_cfg)
    return {
        "schema_version": SCHEMA_VERSION,
        "renderer": "pdf-layout-html",
        "reading": {"pages": _build_pages(pdf_path, reading_refs)},
        "listening": {"pages": _build_pages(pdf_path, listening_refs)},
        "writing": {"pages": _build_pages(pdf_path, writing_refs)},
    }


def scaffold_content_files(mock_dir, manifest, pages_text, log, mock_name):
    os.makedirs(os.path.join(mock_dir, "content"), exist_ok=True)
    for test_name, test_cfg in manifest.get("tests", {}).items():
        out_path = os.path.join(mock_dir, "content", f"{test_name}.json")
        try:
            pdf_file = manifest.get("pdf_file", "main.pdf")
            pdf_path = os.path.join(mock_dir, pdf_file)
            if not os.path.isfile(pdf_path):
                log.append(f"[{mock_name}/{test_name}] layout extraction skipped: {pdf_file} missing")
                continue
            content = build_content_for_test(pages_text, test_cfg, pdf_path=pdf_path)
            existing_version = None
            if os.path.isfile(out_path):
                try:
                    with open(out_path, encoding="utf-8") as f:
                        existing_version = json.load(f).get("schema_version")
                except (OSError, ValueError):
                    pass
            if existing_version != SCHEMA_VERSION:
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(content, f, ensure_ascii=False, separators=(",", ":"))
                log.append(f"[{mock_name}/{test_name}] generated layout-faithful content/{test_name}.json (schema {SCHEMA_VERSION})")
            else:
                log.append(f"[{mock_name}/{test_name}] layout content already current")
        except Exception as exc:
            log.append(f"[{mock_name}/{test_name}] layout extraction failed: {exc}")
