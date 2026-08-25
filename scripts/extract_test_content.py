#!/usr/bin/env python3
"""Build text-only IELTS content JSON from scanned PDF pages locally.

No paid API is required. Pages are rendered locally with PyMuPDF and sent to
an Ollama-hosted vision-language model running on the same machine.

Recommended:
    ollama pull qwen3-vl:8b

Then:
    python3 scripts/extract_test_content.py \
      --pdf "tests/Cambridge 21/main.pdf" \
      --output "tests/Cambridge 21/content/Test 1.json" \
      --raw-dir "tests/Cambridge 21/content/raw/Test 1" \
      --pages 11-45 \
      --test-id cambridge-21-test-1 \
      --test-name "Test 1"
"""
from __future__ import annotations

import argparse
import base64
import json
import pathlib
import re
import sys
from typing import Any
from urllib.request import Request, urlopen

import fitz

QUESTION_TYPES = {
    "text_input", "multiple_choice", "multiple_choice_multiple",
    "true_false_not_given", "yes_no_not_given", "matching",
    "matching_headings", "matching_information", "matching_features",
    "matching_sentence_endings", "sentence_completion", "summary_completion",
    "notes_completion", "table_completion", "flow_chart_completion",
    "diagram_label", "map_label", "form_completion", "short_answer",
    "classification", "ordering"
}

SYSTEM_PROMPT = """You are reconstructing an IELTS practice-test page from a scanned image.
Return JSON only. This is a text-only website, so the final JSON must contain
all learner-visible text needed to render the question without the PDF.

Rules:
- Transcribe visible test text faithfully. Never invent or paraphrase.
- Ignore publisher logos, footer navigation, decorative page numbers and
  answer-key references unless they are part of the test.
- Identify every actual IELTS question number exactly once.
- Detect the question group from its printed instructions.
- Capture every option and every instruction belonging to the group.
- For completion questions, represent the surrounding sentence/note/table
  text and connect each blank to a question number.
- Never guess answers. `answer.accepted` must be [] unless an answer key is
  visibly printed on this page.
- For tables/forms/maps, reproduce their textual content and relationships;
  do not depend on coordinates or PDF images.
- Preserve enough prose to render Reading passages as normal selectable text.

Allowed question types:
""" + ", ".join(sorted(QUESTION_TYPES))

PAGE_FORMAT = {
    "page": 0,
    "role": "reading_question_sheet|reading_passage|listening_question_sheet|writing_task|unknown",
    "printed_page": None,
    "raw_text": "",
    "blocks": [],
    "groups": [],
    "passage": None
}


def parse_pages(value: str) -> list[int]:
    result: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            result.update(range(int(a), int(b) + 1))
        else:
            result.add(int(part))
    return sorted(result)


def render_page(doc: fitz.Document, page_number: int, dpi: int) -> bytes:
    page = doc.load_page(page_number - 1)
    pix = page.get_pixmap(dpi=dpi, alpha=False)
    return pix.tobytes("png")


