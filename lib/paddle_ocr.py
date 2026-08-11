"""Optional, memory-bounded PaddleOCR adapter for scanned IELTS pages."""
import gc
import re

_OCR = None


def _get_ocr():
    global _OCR
    if _OCR is not None:
        return _OCR
    try:
        from paddleocr import PaddleOCR
    except ImportError:
        return None
    _OCR = PaddleOCR(
        lang="en",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )
    return _OCR


def _result_payload(result):
    payload = getattr(result, "json", None)
    if callable(payload):
        payload = payload()
    if isinstance(payload, dict):
        return payload.get("res", payload)
    if isinstance(result, dict):
        return result.get("res", result)
    return {}


def _reading_order_lines(payload):
    texts = payload.get("rec_texts") or []
    boxes = payload.get("rec_boxes") or []
    scores = payload.get("rec_scores") or []
    if not texts or not boxes:
        return []

    rows = []
    for idx, text in enumerate(texts):
        text = re.sub(r"\s+", " ", str(text or "")).strip()
        if not text:
            continue
        try:
            box = boxes[idx]
            x0, y0, x1, y1 = [float(v) for v in box]
            score = float(scores[idx]) if idx < len(scores) else 1.0
        except (IndexError, TypeError, ValueError):
            continue
        rows.append({"text": text, "x": x0, "y": y0, "bottom": y1, "score": score})

    heights = sorted(max(1.0, r["bottom"] - r["y"]) for r in rows)
    tolerance = max(8.0, heights[len(heights) // 2] * 0.65)
    rows.sort(key=lambda r: (r["y"], r["x"]))
    lines = []
    for row in rows:
        center = row["y"] + (row["bottom"] - row["y"]) / 2
        target = None
        for line in reversed(lines):
            if abs(center - line["center"]) <= tolerance:
                target = line
                break
            if center - line["center"] > tolerance * 2:
                break
        if target is None:
            lines.append({"center": center, "rows": [row]})
        else:
            target["rows"].append(row)
            target["center"] = sum(r["y"] + (r["bottom"] - r["y"]) / 2 for r in target["rows"]) / len(target["rows"])

    lines.sort(key=lambda line: line["center"])
    return [" ".join(r["text"] for r in sorted(line["rows"], key=lambda r: r["x"])) for line in lines]


def ocr_page(image_path):
    """OCR exactly one page and release result references immediately."""
    ocr = _get_ocr()
    if ocr is None:
        return []
    try:
        results = ocr.predict(image_path)
        lines = []
        for result in results:
            lines.extend(_reading_order_lines(_result_payload(result)))
        del results
        gc.collect()
        return lines
    except Exception:
        gc.collect()
        return []
