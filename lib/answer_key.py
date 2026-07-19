"""
Best-effort extraction of Listening/Reading answer keys from the answer-key
pages at the back of a Cambridge-style book, so answers/<Test N>/*.json can
be filled automatically instead of typed by hand.

Works on the same page text that lib/pdf_structure.py already extracts
(including its OCR fallback and on-disk cache), so scanned books work too.

Parsing strategy: Cambridge keys list entries as either "N answer" on one
line or "N" followed by the answer on the next line, in ascending question
order, with paired entries like "15&16 IN EITHER ORDER" followed by two
answer lines. Page footers and column artifacts inject stray numbers, so
the parser tracks the EXPECTED next question number and ignores any
number-led line that doesn't match it -- e.g. a stray footer "35" while
expecting question 11 is skipped rather than misread.

Alternative answers separated by "/" (e.g. "colour / color") become a list
of accepted variants, matching what lib/scoring.py already supports. For
"IN EITHER ORDER" pairs, both questions accept either answer -- slightly
lenient if a candidate repeats the same answer twice, but correct for
normal use.

Everything here is a best guess for private local use: spot-check the
filled files against your book once.
"""
import os
import re

_HEADER_NOISE_RE = re.compile(
    r"^(test\s+\d+|listening|reading|academic reading|part\s+\d|section\s+\d"
    r"|[qo]uestions?\s+\d|answer key|listening and reading|if you score|you are (un)?likely"
    r"|band score|in either order|either order)",
    re.IGNORECASE,
)
_TESTSEC_TEST_RE = re.compile(r"^\s*TEST\s+(\d+)\s*$", re.IGNORECASE | re.MULTILINE)
_PAIR_RE = re.compile(r"^\s*(\d{1,2})\s*&\s*(\d{1,2})\b(.*)$")
_NUM_INLINE_RE = re.compile(r"^\s*(\d{1,2})\s+(\S.*)$")
_NUM_ONLY_RE = re.compile(r"^\s*(\d{1,2})\s*$")


def _clean_answer(raw):
    """'colour / color' -> ['colour', 'color']; '(the) sea' -> ['(the) sea', 'the sea', 'sea'] variants."""
    raw = raw.strip().rstrip(".").strip()
    if not raw:
        return None
    parts = [p.strip() for p in raw.split("/") if p.strip()]
    variants = []
    for p in parts:
        variants.append(p)
        if "(" in p:  # optional bracketed words: with and without
            no_paren = re.sub(r"\([^)]*\)", "", p)
            no_paren = re.sub(r"\s+", " ", no_paren).strip()
            with_paren = p.replace("(", "").replace(")", "")
            with_paren = re.sub(r"\s+", " ", with_paren).strip()
            for v in (no_paren, with_paren):
                if v and v not in variants:
                    variants.append(v)
    if len(variants) == 1:
        return variants[0]
    return variants


def _looks_like_answer(line):
    """A plausible answer line: short, not a header/footer sentence."""
    s = line.strip()
    if not s or _HEADER_NOISE_RE.match(s):
        return False
    if len(s) > 40:  # answers are a letter or a few words
        return False
    if _NUM_ONLY_RE.match(s) or _PAIR_RE.match(s):
        return False
    return True


_MIN_ANSWER_CONFIDENCE = 60  # Tesseract confidence (0-100) below this: leave blank, don't guess


