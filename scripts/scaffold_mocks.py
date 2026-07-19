"""
Run this any time after dumping a new Mock N folder (main.pdf + audio/Test N/
subfolders) into tests/, to auto-generate manifest.json and blank
answers/*.json files for it -- so all you have to fill in by hand is real
page numbers and real answers.

Safe to run repeatedly: never overwrites a manifest.json or answers/*.json
that already exists; only fills in what's missing.

Also (re)writes NEEDS_ATTENTION.md at the project root: a live checklist of
exactly what's left to fill in across every mock, with PDF page numbers for
blank answers where known.

    python3 scripts/scaffold_mocks.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import report, scaffold


def main():
    log = scaffold.scan_and_scaffold(verbose=False)
    if not log:
        print("Nothing to do -- every mock folder already has a manifest.json "
              "and answer files (or no mock folders with a main.pdf were found).")
    else:
        for line in log:
            print("-", line)

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    md = report.generate_report()
    with open(os.path.join(root, "NEEDS_ATTENTION.md"), "w") as f:
        f.write(md)
    print()
    print("Wrote NEEDS_ATTENTION.md -- see it for exactly what's left to fill in by hand.")


if __name__ == "__main__":
    main()
