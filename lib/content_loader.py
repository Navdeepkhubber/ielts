"""Loader for structured text-only IELTS content v2.

This module is deliberately separate from the legacy manifest/answer loader so
existing mocks continue to work unchanged while v2 content is introduced.
"""
from __future__ import annotations

import json
import os
from typing import Any

from lib import test_loader


def content_path(mock_id: str, test_name: str, manifest: dict[str, Any] | None = None) -> str:
    manifest = manifest or test_loader.load_manifest(mock_id)
    cfg = manifest.get("tests", {}).get(test_name)
    if cfg is None:
        raise FileNotFoundError(f"'{test_name}' not found in mock '{mock_id}'")

    content_file = cfg.get("content_file")
    if not content_file:
        # Legacy authoring convention used by the current generated bundles.
        content_file = os.path.join("content", f"{test_name}.json")

    path = test_loader.cached_file(mock_id, content_file)
    if path is None:
        raise FileNotFoundError(f"No structured content for '{mock_id}/{test_name}'")
    return path


def load_test_content(mock_id: str, test_name: str) -> dict[str, Any]:
    manifest = test_loader.load_manifest(mock_id)
    path = content_path(mock_id, test_name, manifest)
    with open(path, encoding="utf-8") as handle:
        content = json.load(handle)

    if content.get("schema_version") != "2.0":
        raise ValueError(
            f"Unsupported content schema for '{mock_id}/{test_name}': "
            f"{content.get('schema_version')!r}; expected '2.0'"
        )
    return content


def section(content: dict[str, Any], section_id: str) -> dict[str, Any] | None:
    for item in content.get("sections", []):
        if item.get("id") == section_id:
            return item
    return None


def questions(content: dict[str, Any], section_id: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    item = section(content, section_id)
    if not item:
        return found

    for group in item.get("groups", []):
        found.extend(group.get("questions", []))

    for passage in item.get("passages", []):
        for group in passage.get("question_groups", []):
            found.extend(group.get("questions", []))

    for question in item.get("tasks", []):
        if "task_number" in question:
            found.append(question)

    return sorted(found, key=lambda q: (q.get("number", q.get("task_number", 0))))
