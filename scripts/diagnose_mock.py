"""
Diagnoses why a mock's PDF isn't auto-detecting: dumps every heading-like
line the scan can see, per page, so the detection patterns can be tuned to
that book's actual layout. Uses the existing .pdf_text_cache.json when
present, so it's instant for already-scanned books (no re-OCR).

    python3 scripts/diagnose_mock.py "Mock 9"

Paste the output when asking for detection support for a book format that
isn't being recognized -- it shows the layout without needing the PDF.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import pdf_structure

TESTS_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests")

# Lines worth showing: anything resembling a structural heading in ANY
# common IELTS book layout, plus short ALL-CAPS lines (often headings).
_INTERESTING = re.compile(
    r"^\s*(?:practice\s+)?test\s*\d+|"
    r"^\s*(?:section|part)\s*\d+|"
    r"^\s*reading\s+passage|"
    r"^\s*writing\s+task|"
    r"^\s*[qo]uestions?\s+\d+|"
    r"^\s*(listening|reading|writing|speaking|academic|answer)\b|"
    r"^\s*tapescript|^\s*audioscript",
    re.IGNORECASE,
)
_SHORT_CAPS = re.compile(r"^\s*[A-Z][A-Z0-9\s'.,\-:]{2,50}\s*$")


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        mocks = sorted(d for d in os.listdir(TESTS_ROOT) if os.path.isdir(os.path.join(TESTS_ROOT, d)))
        print("Available mocks:", ", ".join(mocks))
        sys.exit(1)

    mock = sys.argv[1]
    mock_dir = os.path.join(TESTS_ROOT, mock)
    if not os.path.isdir(mock_dir):
        print(f"No such mock folder: {mock_dir}")
        sys.exit(1)

    pdfs = [f for f in os.listdir(mock_dir) if f.lower().endswith(".pdf")]
    if not pdfs:
        print(f"No PDF found in {mock_dir}")
        sys.exit(1)
    pdf_path = os.path.join(mock_dir, "main.pdf" if "main.pdf" in pdfs else pdfs[0])

    audio_root = os.path.join(mock_dir, "audio")
    audio_dirs = sorted(os.listdir(audio_root)) if os.path.isdir(audio_root) else []
    print(f"=== {mock} ===")
    print(f"PDF: {os.path.basename(pdf_path)}")
    print(f"Audio folders: {audio_dirs or '(none)'}")

    texts, ocr_count = pdf_structure._page_texts(pdf_path)
    n = len(texts)
    text_pages = sum(1 for t in texts if len(t.strip()) >= 20)
    print(f"Pages: {n} | with readable text: {text_pages} | OCR'd this run: {ocr_count}")
    print()
    print("Heading-like lines per page (first 4 per page shown):")
    print("-" * 70)
    for i, text in enumerate(texts):
        hits = []
        for line in text.splitlines():
            s = line.strip()
            if not s or len(s) > 60:
                continue
            if _INTERESTING.match(s) or _SHORT_CAPS.match(s):
                hits.append(s)
            if len(hits) >= 4:
                break
        if hits:
            print(f"p{i+1}: " + " | ".join(repr(h) for h in hits))
    print("-" * 70)
    print(f"\nDone. Paste everything above when reporting a book that isn't detecting.")


if __name__ == "__main__":
    main()
