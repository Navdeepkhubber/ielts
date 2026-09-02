"""
Extracts the actual text of each test section (listening question sheets,
reading passages + questions) from the book PDF into a local content.json
per test, so the portal can render selectable, properly typeset text with
inline answer boxes instead of page images.

This is for a PRIVATE, LOCAL study portal working on the user's own copy
of the book -- the extracted text lives only in the local mock folder,
next to the PDF it came from.

Text is cleaned of page furniture: running headers ("Test 1", section
names), lone page numbers, and scan watermarks. The original page images
remain available in the UI ("Book view") since diagrams/maps don't
survive text extraction and OCR text from scanned books has errors.

Files are never overwritten once created, so hand-corrections to OCR
typos are safe.
"""
import json
import os
import re

_NOISE_RES = [
    re.compile(r"^\s*Test\s+\d+\s*$", re.IGNORECASE),           # running header
    re.compile(r"^\s*(LISTENING|READING|WRITING|ACADEMIC READING)\s*$", re.IGNORECASE),
    re.compile(r"^\s*\d{1,3}\s*$"),                              # lone page number
    re.compile(r"^\s*@\w+\s*$"),                                 # scan watermark handles
    re.compile(r"^\s*[|>_\-~•·=]{1,4}\s*$"),                     # OCR artifacts
    re.compile(r"^\s*IELTS\s+\d+\s*$", re.IGNORECASE),
]

# Lines that are structural on their own (never merged into flowing prose):
_HEADING_LIKE_RES = [
    re.compile(r"^\s*[QO]uestions?\s+\d+.*$", re.IGNORECASE),               # "Questions 1-10"
    re.compile(r"^\s*READING PASSAGE\s+\d+.*$", re.IGNORECASE),
    re.compile(r"^\s*(?:SECTION|PART)\s+\d+\s*$", re.IGNORECASE),
    re.compile(r"^\s*[A-H]\s*$"),                                            # lone paragraph-letter marker (A, B, C...)
    re.compile(r"^\s*[A-Z][A-Z\s'.,\-]{3,60}$"),                             # short ALL-CAPS instruction line
    re.compile(r"^\s*Complete the .{3,60}$", re.IGNORECASE),
    re.compile(r"^\s*Choose .{3,60}$", re.IGNORECASE),
    re.compile(r"^\s*Write (?:ONE|NO MORE|TRUE|FALSE) .{0,60}$", re.IGNORECASE),
    re.compile(r"^\s*\d{1,2}[.)]\s+\S.*$"),                                  # numbered list item "1. ..." / "1) ..."
]


_GAP_RE = re.compile(r"\d{1,2}\s*(?:[.…·]{3,}|_{3,})")
_QUESTION_GROUP_RE = re.compile(
    r"^\s*Questions?\s+(\d{1,2})\s*(?:[-–—~]|to|and)\s*(\d{1,2})\b.*$",
    re.IGNORECASE,
)
_QUESTION_ITEM_RE = re.compile(r"(?:^|\s)(\d{1,2})[.)]\s+(.*?)(?=\s+\d{1,2}[.)]\s+|$)")
_ANSWER_RULES = (
    (re.compile(r"choose\s+(?:two|three|four|five|six|seven|eight|nine|ten)", re.IGNORECASE), "multi_choice"),
    (re.compile(r"choose\s+(?:the\s+)?correct\s+letter", re.IGNORECASE), "single_choice"),
    (re.compile(r"true.*false.*not\s+given", re.IGNORECASE | re.DOTALL), "true_false_not_given"),
    (re.compile(r"match", re.IGNORECASE), "matching"),
    (re.compile(r"complete|write", re.IGNORECASE), "text"),
)


def _is_heading_like(line):
    return any(rx.match(line) for rx in _HEADING_LIKE_RES)


