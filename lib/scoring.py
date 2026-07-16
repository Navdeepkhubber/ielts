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
    """
    results = {}
    correct_count = 0
    for qnum, key_value in answer_key.items():
        given = user_answers.get(qnum, "")
        accepted = _accepted_set(key_value)
        is_correct = _normalize(given) in accepted and _normalize(given) != ""
        if is_correct:
            correct_count += 1
        results[qnum] = {
            "given": given,
            "correct_answer": key_value,
            "is_correct": is_correct,
        }
    total = len(answer_key)
    return {
        "results": results,
        "correct_count": correct_count,
        "total": total,
        "band_estimate": raw_score_to_band(correct_count, total, section, variant),
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
