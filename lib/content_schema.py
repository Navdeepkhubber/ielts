"""Validation helpers for IELTSBand structured content v2.

This module deliberately avoids a third-party JSON-schema dependency so the
portal can validate content in the same lightweight runtime used by local
scaffolding and production.
"""
from __future__ import annotations

import json
import os


SCHEMA_VERSION = 2
CONTENT_SCHEMA = "ieltsband.content.v2"


def validate_content(data: dict) -> list[str]:
    """Return human-readable validation errors for one content document."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["content must be a JSON object"]

    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if data.get("content_schema") != CONTENT_SCHEMA:
        errors.append(f"content_schema must be {CONTENT_SCHEMA!r}")
    if not isinstance(data.get("test"), str) or not data.get("test"):
        errors.append("test must be a non-empty string")

    sections = data.get("sections")
    if not isinstance(sections, list):
        errors.append("sections must be an array")
        return errors

    allowed = {"listening", "reading", "writing", "speaking"}
    for i, section in enumerate(sections):
        path = f"sections[{i}]"
        if not isinstance(section, dict):
            errors.append(f"{path} must be an object")
            continue
        for key in ("id", "type", "title"):
            if not isinstance(section.get(key), str) or not section.get(key):
                errors.append(f"{path}.{key} must be a non-empty string")
        if section.get("type") not in allowed:
            errors.append(f"{path}.type must be one of {sorted(allowed)}")

        for key in ("parts", "passages", "tasks"):
            if key in section and not isinstance(section[key], list):
                errors.append(f"{path}.{key} must be an array")

    return errors


def validate_file(path: str) -> list[str]:
    with open(path, encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as exc:
            return [f"invalid JSON: {exc}"]
    return validate_content(data)


def schema_path() -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "schemas",
        "ielts-content.schema.json",
    )
