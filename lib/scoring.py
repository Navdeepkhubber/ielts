"""
Auto-marking for Reading & Listening.

answers.json values can be:
  "TRUE"                              -> single accepted answer
  ["colour", "color"]                 -> list of accepted alternatives (spelling variants etc.)

Matching is case-insensitive and ignores surrounding whitespace / a trailing
full stop, which mirrors how IELTS answer keys are usually marked leniently
for minor formatting differences (NOT for spelling errors, which are marked
strict beyond registered alternatives).
"""

# Rough band conversion tables (Academic). These are commonly published
# approximate conversions, not official IELTS scoring -- always treat as
# indicative only.
_LISTENING_READING_BANDS = [
    (39, 9.0), (37, 8.5), (35, 8.0), (33, 7.5), (30, 7.0),
    (27, 6.5), (23, 6.0), (19, 5.5), (15, 5.0), (13, 4.5),
    (10, 4.0), (8, 3.5), (6, 3.0), (4, 2.5), (0, 0.0),
]


def _normalize(ans):
    if ans is None:
        return ""
    return str(ans).strip().rstrip(".").lower()


def _accepted_set(key_value):
    if isinstance(key_value, list):
        return {_normalize(v) for v in key_value}
    return {_normalize(key_value)}


def mark_section(user_answers: dict, answer_key: dict):
    """
    user_answers / answer_key: {"1": "TRUE", "2": "cotton", ...}
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
        "band_estimate": raw_score_to_band(correct_count),
    }


def raw_score_to_band(correct_count):
    for threshold, band in _LISTENING_READING_BANDS:
        if correct_count >= threshold:
            return band
    return 0.0
