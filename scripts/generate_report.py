"""
Regenerates NEEDS_ATTENTION.md from the current state of tests/ -- no PDF
scanning, just reads manifest.json / answers/*.json / content/*.json, so
it's fast and safe to run anytime, e.g. right after you've hand-filled a
few answers, to see what's left.

    python3 scripts/generate_report.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import report


def main():
    md = report.generate_report()
    out_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "NEEDS_ATTENTION.md")
    with open(out_path, "w") as f:
        f.write(md)
    print(f"Wrote {out_path}")
    print()
    print(md)


if __name__ == "__main__":
    main()
