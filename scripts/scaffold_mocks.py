"""
Run this any time after dumping a new Mock N folder (main.pdf + audio/Test N/
subfolders) into tests/, to auto-generate manifest.json and blank
answers/*.json files for it -- so all you have to fill in by hand is real
page numbers and real answers.

Safe to run repeatedly: never overwrites a manifest.json or answers/*.json
that already exists; only fills in what's missing.

    python3 scripts/scaffold_mocks.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import scaffold


def main():
    log = scaffold.scan_and_scaffold(verbose=False)
    if not log:
        print("Nothing to do -- every mock folder already has a manifest.json "
              "and answer files (or no mock folders with a main.pdf were found).")
        return
    for line in log:
        print("-", line)


if __name__ == "__main__":
    main()
