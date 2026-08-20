"""Build structured IELTS content v2 from OCR page text.

The extractor keeps the scanned PDF as the source of truth while producing a
structured, selectable representation for the portal. It intentionally keeps
raw_text and source-page references because OCR cannot reproduce diagrams,
forms, maps and charts exactly.

The generated document is compatible with the v2 schema in
schemas/ielts-content.schema.json and also contains a small legacy view so
older frontend code can continue to work during migration.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from lib.content_schema import validate_content


_NOISE = [
    re.compile(r"^\s*Test\s+\d+\s*$", re.I),
    re.compile(r"^\s*(LISTENING|READING|WRITING|ACADEMIC READING)\s*$", re.I),
    re.compile(r"^\s*\d{1,3}\s*$"),
    re.compile(r"^\s*IELTS\s+\d+\s*$", re.I),
]

_QRANGE = re.compile(r"(?:Questions?|Q)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})", re.I)
_GAP = re.compile(r"\b(\d{1,2})\s*(?:[.…·]{3,}|_{3,})")


def _clean_lines(text: str) -> list[str]:
    out = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or any(rx.match(line) for rx in _NOISE):
            continue
        out.append(line)
    return out


def _block_type(line: str) -> str:
    if _QRANGE.search(line):
        if line.lower().startswith("questions"):
            return "question_group_heading"
    if re.match(r"^(Complete|Choose|Write|Do the following|Label|Match|Select|Circle)\b", line, re.I):
        return "instruction"
    if re.match(r"^[A-H]\.?\s+", line) or re.match(r"^[A-H]$", line):
        return "option"
    if re.match(r"^(?:\d{1,2}[.)]|\d{1,2}\s+\.)\s+", line):
        return "question_line"
    if line.startswith(("•", "*", "- ")):
        return "bullet"
    if re.match(r"^(PART|SECTION|READING PASSAGE|WRITING TASK)\b", line, re.I):
        return "heading"
    if len(line) <= 80 and line.isupper() and any(c.isalpha() for c in line):
        return "heading"
    if _GAP.search(line):
        return "question_line"
    return "paragraph"


def _blocks(text: str) -> list[dict[str, str]]:
    return [{"type": _block_type(line), "text": line} for line in _clean_lines(text)]


def _page_record(page_number: int, raw_text: str, role: str = "content") -> dict[str, Any]:
    lines = _clean_lines(raw_text)
    title = next((x for x in lines if _block_type(x) == "heading"), None)
    return {
        "pdf_page": page_number,
        "printed_page": None,
        "role": role,
        "text_origin": "ocr_from_scan",
        "raw_text": raw_text or "",
        "blocks": _blocks(raw_text or ""),
        **({"title": title} if title else {}),
    }


def _question_range(item: dict[str, Any], fallback: tuple[int, int] = (1, 10)) -> list[int]:
    q = item.get("questions") or item.get("question_range")
    if isinstance(q, (list, tuple)) and len(q) == 2:
        return [int(q[0]), int(q[1])]
    return list(fallback)


def _page_records(pages_text: list[str], pages: list[int], role: str) -> list[dict[str, Any]]:
    records = []
    for p in pages or []:
        if isinstance(p, int) and 1 <= p <= len(pages_text):
            records.append(_page_record(p, pages_text[p - 1], role))
    return records


def _question_types(item: dict[str, Any]) -> list[str]:
    types = item.get("question_types") or []
    if isinstance(types, str):
        types = [types]
    return list(dict.fromkeys(str(x) for x in types))


def _build_listening(pages_text: list[str], cfg: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    parts_v2, parts_legacy = [], []
    for i, part in enumerate(cfg.get("parts", []), 1):
        number = int(part.get("part_number") or part.get("part") or i)
        qrange = _question_range(part, ((number - 1) * 10 + 1, number * 10))
        pages = part.get("pages") or []
        records = _page_records(pages_text, pages, "listening_question_sheet")
        qtypes = _question_types(part)
        if not qtypes:
            # Preserve information even when the manifest only has pages.
            qtypes = ["structured_question_sheet"]
        sets = [{"type": t, "scope": "page_layout", "source_pages": pages} for t in qtypes]
        parts_v2.append({
            "id": f"listening-part-{number}",
            "type": "part",
            "number": number,
            "title": f"PART {number}",
            "question_range": qrange,
            "question_types": qtypes,
            "source_pages": pages,
            "instructions": [],
            "pages": records,
            "question_sets": sets,
        })
        text = "\n\n".join(p.get("raw_text", "") for p in records)
        legacy = {"text": text, "questions": qrange, "pages": pages}
        files = part.get("files") or ([] if not part.get("file") else [part["file"]])
        if files:
            legacy["files"] = files
            legacy["file"] = files[0]
        parts_legacy.append(legacy)
    v2 = {"id": "listening", "type": "listening", "title": "LISTENING", "duration_minutes": cfg.get("duration_minutes", 40), "parts": parts_v2}
    legacy = {"duration_minutes": cfg.get("duration_minutes", 40), "parts": parts_legacy}
    return v2, legacy


def _split_reading_pages(pages_text: list[str], pages: list[int]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    body, questions = [], []
    for p in pages or []:
        if not (isinstance(p, int) and 1 <= p <= len(pages_text)):
            continue
        raw = pages_text[p - 1] or ""
        # A page containing a question-range marker is a question-sheet page.
        # Mixed pages are kept with the question sheet so the UI can fall back
        # to the original page when geometry matters.
        role = "reading_question_sheet" if _QRANGE.search(raw) else "reading_passage"
        rec = _page_record(p, raw, role)
        (questions if role == "reading_question_sheet" else body).append(rec)
    return body, questions


def _build_reading(pages_text: list[str], cfg: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    passages_v2, passages_legacy = [], []
    for i, passage in enumerate(cfg.get("passages", []), 1):
        qrange = _question_range(passage, (1, 13))
        pages = passage.get("pages") or []
        body, question_pages = _split_reading_pages(pages_text, pages)
        qtypes = _question_types(passage)
        text = "\n\n".join(p.get("raw_text", "") for p in body + question_pages)
        title = passage.get("title") or f"Reading Passage {i}"
        passages_v2.append({
            "id": f"reading-passage-{i}",
            "type": "passage",
            "number": i,
            "title": title,
            "question_range": qrange,
            "question_types": qtypes,
            "source_pages": pages,
            "body_pages": body,
            "question_pages": question_pages,
            "text": text,
        })
        passages_legacy.append({"text": text, "questions": qrange, "pages": pages})
    v2 = {"id": "reading", "type": "reading", "title": "READING", "duration_minutes": cfg.get("duration_minutes", 60), "passages": passages_v2}
    legacy = {"duration_minutes": cfg.get("duration_minutes", 60), "passages": passages_legacy}
    return v2, legacy


def _build_writing(pages_text: list[str], cfg: dict[str, Any]) -> dict[str, Any]:
    tasks = []
    for key, label in (("task1", "Task 1"), ("task2", "Task 2")):
        task = cfg.get(key)
        if not task:
            continue
        page = task.get("page")
        pages = [page] if isinstance(page, int) else []
        records = _page_records(pages_text, pages, "writing_prompt")
        tasks.append({
            "id": key,
            "type": "writing_task",
            "title": label,
            "duration_minutes": task.get("duration_minutes", 20 if key == "task1" else 40),
            "source_pages": pages,
            "pages": records,
        })
    return {"id": "writing", "type": "writing", "title": "WRITING", "tasks": tasks}


def build_content_for_test(pages_text: list[str], test_cfg: dict[str, Any]) -> dict[str, Any]:
    """Return one v2 content document plus temporary legacy compatibility data."""
    test_name = test_cfg.get("test_name") or test_cfg.get("name") or "Test"
    sections, legacy = [], {}

    if test_cfg.get("listening"):
        v2, old = _build_listening(pages_text, test_cfg["listening"])
        sections.append(v2); legacy["listening"] = old
    if test_cfg.get("reading"):
        v2, old = _build_reading(pages_text, test_cfg["reading"])
        sections.append(v2); legacy["reading"] = old
    if test_cfg.get("writing"):
        sections.append(_build_writing(pages_text, test_cfg["writing"]))

    doc = {
        "schema_version": 2,
        "content_schema": "ieltsband.content.v2",
        "test": test_name,
        "variant": test_cfg.get("variant", "academic"),
        "rendering": {
            "primary": "structured_blocks",
            "fallback": "source_pdf_page",
            "inline_answers": "question-number keyed",
        },
        "sections": sections,
        **legacy,
        "notes": [
            "Use sections[].pages[].blocks for selectable rendering.",
            "Use source_pages and the Book view for diagrams, maps, tables and charts.",
            "raw_text is retained as an accessibility/search fallback, not as the primary layout source.",
        ],
    }
    errors = validate_content(doc)
    if errors:
        raise ValueError("Generated invalid structured content: " + "; ".join(errors))
    return doc


def scaffold_content_files(mock_dir: str, manifest: dict[str, Any], pages_text: list[str], log: list[str], mock_name: str) -> None:
    """Write v2 content files without overwriting hand-corrected files."""
    for test_name, cfg in manifest.get("tests", {}).items():
        out_dir = os.path.join(mock_dir, "content")
        out_path = os.path.join(out_dir, f"{test_name}.json")
        if os.path.isfile(out_path):
            # Existing files are deliberately preserved; run the validator
            # separately when a content file is changed by hand.
            continue
        cfg = dict(cfg)
        cfg["test_name"] = test_name
        content = build_content_for_test(pages_text, cfg)
        os.makedirs(out_dir, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(content, f, indent=2, ensure_ascii=False)
        log.append(f"[{mock_name}/{test_name}] wrote structured content v2 to content/{test_name}.json")
