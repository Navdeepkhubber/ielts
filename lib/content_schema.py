"""Validation helpers for structured IELTS content v3."""
import json
from pathlib import Path

SCHEMA_VERSION = 3
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "ielts-content.schema.json"


def validate_content(data):
    if not isinstance(data, dict):
        raise ValueError("Content must be a JSON object")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Expected schema_version {SCHEMA_VERSION}, got {data.get('schema_version')!r}")
    for section_name, collection_name in (("reading", "passages"), ("listening", "parts")):
        section = data.get(section_name)
        if not section:
            continue
        for index, item in enumerate(section.get(collection_name, []), 1):
            for key in ("text", "blocks", "questions", "question_range", "qa"):
                if key not in item:
                    raise ValueError(f"{section_name}.{collection_name}[{index}] missing {key}")
    return True


def validate_file(path):
    with open(path, encoding="utf-8") as f:
        return validate_content(json.load(f))
