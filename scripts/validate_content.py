#!/usr/bin/env python3
"""Validate structured content files without requiring tests/* in Git."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lib.content_schema import validate_content

root = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "tests"
errors = 0
files = sorted(root.glob("**/content/Test *.json"))
if not files:
    print(f"No content files found under {root}")
for path in files:
    try:
        with path.open(encoding="utf-8") as f:
            validate_content(json.load(f))
        print(f"OK  {path}")
    except Exception as exc:
        errors += 1
        print(f"ERR {path}: {exc}")
raise SystemExit(1 if errors else 0)
