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


def _parse_section_lines(lines, q_start=1, q_end=40):
    """
    Parse one section's answer-key lines into {"1": ans, ...}.
    Tracks the expected next question number to reject stray footer numbers.
    """
    answers = {}
    expected = q_start
    i = 0
    while i < len(lines) and expected <= q_end:
        line = lines[i].strip()
        i += 1
        if not line or _HEADER_NOISE_RE.match(line):
            continue

        m = _PAIR_RE.match(line)
        if m and int(m.group(1)) == expected:
            a, b = int(m.group(1)), int(m.group(2))
            # collect the next two answer-looking lines
            got = []
            j = i
            while j < len(lines) and len(got) < 2:
                if _looks_like_answer(lines[j]):
                    got.append(lines[j].strip())
                elif _NUM_ONLY_RE.match(lines[j].strip()) or _PAIR_RE.match(lines[j].strip()):
                    break  # ran into the next question -- give up on this pair
                j += 1
            if len(got) == 2:
                both = []
                for g in got:
                    c = _clean_answer(g)
                    if isinstance(c, list):
                        both.extend(c)
                    elif c:
                        both.append(c)
                for q in (a, b):
                    answers[str(q)] = both
                i = j
                expected = b + 1
            continue

        m = _NUM_INLINE_RE.match(line)
        if m and int(m.group(1)) == expected:
            ans = _clean_answer(m.group(2))
            if ans is not None:
                answers[str(expected)] = ans
                expected += 1
            continue

        m = _NUM_ONLY_RE.match(line)
        if m and int(m.group(1)) == expected:
            # answer is on the next answer-looking line
            j = i
            while j < len(lines):
                nxt = lines[j].strip()
                if _looks_like_answer(nxt):
                    ans = _clean_answer(nxt)
                    if ans is not None:
                        answers[str(expected)] = ans
                        expected += 1
                    i = j + 1
                    break
                if _NUM_ONLY_RE.match(nxt) or _PAIR_RE.match(nxt) or _NUM_INLINE_RE.match(nxt):
                    break  # next question arrived before an answer -- skip
                j += 1
            else:
                break
            continue
        # anything else (stray footer numbers, prose) is ignored
    return answers


def extract_answer_keys(pages_text):
    """
    pages_text: full list of per-page text (from pdf_structure._page_texts).
    Returns ({test_num: {"listening": {...}, "reading": {...}}}, warnings).

    Key pages are identified by their "answer key" header plus a
    LISTENING/READING marker. The "TEST N" number is used when readable;
    when OCR garbles it ("TES", "TEST" with no digit), the test number is
    inferred from page order, since Cambridge prints keys strictly as
    Test 1 Listening, Test 1 Reading, Test 2 Listening, ...

    A section's key is only accepted when at least 30/40 answers parsed
    cleanly: a partially-garbled key would silently mis-mark tests, which
    is worse than leaving the file blank for hand-filling.
    """
    keys = {}
    warnings = []
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
            # Header unreadable (common in scans): infer from order --
            # a listening page starts the next test; a reading page
            # belongs to the current one.
            if sec == "listening" or inferred_test == 0 or last_sec == "reading":
                inferred_test += 1
            test_num = inferred_test
        last_sec = sec

        parsed = _parse_section_lines(text.splitlines())
        if len(parsed) >= 30:
            keys.setdefault(test_num, {})[sec] = parsed
            if len(parsed) < 40:
                warnings.append(
                    f"Answer key for Test {test_num} {sec} (page {page_index + 1}): parsed "
                    f"{len(parsed)}/40 answers -- the rest were left blank; fill them by hand."
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
    return keys, warnings
