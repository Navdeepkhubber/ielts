#!/usr/bin/env python3
"""Validate IELTS content-v2 JSON files and report question coverage.

Usage:
    python3 scripts/validate_content.py tests/Cambridge\ 21/content/Test\ 1.json
    python3 scripts/validate_content.py tests/Cambridge\ 21/content/Test\ 1.json --expected-reading 40 --expected-listening 40
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

try:
    from jsonschema import Draft202012Validator
except ImportError as exc:  # pragma: no cover - authoring dependency
    raise SystemExit("Install extraction dependencies: pip install -r requirements-extraction.txt") from exc


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "content.schema.json"


def _collect_questions(section: dict) -> list[dict]:
    questions: list[dict] = []
    for group in section.get("groups", []):
        questions.extend(group.get("questions", []))
    for passage in section.get("passages", []):
        for group in passage.get("question_groups", []):
            questions.extend(group.get("questions", []))
    return questions


def _validate_unique_numbers(section: dict) -> list[str]:
    errors: list[str] = []
    questions = _collect_questions(section)
    seen: dict[int, str] = {}
    for q in questions:
        number = q.get("number")
        if not isinstance(number, int):
            continue
        if number in seen:
            errors.append(f"{section['id']}: duplicate question number {number} ({seen[number]} and {q.get('id')})")
        else:
            seen[number] = q.get("id", "?")
    return errors


def _validate_ranges(section: dict) -> list[str]:
    errors: list[str] = []
    questions = _collect_questions(section)
    numbers = sorted({q.get("number") for q in questions if isinstance(q.get("number"), int)})
    if not numbers:
        return [f"{section['id']}: no questions found"]
    if section["id"] == "reading":
        expected = list(range(1, 41))
    elif section["id"] == "listening":
        expected = list(range(1, 41))
    else:
        return errors
    missing = [n for n in expected if n not in numbers]
    extra = [n for n in numbers if n not in expected]
    if missing:
        errors.append(f"{section['id']}: missing questions {missing}")
    if extra:
        errors.append(f"{section['id']}: unexpected question numbers {extra}")
    return errors


def validate(path: pathlib.Path, expected: dict[str, int | None]) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    schema_errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))

    if schema_errors:
        print(f"SCHEMA FAIL: {path}")
        for error in schema_errors:
            location = ".".join(str(x) for x in error.absolute_path) or "$"
            print(f"  {location}: {error.message}")
        return 1

    semantic_errors: list[str] = []
    for section in data.get("sections", []):
        semantic_errors.extend(_validate_unique_numbers(section))
        semantic_errors.extend(_validate_ranges(section))
        actual = len(_collect_questions(section))
        wanted = expected.get(section.get("id"))
        print(f"{section.get('id')}: {actual} questions")
        if wanted is not None and actual != wanted:
            semantic_errors.append(f"{section.get('id')}: expected {wanted} questions, found {actual}")

    if semantic_errors:
        print("SEMANTIC FAIL:")
        for error in semantic_errors:
            print(f"  {error}")
        return 1

    print("VALID")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("content", type=pathlib.Path)
    parser.add_argument("--expected-reading", type=int, default=None)
    parser.add_argument("--expected-listening", type=int, default=None)
    args = parser.parse_args()
    return validate(
        args.content,
        {"reading": args.expected_reading, "listening": args.expected_listening},
    )


if __name__ == "__main__":
    sys.exit(main())
