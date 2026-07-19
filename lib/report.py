"""
Generates NEEDS_ATTENTION.md: a live report of exactly what's left to fill
in by hand across every mock in tests/ -- blank answers (with the PDF page
number to look them up on, when known), missing reading/writing sections,
unconfigured listening pages, and un-extracted content.

Fast: reads only manifest.json, answers/*.json, content/*.json, and the
.answer_key_meta.json breadcrumb the scaffolder leaves behind -- never
re-opens or re-scans the PDF, so this can be re-run anytime (e.g. right
after you hand-fill a few answers) to see an up-to-date checklist in
seconds.
"""
import json
import os

TESTS_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests")


def _load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _blank_questions(answers):
    """Returns sorted-by-number list of question keys with a blank value."""
    blanks = [q for q, v in answers.items() if v == "" or v == []]
    return sorted(blanks, key=lambda q: int(q) if q.isdigit() else 0)


def _ranges(nums):
    """[1,2,3,7,8,10] -> '1-3, 7-8, 10' for compact display."""
    nums = sorted(int(n) for n in nums)
    if not nums:
        return ""
    out = []
    start = prev = nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
            continue
        out.append(f"{start}-{prev}" if start != prev else f"{start}")
        start = prev = n
    out.append(f"{start}-{prev}" if start != prev else f"{start}")
    return ", ".join(out)


def _mock_report(mock_name, mock_dir):
    """Returns a list of markdown lines for one mock, or [] if it's fully complete."""
    manifest = _load_json(os.path.join(mock_dir, "manifest.json"))
    lines = []

    if manifest is None:
        return [
            f"## {mock_name}",
            "",
            "⚠️ No `manifest.json` yet (or it isn't valid JSON) -- run "
            "`python3 scripts/scaffold_mocks.py`, or check the folder has a "
            "PDF and an `audio/` folder.",
            "",
        ]

    key_meta = _load_json(os.path.join(mock_dir, ".answer_key_meta.json")) or {}
    tests = manifest.get("tests", {})
    mock_lines = []

    for test_name, cfg in tests.items():
        test_lines = []

        # --- missing sections entirely ---
        missing_sections = [s for s in ("reading", "listening", "writing") if s not in cfg]
        if missing_sections:
            test_lines.append(
                f"- **Missing section(s):** {', '.join(missing_sections)} -- "
                f"add these blocks to `manifest.json` by hand (page numbers can't "
                f"be auto-detected for whatever wasn't found in the PDF scan). "
                f"See `ANSWER_KEYS.md` / the manifest schema docstring in "
                f"`lib/test_loader.py` for the exact shape."
            )

        # --- listening parts missing pages ---
        if "listening" in cfg:
            missing_parts = [
                i + 1 for i, p in enumerate(cfg["listening"].get("parts", []))
                if not p.get("pages")
            ]
            if missing_parts:
                test_lines.append(
                    f"- **Listening part(s) {', '.join(map(str, missing_parts))}** have no "
                    f"`pages` set -- test-takers won't see the question sheet for "
                    f"these parts. Add the page numbers in `manifest.json`."
                )

        # --- reading passages missing question ranges ---
        if "reading" in cfg:
            missing_q = [
                i + 1 for i, p in enumerate(cfg["reading"].get("passages", []))
                if not p.get("questions")
            ]
            if missing_q:
                test_lines.append(
                    f"- **Reading passage(s) {', '.join(map(str, missing_q))}** have no "
                    f"`questions` range set in `manifest.json`."
                )

        # --- blank answers, with page-number hints when available ---
        for section in ("reading", "listening"):
            if section not in cfg:
                continue
            answers_path = os.path.join(mock_dir, "answers", test_name, f"{section}.json")
            answers = _load_json(answers_path)
            if answers is None:
                test_lines.append(f"- **{section.title()} answers missing entirely** (`{answers_path}` not found).")
                continue
            blanks = _blank_questions(answers)
            if blanks:
                hint = ""
                meta = key_meta.get(test_name, {}).get(section)
                if meta:
                    low_conf = meta.get("low_confidence_questions") or []
                    recovered = meta.get("recovered_via_easyocr") or []
                    low_conf_note = ""
                    if low_conf:
                        low_conf_note = (
                            f"; {len(low_conf)} of those (Q{_ranges(low_conf)}) were actually "
                            f"read but rejected for low OCR confidence rather than guessed"
                        )
                    recovered_note = ""
                    if recovered:
                        recovered_note = (
                            f"; {len(recovered)} question(s) (Q{_ranges(recovered)}) were recovered "
                            f"via a second-opinion OCR check and are already filled in"
                        )
                    hint = (
                        f" (answer key is on **page {meta['page']}** of the PDF -- "
                        f"auto-read {meta['parsed']}/{meta['total']} of them already{low_conf_note}{recovered_note})"
                    )
                test_lines.append(
                    f"- **{section.title()}: {len(blanks)} blank answer(s)** "
                    f"-- Q{_ranges(blanks)}{hint}. Fill these in "
                    f"`answers/{test_name}/{section}.json`."
                )

        # --- content extraction status ---
        content_path = os.path.join(mock_dir, "content", f"{test_name}.json")
        has_pages = any(p.get("pages") for p in cfg.get("listening", {}).get("parts", [])) or \
            any(p.get("pages") for p in cfg.get("reading", {}).get("passages", []))
        if has_pages and not os.path.isfile(content_path):
            test_lines.append(
                f"- **Text view not generated yet** for this test -- rerun "
                f"`python3 scripts/scaffold_mocks.py` to extract it (or it'll fall "
                f"back to Book view images only)."
            )

        if test_lines:
            mock_lines.append(f"### {test_name}")
            mock_lines.append("")
            mock_lines.extend(test_lines)
            mock_lines.append("")

    if not mock_lines:
        return []  # nothing to report -- fully complete, omit from the report entirely

    lines.append(f"## {mock_name}")
    lines.append("")
    lines.extend(mock_lines)
    return lines


def generate_report(tests_root=None):
    """Returns the full markdown report as a string."""
    tests_root = tests_root or TESTS_ROOT
    all_lines = []
    complete_count = 0
    total_count = 0

    if os.path.isdir(tests_root):
        for mock_name in sorted(os.listdir(tests_root)):
            mock_dir = os.path.join(tests_root, mock_name)
            if not os.path.isdir(mock_dir):
                continue
            if not os.path.isfile(os.path.join(mock_dir, "manifest.json")):
                continue  # not a scaffolded mock at all -- scaffold_mocks.py reports these separately
            total_count += 1
            section = _mock_report(mock_name, mock_dir)
            if section:
                all_lines.extend(section)
            else:
                complete_count += 1

    header = [
        "# Needs attention",
        "",
        "Auto-generated by `scripts/generate_report.py` -- reflects the current "
        "state of everything in `tests/`. Re-run that script anytime (e.g. after "
        "filling in a few answers) to get an updated list; nothing here is edited "
        "by hand.",
        "",
    ]

    if total_count == 0:
        header.append("No scaffolded mocks found in `tests/` yet.")
        return "\n".join(header) + "\n"

    if not all_lines:
        header.append(f"✅ All {total_count} mock(s) are fully filled in -- nothing left to do.")
        return "\n".join(header) + "\n"

    header.append(f"{complete_count}/{total_count} mock(s) fully complete. Remaining items below.")
    header.append("")
    return "\n".join(header + all_lines).rstrip() + "\n"