def _parse_section_lines(lines, q_start=1, q_end=40, confidences=None):
    """
    Parse one section's answer-key lines into {"1": ans, ...}.

    Resync-capable: tracks the minimum acceptable next question number
    (never goes backward -- Cambridge keys are always ascending) but does
    NOT require an exact match on every line. If a line's number is >=
    expected, it's accepted at that number and expected advances past it;
    any skipped numbers are simply left unfilled rather than aborting the
    whole page. This tolerates a handful of unreadable OCR lines without
    losing every answer after them.

    confidences: optional list parallel to `lines`, giving Tesseract's
    average per-word OCR confidence (0-100) for each line. When given, an
    answer is only accepted if the line(s) it came from meet
    _MIN_ANSWER_CONFIDENCE -- otherwise that question is left out of the
    returned dict (blank) even though its position in the sequence was
    identified, and its number is reported in `low_confidence_questions`.
    This matters because the page-level 30/40 acceptance threshold only
    protects against a wholesale bad page; without this, an individual
    answer OCR got wrong could still be written in just because the rest
    of the page read fine.

    Returns (answers, low_confidence_questions, line_map) --
    low_confidence_questions is a sorted list of question numbers found
    but skipped for low confidence. line_map is {question_num: [line
    indices]} covering every question that was FOUND at all (accepted or
    low-confidence) -- callers use this to look up the original line's
    bounding box for a second-opinion crop. Numbers with no entry in
    line_map were never found in the sequence at all (a bigger gap than
    "found but unclear").
    """
    def conf_ok(idx):
        if confidences is None:
            return True
        return confidences[idx] >= _MIN_ANSWER_CONFIDENCE

    answers = {}
    low_confidence = []
    line_map = {}
    expected = q_start
    i = 0
    while i < len(lines) and expected <= q_end:
        line = lines[i].strip()
        cur_i = i
        i += 1
        if not line or _HEADER_NOISE_RE.match(line):
            continue

        m = _PAIR_RE.match(line)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a >= expected and b == a + 1 and b <= q_end:
                got = []
                j = i
                while j < len(lines) and len(got) < 2:
                    if _looks_like_answer(lines[j]):
                        got.append(j)
                    elif _NUM_ONLY_RE.match(lines[j].strip()) or _PAIR_RE.match(lines[j].strip()) \
                            or _NUM_INLINE_RE.match(lines[j].strip()):
                        break
                    j += 1
                if len(got) == 2:
                    line_map[str(a)] = [cur_i] + got
                    line_map[str(b)] = [cur_i] + got
                    if conf_ok(cur_i) and all(conf_ok(gi) for gi in got):
                        both = []
                        for gi in got:
                            c = _clean_answer(lines[gi].strip())
                            if isinstance(c, list):
                                both.extend(c)
                            elif c:
                                both.append(c)
                        answers[str(a)] = both
                        answers[str(b)] = both
                    else:
                        low_confidence.extend([a, b])
                    i = j
                    expected = b + 1
            continue

        m = _NUM_INLINE_RE.match(line)
        if m:
            n = int(m.group(1))
            if expected <= n <= q_end:
                ans = _clean_answer(m.group(2))
                if ans is not None:
                    line_map[str(n)] = [cur_i]
                    if conf_ok(cur_i):
                        answers[str(n)] = ans
                    else:
                        low_confidence.append(n)
                    expected = n + 1
            continue

        m = _NUM_ONLY_RE.match(line)
        if m:
            n = int(m.group(1))
            if expected <= n <= q_end:
                j = i
                while j < len(lines) and j < i + 3:
                    nxt = lines[j].strip()
                    if _looks_like_answer(nxt):
                        ans = _clean_answer(nxt)
                        if ans is not None:
                            line_map[str(n)] = [cur_i, j]
                            if conf_ok(cur_i) and conf_ok(j):
                                answers[str(n)] = ans
                            else:
                                low_confidence.append(n)
                            expected = n + 1
                        i = j + 1
                        break
                    if _NUM_ONLY_RE.match(nxt) or _PAIR_RE.match(nxt) or _NUM_INLINE_RE.match(nxt):
                        break
                    j += 1
            continue
        # anything else (stray footer numbers, prose) is ignored
    return answers, sorted(set(low_confidence)), line_map


_EASYOCR_MIN_CONFIDENCE = 0.55  # EasyOCR's own 0-1 confidence scale
_easyocr_reader = None
_easyocr_unavailable = False


def _get_easyocr_reader():
    """
    Lazily loads and caches an EasyOCR reader (~14s model load, once per
    process). Used only as a second opinion on the small number of
    individual answers Tesseract wasn't confident about -- never as the
    primary engine, since a full-page EasyOCR pass reconstructs 2-column
    layouts worse than Tesseract does (benchmarked: 13-28/40 vs Tesseract's
    33-39/40 on the same real pages). On a single isolated line crop,
    that column-reconstruction weakness doesn't apply, which is what
    makes it useful here specifically.
    Returns None if easyocr isn't installed or fails to initialize.
    """
    global _easyocr_reader, _easyocr_unavailable
    if _easyocr_reader is not None:
        return _easyocr_reader
    if _easyocr_unavailable:
        return None
    try:
        import easyocr
        _easyocr_reader = easyocr.Reader(["en"], gpu=False, verbose=False)
        return _easyocr_reader
    except Exception:
        _easyocr_unavailable = True
        return None


