"""Import public KeenIELTS answer keys into local mock answer files."""

import argparse
import json
import re
import urllib.request
from pathlib import Path

import fitz


CHECK_URL_RE = re.compile(
    r"https?://[^\s<>\]\)\"']+/check/(reading|listening)/([A-Za-z0-9_-]+)"
)
TEST_NUMBER_RE = re.compile(r"Test\s+(\d+)$", re.IGNORECASE)


def ordered_check_links(pdf_path):
    """Return unique reading/listening check links in PDF page order."""
    links = []
    seen = set()
    document = fitz.open(pdf_path)
    for page in document:
        for skill, module_slug in CHECK_URL_RE.findall(page.get_text()):
            key = (skill, module_slug)
            if key not in seen:
                seen.add(key)
                links.append(key)
    return links


def fetch_answer_key(skill, module_slug):
    url = f"https://keenielts.com/api/ieltstest/public/results/{skill}/{module_slug}/"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; IELTS content importer)",
            "Referer": f"https://keenielts.com/check/{skill}/{module_slug}",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    answers = {
        str(item["n"]): item["answer"]
        for item in payload.get("answer_key", [])
        if "n" in item and "answer" in item
    }
    return payload, answers


def test_number(test_name):
    match = TEST_NUMBER_RE.search(test_name)
    return int(match.group(1)) if match else None


def import_mock(mock_dir):
    manifest_path = mock_dir / "manifest.json"
    pdf_path = mock_dir / "main.pdf"
    if not manifest_path.is_file() or not pdf_path.is_file():
        return 0, 0, "skipped"

    manifest = json.loads(manifest_path.read_text())
    test_names = sorted(
        manifest.get("tests", {}),
        key=lambda name: (test_number(name) is None, test_number(name) or name),
    )
    links_by_skill = {"reading": [], "listening": []}
    for skill, module_slug in ordered_check_links(pdf_path):
        if module_slug not in [slug for _, slug in links_by_skill[skill]]:
            links_by_skill[skill].append((skill, module_slug))

    written = 0
    skipped = 0
    for skill, links in links_by_skill.items():
        for index, (_, module_slug) in enumerate(links):
            if index >= len(test_names):
                skipped += 1
                continue
            test_name = test_names[index]
            try:
                payload, answers = fetch_answer_key(skill, module_slug)
            except Exception as error:
                print(f"  {skill} {module_slug}: {error}")
                skipped += 1
                continue
            remote_test = payload.get("test", "")
            answer_path = mock_dir / "answers" / test_name / f"{skill}.json"
            if not answer_path.is_file() or not answers:
                skipped += 1
                continue
            local_answers = json.loads(answer_path.read_text())
            local_answers.update({key: value for key, value in answers.items() if key in local_answers})
            answer_path.write_text(json.dumps(local_answers, indent=2) + "\n")
            written += len(answers)
            print(f"  {test_name} {skill}: {len(answers)} answers ({remote_test})")
    return written, skipped, "processed"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tests-root", type=Path, default=Path("tests"))
    args = parser.parse_args()

    total_written = 0
    total_skipped = 0
    for mock_dir in sorted(args.tests_root.iterdir()):
        if not mock_dir.is_dir():
            continue
        written, skipped, state = import_mock(mock_dir)
        if state == "processed":
            print(f"{mock_dir.name}: {written} written, {skipped} skipped")
        total_written += written
        total_skipped += skipped
    print(f"Total: {total_written} answers written, {total_skipped} skipped")


if __name__ == "__main__":
    main()