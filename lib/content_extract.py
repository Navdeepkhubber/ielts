"""
Structured text extraction for IELTS reading/listening content.

Keeps the existing `text` field for backwards compatibility while adding
`blocks` and `questions`. Question boundaries are constrained by the manifest
question range, so numbers in normal passage prose are not treated as
questions. The original PDF pages remain the visual fallback for maps,
diagrams and OCR that needs correction.
"""
import json
import os
import re

_NOISE_RES = [
    re.compile(r"^\s*Test\s+\d+\s*$", re.IGNORECASE),
    re.compile(r"^\s*(LISTENING|READING|WRITING|ACADEMIC READING)\s*$", re.IGNORECASE),
    re.compile(r"^\s*\d{1,3}\s*$"),
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
    re.compile(r"^\s*Complete the .{3,60}$", re.IGNORECASE),
    re.compile(r"^\s*Choose .{3,60}$", re.IGNORECASE),
    re.compile(r"^\s*Write (?:ONE|NO MORE|TRUE|FALSE) .{0,60}$", re.IGNORECASE),
]
_GAP_RE = re.compile(r"\d{1,2}\s*(?:[.…·]{3,}|_{3,})")
_QUESTION_START_RE = re.compile(
    r"^\s*(\d{1,2})(?:\s*[.)/:]\s+|\s+(?=[A-Za-z(\[])|\s+(?=[_.…·]{3,}))(.+?)\s*$"
)
_LONE_QUESTION_NUMBER_RE = re.compile(r"^\s*(\d{1,2})\s*$")


def _is_heading_like(line):
    return any(rx.match(line) for rx in _HEADING_LIKE_RES)


def _question_start(line, q_from, q_to):
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
    return None


def _clean_lines(text):
    return [line for raw in text.splitlines() for line in [raw.rstrip()] if not any(rx.match(line) for rx in _NOISE_RES)]


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
    """Split one page into non-question blocks and independently bounded questions."""
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
            # Structural heading after a question ends that question. This
            # prevents the next instruction/group from being swallowed.
            if _is_heading_like(line) and not _GAP_RE.search(line):
                flush_question()
                prose_lines.append(line)
            else:
                current["lines"].append(line)
        else:
            prose_lines.append(line)

    flush_question()
    flush_prose()
    return prose_blocks, questions


def _section_content(pages_text, pages, mode, q_range):
    prose_blocks, questions = [], []
    for p in pages:
        if not 1 <= p <= len(pages_text):
            continue
        lines = _clean_lines(pages_text[p - 1])
        page_prose, page_questions = _extract_page(lines, q_range, mode, p)
        prose_blocks.extend({"type": "text", "page": p, "text": x} for x in page_prose if x)
        questions.extend(page_questions)

    seen = set()
    unique_questions = []
    for q in questions:
        if q["question"] in seen:
            continue
        seen.add(q["question"])
        unique_questions.append(q)

    # `text` remains a useful fallback/debug representation. The UI should
    # prefer prose_blocks + questions when schema_version >= 2.
    return {
        "text": "\n\n".join(x["text"] for x in prose_blocks + [{"text": q["text"]} for q in unique_questions]),
        "blocks": prose_blocks,
        "questions": unique_questions,
        "question_range": list(q_range) if q_range else None,
    }


def build_content_for_test(pages_text, test_cfg):
    content = {"schema_version": 2}
    listening = test_cfg.get("listening", {})
    parts, any_listening = [], False
    for part in listening.get("parts", []):
        pages = part.get("pages") or []
        section = _section_content(pages_text, pages, "list", part.get("questions"))
        any_listening = any_listening or bool(section["text"])
        parts.append(section)
    if any_listening:
        content["listening"] = {"parts": parts}

    reading = test_cfg.get("reading", {})
    passages, any_reading = [], False
    for passage in reading.get("passages", []):
        pages = passage.get("pages") or []
        section = _section_content(pages_text, pages, "prose", passage.get("questions"))
        any_reading = any_reading or bool(section["text"])
        passages.append(section)
    if any_reading:
        content["reading"] = {"passages": passages}
    return content


def scaffold_content_files(mock_dir, manifest, pages_text, log, mock_name):
    for test_name, cfg in manifest.get("tests", {}).items():
        out_dir = os.path.join(mock_dir, "content")
        out_path = os.path.join(out_dir, f"{test_name}.json")
        if os.path.isfile(out_path):
            continue
        content = build_content_for_test(pages_text, cfg)
        if not any(k in content for k in ("reading", "listening")):
            continue
        os.makedirs(out_dir, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(content, f, indent=2, ensure_ascii=False)
        detected = sum(len(s.get("questions", [])) for k in ("reading", "listening") for s in content.get(k, {}).get("passages", []) + content.get(k, {}).get("parts", []))
        secs = " + ".join(k for k in ("reading", "listening") if k in content)
        log.append(f"[{mock_name}/{test_name}] extracted {secs}; detected {detected} structured question blocks.")