def _reflow_paragraphs(lines, mode):
    """
    mode="prose": merges printed-line-wrap fragments into flowing
    paragraphs (reading passages) -- everything not heading-like or
    gapped gets joined, since real prose has no reason to break lines
    except where the PDF happened to wrap them.

    mode="list": listening question sheets (notes/table/summary
    completion, matching, multiple choice) are inherently structured --
    each printed line is already a complete bullet/field, not a wrapped
    sentence fragment. Merging them produces an unreadable wall of text,
    so list mode keeps one line per block and only strips noise.

    Both modes handle hyphenated line-end word breaks when merging
    ("environ-" + "ment" -> "environment").
    """
    if mode == "list":
        return [ln.strip() for ln in lines if ln.strip()]

    blocks = []
    buf = []

    def flush():
        if not buf:
            return
        text = ""
        for ln in buf:
            if text.endswith("-") and text[:-1] and text[-2:-1].isalpha():
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
            continue
        buf.append(line)
    flush()
    return [b for b in blocks if b]


def _clean_page_text(text, mode="prose"):
    lines = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if any(rx.match(line) for rx in _NOISE_RES):
            continue
        lines.append(line)
    paragraphs = _reflow_paragraphs(lines, mode)
    return "\n\n".join(paragraphs)


def _native_page_texts(pdf_path, page_numbers):
    """Read native PDF blocks in visual order, preserving layout boundaries."""
    import fitz

    document = fitz.open(pdf_path)
    try:
        output = []
        for page_number in page_numbers:
            if not 1 <= page_number <= len(document):
                continue
            blocks = document[page_number - 1].get_text("blocks", sort=True)
            output.append("\n".join(block[4].rstrip() for block in blocks if block[4].strip()))
        return output
    finally:
        document.close()


def _native_page_layout(pdf_path, page_numbers):
    """Return native spans with page coordinates and visual metadata."""
    import fitz

    document = fitz.open(pdf_path)
    try:
        layout = []
        for page_number in page_numbers:
            if not 1 <= page_number <= len(document):
                continue
            for block in document[page_number - 1].get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        if span.get("text", "").strip():
                            layout.append({
                                "page": page_number,
                                "bbox": [round(value, 2) for value in span["bbox"]],
                                "text": span["text"],
                                "font": span.get("font"),
                                "size": round(span.get("size", 0), 2),
                                "color": span.get("color", 0),
                                "flags": span.get("flags", 0),
                            })
        return layout
    finally:
        document.close()


def _pages_to_text(pages_text, page_numbers, mode="prose", pdf_path=None):
    """page_numbers are 1-indexed. mode: "prose" (reading) or "list" (listening)."""
    chunks = []
    native_texts = _native_page_texts(pdf_path, page_numbers) if pdf_path else None
    for index, p in enumerate(page_numbers):
        if 1 <= p <= len(pages_text):
            source = native_texts[index] if native_texts is not None else pages_text[p - 1]
            t = _clean_page_text(source, mode=mode)
            if t:
                chunks.append(t)
    return "\n\n".join(chunks)


def _answer_type(instruction):
    for pattern, answer_type in _ANSWER_RULES:
        if pattern.search(instruction):
            return answer_type
    return "unknown"


def _question_numbers(start, end):
    return list(range(start, end + 1))


def _structured_question_groups(text, question_range=None):
    """Parse question groups while retaining raw text when PDF order is imperfect."""
    lines = text.splitlines()
    groups = []
    current = None
    for line in lines:
        match = _QUESTION_GROUP_RE.match(line.strip())
        if match:
            if current:
                groups.append(current)
            start, end = int(match.group(1)), int(match.group(2))
            current = {
                "questions": [start, end],
                "instruction": "",
                "answer_type": "unknown",
                "items": [],
                "text": line.strip(),
            }
            continue
        if current is None:
            continue
        current["text"] += "\n" + line
        stripped = line.strip()
        if not current["instruction"] and stripped and not re.match(r"^\d{1,2}[.)]", stripped):
            current["instruction"] = stripped
        for item in _QUESTION_ITEM_RE.finditer(line):
            number = int(item.group(1))
            if current["questions"][0] <= number <= current["questions"][1]:
                current["items"].append({
                    "number": number,
                    "prompt": item.group(2).strip(),
                    "answer": {"required": True, "type": "unknown"},
                })
    if current:
        groups.append(current)
    selected_groups = []
    for group in groups:
        if question_range and (
            group["questions"][1] < question_range[0]
            or group["questions"][0] > question_range[1]
        ):
            continue
        group["answer_type"] = _answer_type(group["instruction"] + "\n" + group["text"])
        numbers = {item["number"] for item in group["items"]}
        for number in _question_numbers(*group["questions"]):
            if number not in numbers:
                group["items"].append({
                    "number": number,
                    "prompt": "",
                    "answer": {"required": True, "type": group["answer_type"]},
                })
        for item in group["items"]:
            item["answer"]["type"] = group["answer_type"]
        duplicate = next(
            (existing for existing in selected_groups if existing["questions"] == group["questions"]),
            None,
        )
        if duplicate is None:
            selected_groups.append(group)
        else:
            duplicate["text"] += "\n\n" + group["text"]
            items_by_number = {item["number"]: item for item in duplicate["items"]}
            for item in group["items"]:
                items_by_number.setdefault(item["number"], item)
            duplicate["items"] = list(items_by_number.values())
            if duplicate["answer_type"] == "unknown" and group["answer_type"] != "unknown":
                duplicate["answer_type"] = group["answer_type"]
    return selected_groups


