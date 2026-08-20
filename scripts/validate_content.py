#!/usr/bin/env python3
"""Validate all structured IELTS content files in tests/.

Usage:
    python3 scripts/validate_content.py
    python3 scripts/validate_content.py tests/IELTS21/content/Test\ 1.json
"""
import glob
import os
import sys

from lib.content_schema import validate_file


def main() -> int:
    paths = sys.argv[1:]
    if not paths:
        paths = glob.glob(os.path.join("tests", "*", "content", "Test *.json"))

    if not paths:
        print("No structured content files found.")
        return 0

    failed = False
    for path in sorted(paths):
        errors = validate_file(path)
        if errors:
            failed = True
            print(f"FAIL {path}")
            for error in errors:
                print(f"  - {error}")
        else:
            print(f"OK   {path}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