def ollama_chat(base_url: str, model: str, prompt: str, image_bytes: bytes) -> str:
    payload = {
        "model": model,
        "stream": False,
        "format": "json",
        "messages": [{
            "role": "user",
            "content": prompt,
            "images": [base64.b64encode(image_bytes).decode("ascii")]
        }],
        "options": {"temperature": 0}
    }
    request = Request(
        base_url.rstrip("/") + "/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urlopen(request, timeout=600) as response:
            body = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(
            f"Could not reach Ollama at {base_url}. Start Ollama and pull the model first."
        ) from exc
    return body.get("message", {}).get("content", "").strip()


def parse_model_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Model output was not a JSON object")
    return data


def normalize_question(q: dict[str, Any], section: str, page: int) -> dict[str, Any]:
    number = q.get("number")
    if not isinstance(number, int):
        raise ValueError(f"Question without integer number on PDF page {page}: {q}")
    q = dict(q)
    q["id"] = q.get("id") or f"{section}-q{number}"
    q["number"] = number
    q["source"] = dict(q.get("source") or {})
    pages = list(q["source"].get("pdf_pages") or [])
    if page not in pages:
        pages.append(page)
    q["source"]["pdf_pages"] = pages
    q["source"]["primary_page"] = q["source"].get("primary_page", page)
    q["source"]["text_origin"] = "local_vision"
    q["source"]["verified"] = False
    q.setdefault("answer", {"type": "text", "accepted": []})
    q.setdefault("ui", {})
    return q


def section_for_role(role: str) -> str | None:
    role = role.lower()
    if "listening" in role:
        return "listening"
    if "reading" in role:
        return "reading"
    if "writing" in role:
        return "writing"
    return None


def assemble(pages: list[dict[str, Any]], test_id: str, test_name: str, variant: str) -> dict[str, Any]:
    sections: dict[str, dict[str, Any]] = {}
    groups: dict[str, dict[str, Any]] = {}
    questions: dict[str, dict[int, dict[str, Any]]] = {}

    for page in pages:
        sid = section_for_role(str(page.get("role", "")))
        if not sid:
            continue
        section = sections.setdefault(sid, {
            "id": sid,
            "type": sid,
            "title": sid.title(),
            "duration_seconds": 1800 if sid == "listening" else 3600,
            "pages": [],
            "groups": [] if sid != "reading" else None,
            "passages": [] if sid == "reading" else None
        })
        section["pages"].append({
            "pdf_page": page["page"],
            "printed_page": page.get("printed_page"),
            "role": page.get("role", "unknown"),
            "raw_text": page.get("raw_text", ""),
            "blocks": page.get("blocks", [])
        })

        qstore = questions.setdefault(sid, {})
        for raw_group in page.get("groups", []) or []:
            rng = raw_group.get("question_range") or []
            gid = raw_group.get("id") or f"{sid}-group-{rng[0] if rng else page['page']}-{rng[-1] if rng else page['page']}"
            group = groups.setdefault(gid, {
                "id": gid,
                "type": raw_group.get("type", "unknown"),
                "question_range": rng,
                "title": raw_group.get("title"),
                "instructions": raw_group.get("instructions", []),
                "options": raw_group.get("options", []),
                "content": raw_group.get("content"),
                "questions": []
            })
            for raw_q in raw_group.get("questions", []) or []:
                q = normalize_question(raw_q, sid, page["page"])
                n = q["number"]
                if n in qstore:
                    existing = qstore[n]
                    for p in q["source"]["pdf_pages"]:
                        if p not in existing["source"]["pdf_pages"]:
                            existing["source"]["pdf_pages"].append(p)
                    for key in ("prompt", "content", "options"):
                        if not existing.get(key) and q.get(key):
                            existing[key] = q[key]
                else:
                    qstore[n] = q

        if sid == "reading" and page.get("passage"):
            p = page["passage"]
            pid = p.get("id") or f"reading-passage-{p.get('number', 1)}"
            existing = next((x for x in section["passages"] if x["id"] == pid), None)
            if existing is None:
                existing = {
                    "id": pid,
                    "number": p.get("number"),
                    "title": p.get("title", ""),
                    "source_pages": [],
                    "body": []
                }
                section["passages"].append(existing)
            if page["page"] not in existing["source_pages"]:
                existing["source_pages"].append(page["page"])
            existing["body"].append({
                "pdf_page": page["page"],
                "blocks": page.get("blocks", []),
                "raw_text": page.get("raw_text", "")
            })

    for sid, section in sections.items():
        qstore = questions.get(sid, {})
        section_groups = []
        for gid, group in groups.items():
            if not gid.startswith(sid + "-"):
                continue
            start_end = group.get("question_range") or []
            for n, q in sorted(qstore.items()):
                if not start_end or (start_end[0] <= n <= start_end[-1]):
                    if q["id"] not in {x["id"] for x in group["questions"]}:
                        group["questions"].append(q)
            group["questions"].sort(key=lambda x: x["number"])
            section_groups.append(group)
        section_groups.sort(key=lambda x: (x.get("question_range") or [9999])[0])
        if sid != "reading":
            section["groups"] = section_groups
        else:
            section["passages"].sort(key=lambda x: x.get("number") or 999)

    output_sections = [sections[s] for s in ("listening", "reading", "writing") if s in sections]
    for section in output_sections:
        section.pop("pages", None)  # page-level source metadata is audit-only
    return {
        "schema_version": "2.0",
        "test": {"id": test_id, "name": test_name, "variant": variant},
        "rendering": {"primary": "structured_text", "pdf_pages": False},
        "sections": output_sections
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True, type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument("--pages", required=True)
    parser.add_argument("--raw-dir", type=pathlib.Path)
    parser.add_argument("--section", choices=["listening", "reading", "writing"])
    parser.add_argument("--dpi", type=int, default=220)
    parser.add_argument("--model", default="qwen3-vl:8b")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--test-id", default="mock-test-1")
    parser.add_argument("--test-name", default="Test 1")
    parser.add_argument("--variant", choices=["academic", "general"], default="academic")
    args = parser.parse_args()

    pages = parse_pages(args.pages)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.raw_dir:
        args.raw_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(args.pdf)
    extracted: list[dict[str, Any]] = []
    try:
        for page_number in pages:
            print(f"[local-vision] page {page_number}/{len(doc)}", flush=True)
            image = render_page(doc, page_number, args.dpi)
            prompt = SYSTEM_PROMPT + f"\n\nLikely section: {args.section or 'unknown'}\nPDF page: {page_number}\n\nReturn exactly this top-level shape, adding useful fields where needed:\n{json.dumps(PAGE_FORMAT, indent=2)}"
            data = parse_model_json(ollama_chat(args.ollama_url, args.model, prompt, image))
            data["page"] = page_number
            data.setdefault("role", "unknown")
            data.setdefault("printed_page", None)
            data.setdefault("raw_text", "")
            data.setdefault("blocks", [])
            data.setdefault("groups", [])
            extracted.append(data)
            if args.raw_dir:
                (args.raw_dir / f"page-{page_number:04d}.json").write_text(
                    json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
    finally:
        doc.close()

    content = assemble(extracted, args.test_id, args.test_name, args.variant)
    args.output.write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
