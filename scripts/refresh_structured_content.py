"""Regenerate content JSON files using the structured extraction schema."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import content_extract, pdf_structure
from lib.test_loader import TESTS_ROOT


def main():
    refreshed = 0
    for mock_name in sorted(os.listdir(TESTS_ROOT)):
        mock_dir = os.path.join(TESTS_ROOT, mock_name)
        manifest_path = os.path.join(mock_dir, "manifest.json")
        if not os.path.isdir(mock_dir) or not os.path.isfile(manifest_path):
            continue
        with open(manifest_path) as f:
            manifest = json.load(f)
        pdf_path = os.path.join(mock_dir, manifest.get("pdf_file", "main.pdf"))
        if not os.path.isfile(pdf_path):
            continue
        pages_text, _ = pdf_structure._page_texts(pdf_path, use_ocr=True)
        for test_name, test_cfg in manifest.get("tests", {}).items():
            content = content_extract.build_content_for_test(
                pages_text, test_cfg, pdf_path=pdf_path
            )
            if not content:
                continue
            out_dir = os.path.join(mock_dir, "content")
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, f"{test_name}.json")
            with open(out_path, "w") as f:
                json.dump(content, f, indent=2, ensure_ascii=False)
            refreshed += 1
            print(f"refreshed {mock_name}/{test_name}")
    print(f"Refreshed {refreshed} content file(s).")


if __name__ == "__main__":
    main()