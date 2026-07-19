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


def _pages_to_text(pages_text, page_numbers, mode="prose"):
    """page_numbers are 1-indexed. mode: "prose" (reading) or "list" (listening)."""
    chunks = []
    for p in page_numbers:
        if 1 <= p <= len(pages_text):
            t = _clean_page_text(pages_text[p - 1], mode=mode)
            if t:
                chunks.append(t)
    return "\n\n".join(chunks)


def build_content_for_test(pages_text, test_cfg):
    """
    test_cfg: one test's manifest entry (with listening/reading blocks).
    Returns {"listening": {"parts": [{"text": ...}]},
             "reading": {"passages": [{"text": ...}]}}
    including only sections that have pages configured.
    """
    content = {}
    listening = test_cfg.get("listening", {})
    parts = []
    any_listening_pages = False
    for part in listening.get("parts", []):
        pages = part.get("pages") or []
        text = _pages_to_text(pages_text, pages, mode="list") if pages else ""
        if text:
            any_listening_pages = True
        parts.append({"text": text})
    if any_listening_pages:
        content["listening"] = {"parts": parts}

    reading = test_cfg.get("reading", {})
    passages = []
    any_reading = False
    for passage in reading.get("passages", []):
        pages = passage.get("pages") or []
        text = _pages_to_text(pages_text, pages, mode="prose") if pages else ""
        if text:
            any_reading = True
        passages.append({"text": text})
    if any_reading:
        content["reading"] = {"passages": passages}
    return content


def scaffold_content_files(mock_dir, manifest, pages_text, log, mock_name):
    """
    Writes content/<Test N>.json for each test that doesn't have one yet.
    Never overwrites -- hand-fixed OCR typos stay fixed.
    """
    for test_name, cfg in manifest.get("tests", {}).items():
        out_dir = os.path.join(mock_dir, "content")
        out_path = os.path.join(out_dir, f"{test_name}.json")
        if os.path.isfile(out_path):
            continue
        content = build_content_for_test(pages_text, cfg)
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
