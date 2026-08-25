#!/usr/bin/env python3
"""Extract IELTS mock content from scanned PDF pages using a vision model.

This deliberately does NOT use a traditional OCR engine. Each PDF page is
rendered to a high-resolution PNG with PyMuPDF and sent to a multimodal model.
The model reconstructs semantic text structure and question objects.

Environment:
    OPENAI_API_KEY       required
    OPENAI_VISION_MODEL  optional; defaults to gpt-5.6-luna

Examples:
    python3 scripts/extract_test_content.py \
        --pdf tests/Cambridge\ 21/main.pdf \
        --output tests/Cambridge\ 21/content/Test\ 1.json \
        --pages 1-24

    python3 scripts/extract_test_content.py \
        --pdf tests/Cambridge\ 21/main.pdf \
        --output tests/Cambridge\ 21/content/Test\ 1.json \
        --pages 10-24 --section listening

The first pass is page-oriented. Use --raw-dir to preserve the individual
page responses for auditing. The final JSON is assembled deterministically
from those page records; cross-page group/question continuity is kept by
question number and group ids.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import pathlib
import re
import sys
import time
from typing import Any

import fitz
from openai import OpenAI

ROOT = pathlib.Path(__file__).resolve().parents[1]

QUESTION_TYPES = {
    "text_input",
    "multiple_choice",
    "multiple_choice_multiple",
    "true_false_not_given",
    "yes_no_not_given",
    "matching",
    "matching_headings",
    "matching_information",
    "matching_features",
    "matching_sentence_endings",
    "sentence_completion",
    "summary_completion",
    "notes_completion",
    "table_completion",
    "flow_chart_completion",
    "diagram_label",
    "map_label",
    "form_completion",
    "short_answer",
    "classification",
    "ordering",
}

PAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "page": {"type": "integer"},
        "role": {"type": "string"},
        "printed_page": {"type": ["integer", "null"]},
        "raw_text": {"type": "string"},
        "blocks": {"type": "array"},
        "groups": {"type": "array"}
    },
    "required": ["page", "role", "raw_text", "blocks", "groups"],
    "additionalProperties": True
}

PROMPT = """
You are reconstructing the content of an IELTS practice test from one scanned
PDF page. Traditional OCR is not being used because the source pages are
poor-quality scans. Read the page visually and return semantic content.

Rules:
1. Transcribe visible text faithfully. Do not invent or paraphrase test content.
2. Ignore decorative page numbers, book navigation markers, scan artifacts,
   publisher logos, and answer-key references unless they are part of the test.
3. Detect question numbers exactly. A question number belongs to the IELTS
   question, not to a page or subsection.
4. Detect the question group type from the printed instructions.
5. Capture every option exactly once.
6. For completion questions, represent each numbered blank as a question with
   its surrounding text in `content.before` and `content.after` where possible.
7. Do not guess answers. Leave answer.accepted as [] unless an answer is
   visibly printed on THIS page.
8. Preserve enough surrounding text that another page can be rendered without
   the PDF image.
9. For tables, maps, flow charts and forms, represent the semantic labels and
   text. Do not return pixel coordinates. If some geometry is inherently
   visual, describe it textually in `content.layout_notes`.
10. Return JSON only.