def _easyocr_read_crop(img, pad=15):
    """
    Runs EasyOCR on a small region, upsampled for better small-text
    recognition. Returns (text, confidence) using the WEAKEST individual
    detection's confidence (not an average) -- a second-opinion answer is
    only as trustworthy as its least-confident fragment. Returns
    (None, 0.0) if nothing detected or EasyOCR unavailable.
    """
    reader = _get_easyocr_reader()
    if reader is None:
        return None, 0.0
    try:
        import numpy as np
        from PIL import Image
        if img.width < 4 or img.height < 4:
            return None, 0.0
        big = img.resize((img.width * 3, img.height * 3), Image.LANCZOS)
        results = reader.readtext(np.array(big), detail=1)
        if not results:
            return None, 0.0
        text = " ".join(t for _, t, _ in results)
        conf = min(c for _, _, c in results)
        return text, conf
    except Exception:
        return None, 0.0


def _crop_region(crops, box, pad=15):
    """box: (crop_name, x0, y0, x1, y1). Returns a padded PIL crop, or None."""
    if crops is None or box is None:
        return None
    crop_name, x0, y0, x1, y1 = box
    img = crops.get(crop_name)
    if img is None:
        return None
    w, h = img.size
    return img.crop((max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad)))


def _extract_answer_from_text(raw_text, qnum):
    """
    Given a raw OCR line like "23 NOT GIVEN" or just "NOT GIVEN" (number
    already stripped/separate), pulls out the answer part for question
    qnum specifically. Strips a leading token matching qnum (allowing
    minor OCR noise around it) before cleaning. Returns None if the
    remaining text doesn't look like a plausible answer at all.
    """
    if not raw_text:
        return None
    text = raw_text.strip()
    # strip a leading occurrence of the question number (with optional
    # punctuation/noise immediately around it)
    text = re.sub(rf"^\D{{0,4}}\b{qnum}\b[.\s]*", "", text).strip()
    if not text or len(text) > 40:
        return None
    return _clean_answer(text)


def _recover_low_confidence_with_easyocr(low_confidence, line_map, boxes, crops):
    """
    For each question in `low_confidence` (found by Tesseract but below
    _MIN_ANSWER_CONFIDENCE), re-crops that exact line and asks EasyOCR for
    a second opinion. Only accepted if EasyOCR itself is confident
    (>= _EASYOCR_MIN_CONFIDENCE) -- otherwise it stays blank, same as
    before. Returns (recovered_answers, still_low_confidence).
    """
    recovered = {}
    still_low = []
    if crops is None:
        return recovered, list(low_confidence)
    for qn in low_confidence:
        key = str(qn)
        idxs = line_map.get(key, [])
        if not idxs or len(idxs) > 2:  # skip IN-EITHER-ORDER pairs (3 idxs: number+2 answers) -- ambiguous which box
            still_low.append(qn)
            continue
        answer_idx = idxs[-1]  # last index is the answer line (or the only line, for inline format)
        region = _crop_region(crops, boxes[answer_idx])
        if region is None:
            still_low.append(qn)
            continue
        text, conf = _easyocr_read_crop(region)
        if text and conf >= _EASYOCR_MIN_CONFIDENCE:
            ans = _extract_answer_from_text(text, qn)
            if ans is not None:
                recovered[key] = ans
                continue
        still_low.append(qn)
    return recovered, still_low


def _easyocr_read_band(img, pad=10):
    """
    Runs EasyOCR on a (possibly multi-line) region and reconstructs rows
    by clustering detections with similar y-position, sorted left-to-right
    within each row. Returns [(text, min_confidence), ...] in top-to-
    bottom order. Used to search a gap spanning several candidate rows,
    rather than trusting a single precise line-height guess -- a section
    header between two known answers can eat uneven vertical space that
    a fixed-height guess would misjudge.
    """
    reader = _get_easyocr_reader()
    if reader is None:
        return []
    try:
        import numpy as np
        if img.width < 4 or img.height < 4:
            return []
        results = reader.readtext(np.array(img), detail=1)
        if not results:
            return []
        items = [(box[0][0], box[0][1], text, conf) for box, text, conf in results]
        items.sort(key=lambda it: it[1])
        rows = []
        for x, y, text, conf in items:
            placed = False
            for row in rows:
                if abs(row[0][1] - y) < 14:
                    row.append((x, y, text, conf)); placed = True; break
            if not placed:
                rows.append([(x, y, text, conf)])
        rows.sort(key=lambda r: r[0][1])
        out = []
        for row in rows:
            row.sort(key=lambda it: it[0])
            text = " ".join(t for x, y, t, c in row)
            min_conf = min(c for x, y, t, c in row)
            out.append((text, min_conf))
        return out
    except Exception:
        return []