def _structured_paragraphs(text):
    """Split reading text into labeled paragraphs without discarding raw content."""
    paragraphs = []
    current = None
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        label_match = re.match(r"^([A-H])\s+(.*)$", block, re.DOTALL)
        if label_match:
            if current:
                paragraphs.append(current)
            current = {"label": label_match.group(1), "text": label_match.group(2).strip()}
        elif current:
            current["text"] += "\n\n" + block
        else:
            paragraphs.append({"label": None, "text": block})
    if current:
        paragraphs.append(current)
    return paragraphs


def build_content_for_test(pages_text, test_cfg, pdf_path=None):
    """
    test_cfg: one test's manifest entry (with listening/reading blocks).
    Returns raw text plus structured question groups and reading paragraphs.
    including only sections that have pages configured.
    """
    content = {}
    listening = test_cfg.get("listening", {})
    parts = []
    any_listening_pages = False
    for part in listening.get("parts", []):
        pages = part.get("pages") or []
        text = _pages_to_text(pages_text, pages, mode="list", pdf_path=pdf_path) if pages else ""
        if text:
            any_listening_pages = True
        parts.append({
            "pages": pages,
            "text": text,
            "layout": _native_page_layout(pdf_path, pages) if pdf_path and pages else [],
            "question_groups": _structured_question_groups(text, part.get("questions")),
        })
    if any_listening_pages:
        content["listening"] = {"parts": parts}

    reading = test_cfg.get("reading", {})
    passages = []
    any_reading = False
    for passage in reading.get("passages", []):
        pages = passage.get("pages") or []
        text = _pages_to_text(pages_text, pages, mode="prose", pdf_path=pdf_path) if pages else ""
        if text:
            any_reading = True
        passages.append({
            "pages": pages,
            "text": text,
            "layout": _native_page_layout(pdf_path, pages) if pdf_path and pages else [],
            "paragraphs": _structured_paragraphs(text),
            "question_groups": _structured_question_groups(text, passage.get("questions")),
        })
    if any_reading:
        content["reading"] = {"passages": passages}
    return content


def scaffold_content_files(mock_dir, manifest, pages_text, log, mock_name, pdf_path=None):
    """
    Writes content/<Test N>.json for each test that doesn't have one yet.
    Never overwrites -- hand-fixed OCR typos stay fixed.
    """
    for test_name, cfg in manifest.get("tests", {}).items():
        out_dir = os.path.join(mock_dir, "content")
        out_path = os.path.join(out_dir, f"{test_name}.json")
        if os.path.isfile(out_path):
            continue
        content = build_content_for_test(pages_text, cfg, pdf_path=pdf_path)
        if not content:
            continue
        os.makedirs(out_dir, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(content, f, indent=2, ensure_ascii=False)
        secs = " + ".join(sorted(content.keys()))
        log.append(
            f"[{mock_name}/{test_name}] extracted {secs} text into content/{test_name}.json "
            f"-- the portal will show selectable text with inline answer boxes "
            f"(use the Book view toggle for diagrams/maps; hand-fix any OCR typos in that file)."
        )
