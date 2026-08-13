"""Repair duplicated question-group extraction in existing structured content.

Usage:
    python3 scripts/repair_content_groups.py --mock "Cambridge 21" --test "Test 1"

This is intentionally conservative. A heading such as ``Questions 1-7`` is a
question group, not seven copies of the same question text. The script removes
that duplication from an already-generated content JSON. If the OCR contains
real numbered boundaries inside the group, it splits them; otherwise it keeps
the group as one visual item instead of inventing boundaries.
"""
import argparse
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_ROOT = os.path.join(ROOT, "tests")

_GROUP_RE = re.compile(
    r"^\s*(?:questions?|qns?)\s+(\d{1,2})\s*(?:to|[-–—]|and|&)\s*(\d{1,2})\b",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(
    r"(?:^|\s)[|¦©®™*•·\-–—:;]*(\d{1,2})\s*(?:[.)/:]|(?=\s))\s+"
)


def _expected_range(value):
    if not value or len(value) != 2:
        return []
    start, end = int(value[0]), int(value[1])
    return list(range(start, end + 1)) if start <= end else []


def _split_explicit_numbers(text, start, end):
    body = re.sub(
        r"^\s*(?:questions?|qns?)\s+\d{1,2}\s*(?:to|[-–—]|and|&)\s*\d{1,2}\b",
        "",
        text,
        count=1,
        flags=re.IGNORECASE,
    ).strip()
    matches = []
    for match in _NUMBER_RE.finditer(body):
        number = int(match.group(1))
        if start <= number <= end:
            matches.append((number, match.start(), match.end()))
    matches.sort(key=lambda item: item[1])
    if len(matches) < 2:
        return None

    result = []
    for index, (number, _, end_pos) in enumerate(matches):
        next_pos = matches[index + 1][1] if index + 1 < len(matches) else len(body)
        chunk = body[end_pos:next_pos].strip(" \t\r\n-–—:*;")
        if chunk:
            result.append({"question": number, "text": chunk})
    return result or None


def _repair_section(section):
    questions = section.get("questions") or []
    if len(questions) < 2:
        return False

    configured = section.get("question_range") or section.get("questions_range")
    expected = _expected_range(configured)
    if not expected:
        return False

    groups = {}
    for question in questions:
        text = re.sub(r"\s+", " ", str(question.get("text", "")).strip())
        groups.setdefault(text, []).append(question)

    repaired = []
    changed = False
    for text, members in groups.items():
        heading = _GROUP_RE.match(text)
        if len(members) < 2 or not heading:
            repaired.extend(members)
            continue

        start, end = int(heading.group(1)), int(heading.group(2))
        split = _split_explicit_numbers(text, start, end)
        if split:
            page = members[0].get("page")
            repaired.extend({"page": page, **item} for item in split)
        else:
            # There are no trustworthy boundaries in the OCR. Do not create
            # seven identical question objects. Keep the group as one object
            # and preserve its full text for the review UI.
            repaired.append(
                {
                    "page": members[0].get("page"),
                    "question": start,
                    "question_group": [n for n in expected if start <= n <= end],
                    "text": text,
                }
            )
        changed = True

    if changed:
        repaired.sort(key=lambda item: int(item.get("question", 0)))
        section["questions"] = repaired
    return changed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", required=True)
    parser.add_argument("--test", required=True)
    args = parser.parse_args()

    path = os.path.join(TESTS_ROOT, args.mock, "content", f"{args.test}.json")
    with open(path, encoding="utf-8") as handle:
        content = json.load(handle)

    changed = False
    for section in content.get("reading", {}).get("passages", []):
        changed = _repair_section(section) or changed
    for section in content.get("listening", {}).get("parts", []):
        changed = _repair_section(section) or changed

    if changed:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(content, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        print(f"Repaired: {path}")
    else:
        print(f"No grouped-question duplication found: {path}")


if __name__ == "__main__":
    main()
