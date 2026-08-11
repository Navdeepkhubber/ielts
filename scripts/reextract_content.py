"""Force-regenerate structured Reading/Listening content from existing manifests.

This deliberately leaves manifest.json and answers untouched. It is intended
for development/QA when the extraction logic changes and existing
content/<Test N>.json files need to be regenerated.

Examples:
    python3 scripts/reextract_content.py
    python3 scripts/reextract_content.py --mock "Cambridge 21 Test 1"
    python3 scripts/reextract_content.py --mock "Cambridge 21 Test 1" --test "Test 1"
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from lib import content_extract, pdf_render, pdf_structure

TESTS_ROOT = os.path.join(ROOT, "tests")


def _find_pdf(mock_dir):
    main = os.path.join(mock_dir, "main.pdf")
    if os.path.isfile(main):
        return main
    pdfs = sorted(
        os.path.join(mock_dir, f)
        for f in os.listdir(mock_dir)
        if f.lower().endswith(".pdf")
    )
    if len(pdfs) == 1:
        return pdfs[0]
    return None


def _load_manifest(mock_dir):
    path = os.path.join(mock_dir, "manifest.json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_content(mock_dir, test_name, content):
    out_dir = os.path.join(mock_dir, "content")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{test_name}.json")
    tmp_path = out_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(content, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp_path, out_path)
    return out_path


def reextract_mock(mock_name, test_filter=None):
    mock_dir = os.path.join(TESTS_ROOT, mock_name)
    if not os.path.isdir(mock_dir):
        raise FileNotFoundError(f"Mock folder not found: {mock_dir}")

    manifest = _load_manifest(mock_dir)
    if not manifest:
        raise FileNotFoundError(f"manifest.json not found for {mock_name}")

    pdf_path = _find_pdf(mock_dir)
    if not pdf_path:
        raise FileNotFoundError(f"Could not identify a PDF for {mock_name}")

    print(f"[{mock_name}] reading PDF text/OCR: {os.path.basename(pdf_path)}", flush=True)
    pages_text, _ = pdf_structure._page_texts(pdf_path)

    tests = manifest.get("tests", {})
    selected = [test_filter] if test_filter else list(tests.keys())
    missing = [name for name in selected if name not in tests]
    if missing:
        raise ValueError(f"Tests not found in manifest: {', '.join(missing)}")

    for test_name in selected:
        cfg = tests[test_name]
        content = content_extract.build_content_for_test(pages_text, cfg)
        path = _write_content(mock_dir, test_name, content)
        reading_count = sum(len(p.get("questions", [])) for p in content.get("reading", {}).get("passages", []))
        listening_count = sum(len(p.get("questions", [])) for p in content.get("listening", {}).get("parts", []))
        print(
            f"  {test_name}: {path} | reading questions={reading_count}, "
            f"listening questions={listening_count}",
            flush=True,
        )


def main():
    parser = argparse.ArgumentParser(description="Force-regenerate structured mock content without changing manifests or answers.")
    parser.add_argument("--mock", help="Exact mock directory name under tests/")
    parser.add_argument("--test", dest="test_name", help="Exact test name from manifest.json, e.g. 'Test 1'")
    args = parser.parse_args()

    if args.test_name and not args.mock:
        parser.error("--test requires --mock")

    if args.mock:
        reextract_mock(args.mock, args.test_name)
        return

    mock_names = sorted(
        d for d in os.listdir(TESTS_ROOT)
        if os.path.isdir(os.path.join(TESTS_ROOT, d))
    )
    for mock_name in mock_names:
        try:
            reextract_mock(mock_name)
        except (FileNotFoundError, ValueError) as exc:
            print(f"[{mock_name}] SKIPPED: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