Allowed question types:
""" + ", ".join(sorted(QUESTION_TYPES)) + "\n\nReturn an object matching this shape:\n" + json.dumps(PAGE_SCHEMA, indent=2)


def parse_pages(value: str) -> list[int]:
    pages: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            pages.extend(range(int(a), int(b) + 1))
        else:
            pages.append(int(part))
    return sorted(set(pages))


def render_page(doc: fitz.Document, page_number: int, dpi: int) -> bytes:
    page = doc.load_page(page_number - 1)
    pix = page.get_pixmap(dpi=dpi, alpha=False)
    return pix.tobytes("png")


def extract_page(client: OpenAI, image_bytes: bytes, page_number: int, model: str, section: str | None) -> dict[str, Any]:
    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    section_hint = section or "unknown"
    prompt = PROMPT + f"\n\nThis page is likely part of the {section_hint} section. PDF page number: {page_number}."

    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": f"data:image/png;base64,{image_b64}"}
                ]
            }
        ]
    )
    text = response.output_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    data = json.loads(text)
    data["page"] = page_number
    data.setdefault("role", "unknown")
    data.setdefault("raw_text", "")
    data.setdefault("blocks", [])
    data.setdefault("groups", [])
    return data


def normalize_question(q: dict[str, Any], section: str | None, page: int) -> dict[str, Any]:
    number = q.get("number")
    if not isinstance(number, int):
        raise ValueError(f"question without integer number on page {page}: {q}")
    qid = q.get("id") or f"{section or 'section'}-q{number}"
    q["id"] = qid
    q["number"] = number
    q.setdefault("type", "text_input")
    q.setdefault("source", {"pdf_pages": [page], "primary_page": page, "text_origin": "vision", "verified": False})
    if page not in q["source"].setdefault("pdf_pages", []):
        q["source"]["pdf_pages"].append(page)
    q["source"]["text_origin"] = "vision"
    q.setdefault("answer", {"type": "text", "accepted": []})
    q.setdefault("ui", {})
    return q


def assemble(pages: list[dict[str, Any]], test_id: str, test_name: str, variant: str) -> dict[str, Any]:
    sections: dict[str, dict[str, Any]] = {}
    questions_by_section: dict[str, dict[int, dict[str, Any]]] = {}
    groups_by_section: dict[str, dict[str, dict[str, Any]]] = {}

    for page in pages:
        role = str(page.get("role", "unknown"))
        if "listening" in role:
            section_id = "listening"
        elif "reading" in role:
            section_id = "reading"
        elif "writing" in role:
            section_id = "writing"
        else:
            continue

        section = sections.setdefault(section_id, {
            "id": section_id,
            "type": section_id,
            "title": section_id.title(),
            "duration_seconds": 1800 if section_id == "listening" else 3600,
            "groups": [],
            "passages": [] if section_id == "reading" else None,
            "pages": []
        })
        section["pages"].append({
            "pdf_page": page["page"],
            "printed_page": page.get("printed_page"),
            "role": page.get("role", "unknown"),
            "text_origin": "vision",
            "raw_text": page.get("raw_text", ""),
            "blocks": page.get("blocks", [])
        })

        qmap = questions_by_section.setdefault(section_id, {})
        gmap = groups_by_section.setdefault(section_id, {})

        for raw_group in page.get("groups", []):
            group_id = raw_group.get("id")
            if not group_id:
                rng = raw_group.get("question_range", [page["page"], page["page"]])
                group_id = f"{section_id}-group-{rng[0]}-{rng[-1]}"
            group = gmap.setdefault(group_id, {
                "id": group_id,
                "type": raw_group.get("type", "unknown"),
                "question_range": raw_group.get("question_range"),
                "title": raw_group.get("title"),
                "instructions": raw_group.get("instructions", []),
                "options": raw_group.get("options", []),
                "questions": []
            })
            for raw_q in raw_group.get("questions", []):
                q = normalize_question(dict(raw_q), section_id, page["page"])
                existing = qmap.get(q["number"])
                if existing:
                    merged_pages = existing.setdefault("source", {}).setdefault("pdf_pages", [])
                    for source_page in q["source"]["pdf_pages"]:
                        if source_page not in merged_pages:
                            merged_pages.append(source_page)
                    if not existing.get("prompt") and q.get("prompt"):
                        existing["prompt"] = q["prompt"]
                    if not existing.get("options") and q.get("options"):
                        existing["options"] = q["options"]
                else:
                    qmap[q["number"]] = q

        if section_id == "reading":
            passage = page.get("passage")
            if passage:
                pid = passage.get("id") or f"reading-passage-{passage.get('number', len(section['passages']) + 1)}"
                existing_passage = next((p for p in section["passages"] if p["id"] == pid), None)
                if existing_passage is None:
                    existing_passage = {
                        "id": pid,
                        "number": passage.get("number"),
                        "title": passage.get("title", ""),
                        "source_pages": [],
                        "body_pages": [],
                        "question_groups": []
                    }
                    section["passages"].append(existing_passage)
                if page["page"] not in existing_passage["source_pages"]:
                    existing_passage["source_pages"].append(page["page"])

    for section_id, section in sections.items():
        qmap = questions_by_section.get(section_id, {})
        gmap = groups_by_section.get(section_id, {})
        for group in gmap.values():
            for q in sorted(
                [x for x in qmap.values() if x.get("number") is not None and (
                    group.get("question_range") is None
                    or group["question_range"][0] <= x["number"] <= group["question_range"][-1]
                )],
                key=lambda x: x["number"]
            ):
                if q["id"] not in {x["id"] for x in group["questions"]}:
                    group["questions"].append(q)
            section["groups"].append(group)
        section["groups"].sort(key=lambda g: (g.get("question_range") or [9999])[0])
        if section_id == "reading":
            section.pop("groups", None)
            section["passages"].sort(key=lambda p: p.get("number") or 999)

    output_sections = []
    for sid in ("listening", "reading", "writing"):
        if sid in sections:
            output_sections.append(sections[sid])

    return {
        "schema_version": "2.0",
        "test": {"id": test_id, "name": test_name, "variant": variant},
        "sections": output_sections
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True, type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument("--pages", required=True, help="1-based pages, e.g. 1-24 or 3,7,9-12")
    parser.add_argument("--section", choices=["listening", "reading", "writing"], default=None)
    parser.add_argument("--raw-dir", type=pathlib.Path, default=None)
    parser.add_argument("--dpi", type=int, default=220)
    parser.add_argument("--model", default=os.getenv("OPENAI_VISION_MODEL", "gpt-5.6-luna"))
    parser.add_argument("--test-id", default="mock-test-1")
    parser.add_argument("--test-name", default="Test 1")
    parser.add_argument("--variant", choices=["academic", "general"], default="academic")
    parser.add_argument("--sleep", type=float, default=0.25)
    args = parser.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required")

    pages = parse_pages(args.pages)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.raw_dir:
        args.raw_dir.mkdir(parents=True, exist_ok=True)

    client = OpenAI()
    doc = fitz.open(args.pdf)
    extracted: list[dict[str, Any]] = []
    try:
        for page_number in pages:
            print(f"[vision] page {page_number}/{len(doc)}", flush=True)
            image = render_page(doc, page_number, args.dpi)
            data = extract_page(client, image, page_number, args.model, args.section)
            extracted.append(data)
            if args.raw_dir:
                (args.raw_dir / f"page-{page_number:04d}.json").write_text(
                    json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            time.sleep(args.sleep)
    finally:
        doc.close()

    content = assemble(extracted, args.test_id, args.test_name, args.variant)
    args.output.write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