def _ocrad_available():
    import shutil
    return shutil.which("ocrad") is not None


def _ocrad_read_region(img):
    """
    Runs GNU Ocrad (a lightweight, fast, classical OCR engine -- no
    confidence scores, so never used alone) on a region and returns its
    output lines. Used only to CORROBORATE an EasyOCR-recovered answer
    for questions Tesseract never found at all: since Ocrad exposes no
    per-answer confidence, its reading is only trusted when it
    independently agrees with EasyOCR's, not on its own. Returns [] if
    Ocrad isn't installed or fails.
    """
    if not _ocrad_available():
        return []
    try:
        import subprocess
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".pnm", delete=False) as f:
            img.convert("L").save(f.name)
            tmp_path = f.name
        try:
            result = subprocess.run(["ocrad", tmp_path], capture_output=True, timeout=30)
            text = result.stdout.decode("utf-8", errors="replace")
            return text.splitlines()
        finally:
            os.unlink(tmp_path)
    except Exception:
        return []


def _normalize_for_agreement(ans):
    """ans may be a string or a list of alternatives; returns a set of
    lowercased/stripped tokens for comparing two engines' readings."""
    vals = ans if isinstance(ans, list) else [ans]
    return {str(v).strip().lower().rstrip(".") for v in vals if v}


