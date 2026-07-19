"""
Auto-marking for Reading & Listening.

answers.json values can be:
  "TRUE"                              -> single accepted answer
  ["colour", "color"]                 -> list of accepted alternatives (spelling variants etc.)

Matching is case-insensitive and ignores surrounding whitespace / a trailing
full stop, which mirrors how IELTS answer keys are usually marked leniently
for minor formatting differences (NOT for spelling errors, which are marked
strict beyond registered alternatives).

Band conversion:
IELTS has never published official raw-score-to-band tables -- the mapping
varies slightly between test versions to account for difficulty. The tables
below are the standard published approximations (the same ones Cambridge's
own practice books print as guidance), with the correct distinctions that
official scoring makes:
  - Listening and Reading use DIFFERENT tables.
  - Academic Reading and General Training Reading use different tables
    (GT is markedly stricter). Set "variant": "general" on a test in
    manifest.json to use the GT reading table; the default is academic.
All bands produced here are indicative, exactly like every practice
platform's -- treat them as a close estimate, not an official score.

Tables assume the standard 40-question section. Sections with fewer
questions (partial/sectional practice) are scaled to a 40-question
equivalent before conversion, which keeps the estimate sensible but makes
it even more approximate.
"""

# (min_raw_score_out_of_40, band)
_LISTENING_BANDS = [
    (39, 9.0), (37, 8.5), (35, 8.0), (32, 7.5), (30, 7.0),
    (26, 6.5), (23, 6.0), (18, 5.5), (16, 5.0), (13, 4.5),
    (10, 4.0), (8, 3.5), (6, 3.0), (4, 2.5), (0, 0.0),
]

_READING_ACADEMIC_BANDS = [
    (39, 9.0), (37, 8.5), (35, 8.0), (33, 7.5), (30, 7.0),
    (27, 6.5), (23, 6.0), (19, 5.5), (15, 5.0), (13, 4.5),
    (10, 4.0), (8, 3.5), (6, 3.0), (4, 2.5), (0, 0.0),
]

_READING_GENERAL_BANDS = [
    (40, 9.0), (39, 8.5), (37, 8.0), (36, 7.5), (34, 7.0),
    (32, 6.5), (30, 6.0), (27, 5.5), (23, 5.0), (19, 4.5),
    (15, 4.0), (12, 3.5), (9, 3.0), (6, 2.5), (0, 0.0),
]


def _normalize(ans):
    if ans is None:
        return ""
    return str(ans).strip().rstrip(".").lower()


def _accepted_set(key_value):
    if isinstance(key_value, list):
        return {_normalize(v) for v in key_value}
    return {_normalize(key_value)}


def mark_section(user_answers: dict, answer_key: dict, section="reading", variant="academic"):
    """
    user_answers / answer_key: {"1": "TRUE", "2": "cotton", ...}
    section: "reading" or "listening" -- selects the correct band table.
    variant: "academic" (default) or "general" -- GT uses a stricter
             reading table; listening is identical across variants.
    Returns per-question results + a total score.

    If the answer key is entirely blank (auto-extraction couldn't read it
    and it hasn't been filled by hand yet), the attempt is returned as
    "unmarked": the person's answers are still recorded per question so
    they can self-mark against the book, but no misleading 0/40 score or
    band is produced.
    """
    key_is_blank = all(v == "" or v == [] for v in answer_key.values()) if answer_key else True
    if key_is_blank:
        return {
            "unmarked": True,
            "results": {
                q: {"given": user_answers.get(q, ""), "correct_answer": "", "is_correct": None}
                for q in answer_key
            },
            "correct_count": None,
            "total": len(answer_key),
            "band_estimate": None,
        }

    results = {}
    correct_count = 0
    markable_total = 0
    for qnum, key_value in answer_key.items():
        given = user_answers.get(qnum, "")
        if key_value == "" or key_value == []:
            # Key not filled in for this question yet: record the answer
            # but don't mark it right or wrong, and exclude it from the
            # score denominator -- fairer than counting it as a miss.
            results[qnum] = {"given": given, "correct_answer": "", "is_correct": None}
            continue
        markable_total += 1
        accepted = _accepted_set(key_value)
        is_correct = _normalize(given) in accepted and _normalize(given) != ""
        if is_correct:
            correct_count += 1
        results[qnum] = {
            "given": given,
            "correct_answer": key_value,
            "is_correct": is_correct,
        }
    return {
        "results": results,
        "correct_count": correct_count,
        "total": markable_total,
        "unmarkable_count": len(answer_key) - markable_total,
        "band_estimate": raw_score_to_band(correct_count, markable_total, section, variant),
    }


def band_explanation(correct_count, total=40, section="reading", variant="academic"):
    """
    Same lookup as raw_score_to_band, but returns the full working instead
    of just the final number -- which table was used, the raw and scaled
    score, and every threshold in that table with the matched one marked --
    so a "how was this calculated" UI can show its work rather than just
    asserting a band.
    """
    if section == "listening":
        table, table_name = _LISTENING_BANDS, "Listening"
    elif variant == "general":
        table, table_name = _READING_GENERAL_BANDS, "General Training Reading"
    else:
        table, table_name = _READING_ACADEMIC_BANDS, "Academic Reading"

    scaled = correct_count if total == 40 else (
        round(correct_count / total * 40) if total else 0
    )
    matched_threshold, band = 0, 0.0
    for threshold, b in table:
        if scaled >= threshold:
            matched_threshold, band = threshold, b
            break

    return {
        "correct_count": correct_count,
        "total": total,
        "scaled_score": scaled,
        "was_scaled": total != 40,
        "table_name": table_name,
        "table": [{"threshold": t, "band": b} for t, b in table],
        "matched_threshold": matched_threshold,
        "band": band,
    }


def raw_score_to_band(correct_count, total=40, section="reading", variant="academic"):
    if section == "listening":
        table = _LISTENING_BANDS
    elif variant == "general":
        table = _READING_GENERAL_BANDS
    else:
        table = _READING_ACADEMIC_BANDS

    # Scale partial sections to a 40-question equivalent.
    scaled = correct_count if total == 40 else (
        round(correct_count / total * 40) if total else 0
    )
    for threshold, band in table:
        if scaled >= threshold:
            return band
    return 0.0
