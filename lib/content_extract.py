"""Layout-faithful PDF extraction for the IELTS text view.

The old extractor converted PDF text into prose. This module deliberately does
not do that. It keeps the PDF's page geometry and text spans, so the browser can
recreate the printed page as HTML: headings stay where they are, tables retain
rows/columns, and multi-column question sheets don't collapse into a text wall.
"""
import json
import os
import re
import fitz

SCHEMA_VERSION = 3
_BRAND_RE = re.compile(r"(?:keenielts\.com|Practice smarter\.\s*Score higher)", re.I)
_SECTION_HEADER_RE = re.compile(r"^(?:Test\s+\d+|Listening|Reading|Writing|Academic Reading)\s*$", re.I)
_RUNNING_HEADER_RE = re.compile(r"C\s*A\s*M\s*B\s*R\s*I\s*D\s*G\s*E.*P\s*R\s*A\s*C\s*T\s*I\s*C\s*E", re.I)
_FOOTER_RE = re.compile(r"^Cambridge\s+IELTS\s+\d+.*(?:Academic|General Training).*\d{1,3}$", re.I)
_PAGE_NUMBER_RE = re.compile(r"^\s*\d{1,3}\s*$")
_GAP_RE = re.compile(r"^\s*(\d{1,2})\s*(?:[.…·]{3,}|_{3,})\s*$")
_INLINE_GAP_RE = re.compile(r"\b(\d{1,2})\s*(?:[.…·]{3,}|_{3,})")

def _norm(text):
    return re.sub(r"\s+", " ", text or "").strip()

def _is_noise(span, page):
    text = _norm(span.get("text", ""))
    if not text or _BRAND_RE.search(text) or _SECTION_HEADER_RE.match(text):
        return True
    y0 = span["bbox"][1]
    if y0 < page.rect.height * 0.10 and _RUNNING_HEADER_RE.search(text):
        return True
    if y0 > page.rect.height * 0.90 and (_PAGE_NUMBER_RE.match(text) or _FOOTER_RE.match(text)):
        return True
    return False

def _font_style(span):
    flags = int(span.get("flags", 0)); font = (span.get("font") or "").lower()
    return (bool(flags & 16) or "bold" in font or "semibold" in font or "heavy" in font,
            bool(flags & 2) or "italic" in font or "oblique" in font)

def _span_payload(span):
    bold, italic = _font_style(span)
    return {"bbox":[round(v,2) for v in span["bbox"]],"text":span.get("text",""),"size":round(float(span.get("size",10)),2),"font":span.get("font"),"bold":bold,"italic":italic,"color":int(span.get("color",0))}

def _extract_page(page, page_number, q_from=None, q_to=None):
    spans=[]; answer_boxes=[]
    for block in page.get_text("dict").get("blocks",[]):
        if "lines" not in block: continue
        for line in block.get("lines",[]):
            for raw in line.get("spans",[]):
                if _is_noise(raw,page): continue
                payload=_span_payload(raw); spans.append(payload); text=payload["text"]
                matches=[]
                m=_GAP_RE.match(text)
                if m: matches=[int(m.group(1))]
                else: matches=[int(x.group(1)) for x in _INLINE_GAP_RE.finditer(text)]
                for q in matches:
                    if (q_from is None or q>=q_from) and (q_to is None or q<=q_to):
                        answer_boxes.append({"question":q,"bbox":payload["bbox"],"mode":"inline_gap"})
    return {"page":page_number,"width":round(page.rect.width,2),"height":round(page.rect.height,2),"spans":spans,"answer_boxes":answer_boxes}

def _page_numbers_for_test(test_cfg):
    reading=[]
    for p in test_cfg.get("reading",{}).get("passages",[]): reading.extend((pg,p["questions"]) for pg in p.get("pages",[]))
    listening=[]
    for p in test_cfg.get("listening",{}).get("parts",[]): listening.extend((pg,p["questions"]) for pg in p.get("pages",[]))
    writing=[]
    for task in ("task1","task2"):
        pg=test_cfg.get("writing",{}).get(task,{}).get("page")
        if pg: writing.append((pg,None))
    return reading,listening,writing

def _build_pages(pdf_path, refs):
    document=fitz.open(pdf_path)
    try:
        pages=[]; seen=set()
        for page_number,qrange in refs:
            if page_number in seen or not 1<=page_number<=len(document): continue
            seen.add(page_number)
            pages.append(_extract_page(document[page_number-1],page_number,*(qrange or (None,None))))
        pages.sort(key=lambda p:p["page"]); return pages
    finally: document.close()

def build_content_for_test(pages_text, test_cfg, pdf_path=None):
    if not pdf_path: raise ValueError("pdf_path is required for layout extraction")
    reading,listening,writing=_page_numbers_for_test(test_cfg)
    return {"schema_version":SCHEMA_VERSION,"renderer":"pdf-layout-html","reading":{"pages":_build_pages(pdf_path,reading)},"listening":{"pages":_build_pages(pdf_path,listening)},"writing":{"pages":_build_pages(pdf_path,writing)}}

def scaffold_content_files(mock_dir, manifest, pages_text, log, mock_name, pdf_path=None):
    os.makedirs(os.path.join(mock_dir,"content"),exist_ok=True)
    for test_name,test_cfg in manifest.get("tests",{}).items():
        out_path=os.path.join(mock_dir,"content",f"{test_name}.json")
        try:
            source_pdf=pdf_path or os.path.join(mock_dir,manifest.get("pdf_file","main.pdf"))
            if not os.path.isfile(source_pdf):
                log.append(f"[{mock_name}/{test_name}] layout extraction skipped: PDF missing"); continue
            content=build_content_for_test(pages_text,test_cfg,pdf_path=source_pdf)
            existing_version=None
            if os.path.isfile(out_path):
                try:
                    with open(out_path,encoding="utf-8") as f: existing_version=json.load(f).get("schema_version")
                except (OSError,ValueError): pass
            if existing_version != SCHEMA_VERSION:
                with open(out_path,"w",encoding="utf-8") as f: json.dump(content,f,ensure_ascii=False,separators=(",",":"))
                log.append(f"[{mock_name}/{test_name}] generated layout-faithful content/{test_name}.json (schema {SCHEMA_VERSION})")
            else: log.append(f"[{mock_name}/{test_name}] layout content already current")
        except Exception as exc: log.append(f"[{mock_name}/{test_name}] layout extraction failed: {exc}")
