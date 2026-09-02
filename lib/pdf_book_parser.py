"""Parse IELTS practice-book PDFs into the app's manifest format.

Listening/audio is intentionally excluded for now. The importer uses the PDF
itself as the source of truth for Reading, Writing, and Speaking content; the
manifest records the page ranges needed by the existing PDF renderer.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional

import fitz  # PyMuPDF


def _compact(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def _has(compact: str, *parts: str) -> bool:
    return all(part in compact for part in parts)


def _first_page(pages: List[str], start: int, end: int, predicate) -> Optional[int]:
    for page in range(start, end + 1):
        if predicate(pages[page]):
            return page
    return None


def _answer_sheet_page(pages: List[str], start: int, end: int, section: str) -> Optional[int]:
    needle = f"{section.upper()}ANSWERSHEET"
    for page in range(start, end + 1):
        if needle in _compact(pages[page]):
            return page
    return None


def _module_end(
    pages: List[str],
    begin: Optional[int],
    next_begin: Optional[int],
    section: str,
    book_end: int,
) -> Optional[int]:
    if begin is None:
        return None
    limit = (next_begin - 1) if next_begin is not None else book_end
    answer = _answer_sheet_page(pages, begin, limit, section)
    return answer - 1 if answer is not None else limit


def _marker_regex_pages(
    pages: List[str], begin: Optional[int], end: Optional[int], pattern: str
) -> List[int]:
    if begin is None or end is None:
        return []
    rx = re.compile(pattern, re.I)
    return [p for p in range(begin, end + 1) if rx.search(_compact(pages[p]))]


def parse_book(pdf_path: str | Path) -> Dict:
    """Return a manifest-oriented description of one IELTS PDF."""
    pdf_path = Path(pdf_path)
    doc = fitz.open(pdf_path)
    pages = [doc[i].get_text("text") or "" for i in range(len(doc))]
    compact = [_compact(page) for page in pages]

    starts = []
    for i, page in enumerate(compact):
        for number in range(1, 5):
            if _has(page, f"PRACTICETEST{number}", "LISTENING40QUESTIONS"):
                starts.append((number, i))
                break

    unique = {}
    for number, page in starts:
        unique.setdefault(number, page)
    starts = sorted(unique.items())

    if not starts:
        return {
            "source_file": pdf_path.name,
            "book_type": "reference",
            "page_count": len(pages),
            "tests": [],
        }

    tests = []
    for idx, (number, start) in enumerate(starts):
        book_end = starts[idx + 1][1] - 1 if idx + 1 < len(starts) else len(pages) - 1

        reading = _first_page(
            pages,
            start,
            book_end,
            lambda text: _has(_compact(text), f"PRACTICETEST{number}", "READING40QUESTIONS"),
        )
        writing = _first_page(
            pages,
            start,
            book_end,
            lambda text: _has(_compact(text), f"PRACTICETEST{number}", "WRITING2TASKS"),
        )
        speaking = _first_page(
            pages,
            start,
            book_end,
            lambda text: _has(_compact(text), f"PRACTICETEST{number}", "SPEAKING3PARTS"),
        )

        reading_end = _module_end(pages, reading, writing, "READING", book_end)
        writing_end = _module_end(pages, writing, speaking, "WRITING", book_end)
        speaking_end = book_end

        passage_starts = _marker_regex_pages(
            pages, reading, reading_end, r"READINGPASSAGE[1-3]"
        )[:3]
        if len(passage_starts) < 3:
            # Some books label the three reading passages only as sections.
            passage_starts = []
            for section in range(1, 4):
                passage_starts.extend(
                    _marker_regex_pages(
                        pages, reading, reading_end, rf"SECTION{section}"
                    )[:1]
                )

        reading_passages = []
        question_ranges = [[1, 13], [14, 26], [27, 40]]
        for index, page in enumerate(passage_starts):
            stop = (
                passage_starts[index + 1] - 1
                if index + 1 < len(passage_starts)
                else reading_end
            )
            reading_passages.append(
                {
                    "pages": list(range(page + 1, stop + 2)),
                    "questions": question_ranges[index],
                }
            )

        task2_page = None
        if writing is not None and writing_end is not None:
            for page in range(writing, writing_end + 1):
                if re.search(r"TASK\s*2", pages[page], re.I):
                    task2_page = page + 1
                    break
            task2_page = task2_page or writing + 3

        cfg = {
            "name": f"Test {number}",
            "variant": "academic",
            "reading": {
                "duration_minutes": 60,
                "passages": reading_passages,
            }
            if reading is not None and reading_passages
            else None,
            "writing": {
                "task1": {"page": writing + 1, "duration_minutes": 20},
                "task2": {"page": task2_page, "duration_minutes": 40},
            }
            if writing is not None
            else None,
            "speaking": {
                "pages": list(range(speaking + 1, speaking_end + 2)),
            }
            if speaking is not None
            else None,
        }
        tests.append(cfg)

    return {
        "source_file": pdf_path.name,
        "book_type": "practice",
        "page_count": len(pages),
        "tests": tests,
    }
