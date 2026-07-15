"""
Renders specific PDF pages to PNG images on demand.

Deliberately does NOT extract or cache text content anywhere -- the whole
point is that the platform displays your original source pages exactly as
they are (like a page viewer), rather than re-typing passages/questions
into a database. This keeps the tool source-material-agnostic: Cambridge
book, a teacher's own worksheet, or any other PDF in the same folder
layout all work identically.
"""
import io
import os
import fitz  # PyMuPDF

_cache = {}  # (path, page_num, zoom) -> png bytes, in-memory only, cleared per process


def render_page(pdf_path, page_number, zoom=2.0):
    """page_number is 1-indexed to match how humans refer to book pages."""
    key = (pdf_path, page_number, zoom)
    if key in _cache:
        return _cache[key]

    if not os.path.isfile(pdf_path):
        raise FileNotFoundError(pdf_path)

    doc = fitz.open(pdf_path)
    try:
        idx = page_number - 1
        if idx < 0 or idx >= len(doc):
            raise IndexError(f"Page {page_number} out of range for {pdf_path} ({len(doc)} pages)")
        page = doc[idx]
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        png_bytes = pix.tobytes("png")
    finally:
        doc.close()

    _cache[key] = png_bytes
    return png_bytes


def page_count(pdf_path):
    doc = fitz.open(pdf_path)
    try:
        return len(doc)
    finally:
        doc.close()
