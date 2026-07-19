"""
Standalone benchmark: compares PaddleOCR against the app's current
Tesseract-based answer-key extraction on a real answer-key page from one
of your books. Run this on your own machine (needs normal internet access
for PaddleOCR's one-time model download).

Usage:
    pip install paddleocr paddlepaddle
    python3 benchmark_paddleocr.py "tests/Cam 19/main.pdf" 119

The page number is 1-indexed -- pick an answer-key page from the back of
the book (check the [scaffold] log for "Answer key ... (page N)" lines).

Prints how many of 40 questions each engine parsed, and the raw text each
one produced, so you can eyeball which is actually more accurate rather
than just trusting a report.
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.answer_key import _parse_section_lines, _column_ocr_lines

if len(sys.argv) != 3:
    print(__doc__)
    sys.exit(1)

pdf_path = sys.argv[1]
page_1indexed = int(sys.argv[2])
page_index = page_1indexed - 1

print(f"=== Tesseract (current app engine) ===")
t0 = time.time()
tess_lines, tess_confs = _column_ocr_lines(pdf_path, page_index)
tess_parsed, tess_low_conf = _parse_section_lines(tess_lines, confidences=tess_confs) if tess_lines else ({}, [])
print(f"Time: {time.time()-t0:.1f}s | Parsed: {len(tess_parsed)}/40")

print(f"\n=== PaddleOCR ===")
try:
    import fitz
    import numpy as np
    from PIL import Image
    import io as _io
    from paddleocr import PaddleOCR

    t0 = time.time()
    ocr = PaddleOCR(use_textline_orientation=False, lang="en")
    print(f"Model load: {time.time()-t0:.1f}s")

    doc = fitz.open(pdf_path)
    page = doc[page_index]
    pix = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), colorspace=fitz.csGRAY)
    img = np.array(Image.open(_io.BytesIO(pix.tobytes("png"))).convert("RGB"))
    doc.close()

    t1 = time.time()
    result = ocr.predict(img)
    print(f"OCR time: {time.time()-t1:.1f}s")

    # Reconstruct lines using position data, same column-split approach as Tesseract
    boxes = []
    for page_result in result:
        polys = page_result.get("dt_polys") or page_result.get("rec_polys")
        texts = page_result.get("rec_texts", [])
        for poly, text in zip(polys, texts):
            x0, y0 = poly[0]
            boxes.append((x0, y0, text))

    if boxes:
        xs = sorted(b[0] for b in boxes)
        gaps = [(xs[i+1] - xs[i], (xs[i] + xs[i+1]) / 2) for i in range(len(xs)-1)]
        split_x = max(gaps)[1] if gaps and max(gaps)[0] > 80 else None

        def build_column(subset):
            subset = sorted(subset, key=lambda it: it[1])
            rows = []
            for x, y, t in subset:
                placed = False
                for row in rows:
                    if abs(row[0][1] - y) < 15:
                        row.append((x, y, t)); placed = True; break
                if not placed:
                    rows.append([(x, y, t)])
            rows.sort(key=lambda r: r[0][1])
            return [" ".join(t for x, y, t in sorted(row)) for row in rows]

        if split_x:
            paddle_lines = build_column([b for b in boxes if b[0] < split_x]) + \
                           build_column([b for b in boxes if b[0] >= split_x])
        else:
            paddle_lines = build_column(boxes)
    else:
        paddle_lines = []

    paddle_parsed, _ = _parse_section_lines(paddle_lines)
    print(f"Parsed: {len(paddle_parsed)}/40")

except ImportError as e:
    print(f"PaddleOCR not installed: {e}")
    print("Run: pip install paddleocr paddlepaddle")

print(f"\n=== Summary ===")
print(f"Tesseract: {len(tess_parsed)}/40")
try:
    print(f"PaddleOCR: {len(paddle_parsed)}/40")
except NameError:
    pass