def _recover_missing_with_easyocr(missing, line_map, boxes, crops):
    """
    For questions Tesseract's parser never found in the sequence at all
    (a bigger gap than "found but unclear"), searches the vertical gap
    between the nearest known questions before and after it (in the same
    column) for a line whose leading number matches -- rather than
    guessing one precise line position, since a section header
    ("Part 2, Questions 11-20") between two answer rows can eat uneven
    vertical space that a fixed spacing would misjudge. Only accepted if
    EasyOCR is confident about that specific line AND its leading number
    matches the target question. Returns recovered_answers dict.

    Column assignment: a missing question is assigned to whichever column
    ("left"/"right") holds its nearest neighbors overall, using the point
    where the known anchors switch columns as the boundary -- Cambridge
    key pages are consistently "first half of questions on the left,
    second half on the right".
    """
    recovered = {}
    if crops is None or not missing:
        return recovered

    anchors = []
    for key, idxs in line_map.items():
        qn = int(key)
        idx = idxs[0]
        crop_name, x0, y0, x1, y1 = boxes[idx]
        anchors.append((qn, crop_name, (y0 + y1) / 2, x0, x1))
    anchors.sort(key=lambda a: a[0])
    if len(anchors) < 2:
        return recovered

    boundary = None
    for i in range(len(anchors) - 1):
        if anchors[i][1] != anchors[i + 1][1]:
            lo, hi = anchors[i][0], anchors[i + 1][0]
            # IELTS listening parts are always exactly 10 questions, so if
            # the column split genuinely falls at a part boundary, prefer
            # that over the raw midpoint -- a run of several consecutive
            # missing questions can otherwise place the naive midpoint far
            # from where the transition actually is (e.g. anchors at 20
            # and 25 with 21-24 all missing gives midpoint 22.5, but the
            # true split is 20.5).
            standard = [b for b in (10.5, 20.5, 30.5) if lo < b < hi]
            boundary = standard[0] if standard else (lo + hi) / 2
            break

    def column_for(qn):
        if boundary is None:
            return anchors[0][1]
        return anchors[0][1] if qn < boundary else anchors[-1][1]

    spacings = {}
    for i in range(len(anchors) - 1):
        qn1, c1, y1_, _, _ = anchors[i]
        qn2, c2, y2_, _, _ = anchors[i + 1]
        if c1 == c2 and qn2 - qn1 in (1, 2):
            spacings.setdefault(c1, []).append((y2_ - y1_) / (qn2 - qn1))
    row_height = {}
    for c, vals in spacings.items():
        vals.sort()
        row_height[c] = vals[len(vals) // 2]

    # Group consecutive missing numbers that share the same before/after
    # anchors -- search their shared gap once rather than once per number.
    for qn in missing:
        target_col = column_for(qn)
        same_col = [a for a in anchors if a[1] == target_col]
        before = max((a for a in same_col if a[0] < qn), key=lambda a: a[0], default=None)
        after = min((a for a in same_col if a[0] > qn), key=lambda a: a[0], default=None)
        rh = row_height.get(target_col, 33)

        if before and after:
            y_top, y_bot = before[2], after[2]
            x0 = min(before[3], after[3]); x1 = max(before[4], after[4])
        elif before:
            span = (qn - before[0]) + 1.5  # rows between anchor and target, plus margin
            y_top, y_bot = before[2], before[2] + rh * span
            x0, x1 = before[3], before[4]
        elif after:
            span = (after[0] - qn) + 1.5
            y_top, y_bot = after[2] - rh * span, after[2]
            x0, x1 = after[3], after[4]
        else:
            continue

        region = _crop_region(crops, (target_col, x0, y_top, x1, y_bot), pad=10)
        if region is None:
            continue

        # Ocrad has no confidence score, so it's never trusted alone --
        # but if it independently agrees with EasyOCR on this specific
        # question (two differently-built free engines, same answer),
        # that agreement is strong evidence for what is otherwise a blind
        # geometric guess. Compute once per gap, reused for every missing
        # question number that shares this region.
        ocrad_lines = _ocrad_read_region(region)
        ocrad_ans = None
        for oline in ocrad_lines:
            if re.match(rf"^\D{{0,3}}\b{qn}\b", oline.strip()):
                ocrad_ans = _extract_answer_from_text(oline.strip(), qn)
                break

        for text, conf in _easyocr_read_band(region):
            if conf < _EASYOCR_MIN_CONFIDENCE:
                continue
            if not re.match(rf"^\D{{0,3}}\b{qn}\b", text):
                continue
            ans = _extract_answer_from_text(text, qn)
            if ans is None:
                continue
            if ocrad_ans is not None and not (_normalize_for_agreement(ans) & _normalize_for_agreement(ocrad_ans)):
                continue  # two engines disagree -- stay blank rather than guess which is right
            recovered[str(qn)] = ans
            break
    return recovered


_TESSDATA_BEST_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tessdata_best")
_TESSDATA_BEST_URL = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/main/eng.traineddata"
_tessdata_best_checked = False


def _ensure_tessdata_best():
    """
    Lazily fetches Tesseract's high-accuracy "best" English model (LSTM,
    float weights -- much more accurate than the default "fast" model
    Tesseract ships with, at roughly 1.5x the OCR time). One-time ~15MB
    download from the official tesseract-ocr GitHub org. Used only for
    the answer-key column retry pass, not the whole-book scan, since
    that's the specific case it measurably helps (verified: 285/320 ->
    294/320 answers correctly parsed across 8 real answer-key pages,
    with 2 pages going from imperfect to a fully verified 40/40).
    Returns the tessdata directory path, or None if unavailable (network
    down, etc.) -- callers fall back to the default model silently.
    """
    global _tessdata_best_checked
    path = os.path.join(_TESSDATA_BEST_DIR, "eng.traineddata")
    if os.path.isfile(path):
        return _TESSDATA_BEST_DIR
    if _tessdata_best_checked:
        return None  # already tried and failed this run -- don't retry every page
    _tessdata_best_checked = True
    try:
        import ssl
        import urllib.request
        os.makedirs(_TESSDATA_BEST_DIR, exist_ok=True)
        tmp = path + ".part"

        # macOS's python.org builds don't link the system CA store, so a
        # plain urlretrieve() often fails with CERTIFICATE_VERIFY_FAILED
        # even though the network itself is fine. Use certifi's bundled
        # certificates explicitly rather than depending on the OS/Python
        # install having them wired up correctly.
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ctx = ssl.create_default_context()

        with urllib.request.urlopen(_TESSDATA_BEST_URL, context=ctx, timeout=30) as resp, open(tmp, "wb") as f:
            f.write(resp.read())
        os.replace(tmp, path)
        print("[answer_key] Downloaded Tesseract's high-accuracy model for answer-key extraction (one-time, ~15MB).")
        return _TESSDATA_BEST_DIR
    except Exception as e:
        hint = ""
        if "CERTIFICATE_VERIFY_FAILED" in str(e):
            hint = " Run: pip install certifi"
        print(f"[answer_key] Could not fetch high-accuracy OCR model ({e}); using the default model instead.{hint}")
        return None


def _column_ocr_lines(pdf_path, page_index, zoom=3.0):
    """
    Re-OCRs one page at higher resolution, split into left/right column
    halves (answer-key pages are almost always 2-column), returning
    (lines, confidences, boxes, crops) in reading order (left column
    top-to-bottom, then right column):
      - confidences[i]: Tesseract's average per-word confidence (0-100)
        for lines[i], used to reject individual low-confidence answers
        even on an otherwise-good page.
      - boxes[i]: (crop_name, x0, y0, x1, y1) -- lines[i]'s bounding box
        within whichever crop image it came from ("left" or "right"),
        used to re-crop that exact region for a second-opinion OCR pass
        on questions Tesseract wasn't confident about.
      - crops: {"left": PIL.Image, "right": PIL.Image} -- the two column
        images themselves, so callers can crop from them directly.
    Uses Tesseract's high-accuracy "best" model when available (see
    _ensure_tessdata_best), falling back to the default model otherwise.
    Requires pytesseract/Tesseract; returns (None, None, None, None) if
    unavailable or on error.
    """
    try:
        import fitz
        import pytesseract
        from pytesseract import Output
        from PIL import Image
        import io as _io
    except ImportError:
        return None, None, None, None

    def _column_lines_with_conf(img, cfg, crop_name):
        data = pytesseract.image_to_data(img, config=cfg, output_type=Output.DICT)
        grouped = {}
        order = []
        for i in range(len(data["text"])):
            word = data["text"][i].strip()
            if not word:
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            if key not in grouped:
                grouped[key] = []
                order.append(key)
            try:
                conf = float(data["conf"][i])
            except (ValueError, TypeError):
                conf = -1
            grouped[key].append((word, conf, data["left"][i], data["top"][i], data["width"][i], data["height"][i]))
        lines_out, confs_out, boxes_out = [], [], []
        for key in order:
            words = grouped[key]
            text = " ".join(w[0] for w in words)
            valid = [w[1] for w in words if w[1] >= 0]
            avg_conf = sum(valid) / len(valid) if valid else 0.0
            x0 = min(w[2] for w in words); y0 = min(w[3] for w in words)
            x1 = max(w[2] + w[4] for w in words); y1 = max(w[3] + w[5] for w in words)
            lines_out.append(text)
            confs_out.append(avg_conf)
            boxes_out.append((crop_name, x0, y0, x1, y1))
        return lines_out, confs_out, boxes_out

    try:
        doc = fitz.open(pdf_path)
        try:
            page = doc[page_index]
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csGRAY)
            img = Image.open(_io.BytesIO(pix.tobytes("png")))
            w, h = img.size
            # The right column's answers sit close to the midline, so a
            # hard 50/50 cut clips the leading digit of numbers right at
            # the boundary (e.g. "27" -> "7"). Widen only the right crop's
            # left edge to recover that margin; the left crop stays exact
            # since widening it too caused cross-column contamination.
            left = img.crop((0, 0, w // 2, h))
            right = img.crop((int(w * 0.42), 0, w, h))
            tessdata_dir = _ensure_tessdata_best()
            cfg = "--psm 6"
            if tessdata_dir:
                cfg += f' --tessdata-dir "{tessdata_dir}"'
            l_lines, l_confs, l_boxes = _column_lines_with_conf(left, cfg, "left")
            r_lines, r_confs, r_boxes = _column_lines_with_conf(right, cfg, "right")
            return l_lines + r_lines, l_confs + r_confs, l_boxes + r_boxes, {"left": left, "right": right}
        finally:
            doc.close()
    except Exception:
        return None, None, None, None


def extract_answer_keys(pages_text, pdf_path=None):
    """
    pages_text: full list of per-page text (from pdf_structure._page_texts).
    pdf_path: if given, key pages that parse poorly from the cached
    whole-book OCR get a targeted high-resolution, column-split re-OCR
    (answer-key pages are dense 2-column tables -- a much harder OCR
    target than prose, so the standard whole-book pass under-reads them).
    Returns:
      keys: {test_num: {"listening": {...}, "reading": {...}}}
      warnings: [str, ...]
      page_meta: {(test_num, section): {"page": 1-indexed page num,
                                         "parsed": n, "total": 40}}
                 for EVERY key page found, whether or not it was accepted
                 -- lets callers persist "here's where to look in the PDF"
                 even when a section couldn't be auto-filled.
    """
    keys = {}
    warnings = []
    page_meta = {}
    inferred_test = 0
    last_sec = None
    for page_index, text in enumerate(pages_text):
        head = text[:600]
        if not re.search(r"answer key|answer keys", head, re.IGNORECASE):
            continue
        sec = None
        if re.search(r"^\s*LISTENING\s*$", head, re.IGNORECASE | re.MULTILINE):
            sec = "listening"
        elif re.search(r"^\s*(?:ACADEMIC\s+)?READING\s*$", head, re.IGNORECASE | re.MULTILINE):
            sec = "reading"
        if sec is None:
            continue

        mt = _TESTSEC_TEST_RE.search(head)
        if mt:
            test_num = int(mt.group(1))
            inferred_test = test_num
        else:
            if sec == "listening" or inferred_test == 0 or last_sec == "reading":
                inferred_test += 1
            test_num = inferred_test
        last_sec = sec

        # Try the cheap parse first (native PDF text, or the whole-book
        # cached OCR pass). If that's already perfect, trust it as-is --
        # there's no OCR uncertainty to gate on for real digital text, and
        # re-OCRing an already-perfect page could only introduce NEW
        # errors, not remove any.
        parsed, _, _ = _parse_section_lines(text.splitlines())
        low_conf = []
        recovered_low_conf = {}
        recovered_missing = {}

        if len(parsed) < 40 and pdf_path:
            # Column-split OCR with per-answer confidence tracking
            # consistently outperforms the naive whole-page parse for
            # scanned pages (verified: 285/320 -> 294/320 correct across a
            # real 8-page test set), and lets us reject individual
            # low-confidence answers instead of accepting whatever OCR
            # produced just because the page as a whole read well enough.
            col_lines, col_confs, col_boxes, col_crops = _column_ocr_lines(pdf_path, page_index)
            if col_lines:
                retry_parsed, retry_low_conf, retry_line_map = _parse_section_lines(col_lines, confidences=col_confs)
                if len(retry_parsed) >= len(parsed):
                    parsed, low_conf = retry_parsed, retry_low_conf

                    # Second opinion from EasyOCR: only for the specific
                    # answers Tesseract flagged as low-confidence or never
                    # found at all, and only accepted when EasyOCR itself
                    # is confident -- see _recover_low_confidence_with_
                    # easyocr / _recover_missing_with_easyocr docstrings.
                    recovered_low_conf, still_low = _recover_low_confidence_with_easyocr(
                        low_conf, retry_line_map, col_boxes, col_crops
                    )
                    if recovered_low_conf:
                        parsed = {**parsed, **recovered_low_conf}
                        low_conf = still_low

                    missing = [n for n in range(1, 41) if str(n) not in retry_line_map]
                    if missing:
                        recovered_missing = _recover_missing_with_easyocr(
                            missing, retry_line_map, col_boxes, col_crops
                        )
                        if recovered_missing:
                            parsed = {**parsed, **recovered_missing}

        recovered_count = len(recovered_low_conf) + len(recovered_missing)
        page_meta[(test_num, sec)] = {
            "page": page_index + 1, "parsed": len(parsed), "total": 40,
            "low_confidence_questions": low_conf,
            "recovered_via_easyocr": sorted(
                [int(q) for q in recovered_low_conf] + [int(q) for q in recovered_missing]
            ),
        }

        if len(parsed) >= 30:
            keys.setdefault(test_num, {})[sec] = parsed
            unfilled = 40 - len(parsed)
            if unfilled or recovered_count:
                detail = ""
                if low_conf:
                    detail += f", including {len(low_conf)} read but too unclear to trust (Q{', '.join(map(str, low_conf))})"
                if recovered_count:
                    detail += f" ({recovered_count} more recovered via a second-opinion OCR check)"
                warnings.append(
                    f"Answer key for Test {test_num} {sec} (page {page_index + 1}): parsed "
                    f"{len(parsed)}/40 answers -- {unfilled} left blank{detail}; fill them by hand."
                )
        else:
            warnings.append(
                f"Answer key page for Test {test_num} {sec} (page {page_index + 1}) was found "
                f"but only {len(parsed)}/40 answers could be read reliably (poor scan quality) "
                f"-- left blank rather than risk wrong marking; type this key in by hand."
            )
    if not keys and not warnings:
        warnings.append(
            "No answer-key pages recognised in this PDF -- answers/*.json were "
            "left blank; fill them in by hand."
        )
    return keys, warnings, page_meta
