"""
Generates a small SYNTHETIC demo mock (original placeholder text, not
Cambridge or any copyrighted content) so you can see the "Mock folder with
one main.pdf + per-test audio folders" convention in action, before wiring
up your own real, non-copyrighted material in the exact same layout.

Run: python3 scripts/make_demo_test.py
"""
import json
import os
import subprocess
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOCK_DIR = os.path.join(ROOT, "tests", "Mock Demo")


def _wrap(text, width):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines


def add_text_page(c, title, paragraphs):
    width, height = A4
    y = height - 2 * cm
    c.setFont("Helvetica-Bold", 14)
    c.drawString(2 * cm, y, title)
    y -= 1 * cm
    c.setFont("Helvetica", 10)
    for para in paragraphs:
        for line in _wrap(para, 90):
            c.drawString(2 * cm, y, line)
            y -= 0.5 * cm
        y -= 0.3 * cm
    c.showPage()


def make_tone_mp3(path, seconds=15, freq=440):
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}",
        "-q:a", "9", path
    ], check=True, capture_output=True)


def main():
    audio_dir = os.path.join(MOCK_DIR, "audio", "Test 1")
    answers_dir = os.path.join(MOCK_DIR, "answers", "Test 1")
    os.makedirs(audio_dir, exist_ok=True)
    os.makedirs(answers_dir, exist_ok=True)

    # --- Build one main.pdf with everything for "Test 1" ---
    pdf_path = os.path.join(MOCK_DIR, "main.pdf")
    c = canvas.Canvas(pdf_path, pagesize=A4)

    # Page 1-2: Reading passage 1
    add_text_page(c, "Reading Passage 1: The Life Cycle of a Placeholder", [
        "This is placeholder passage text generated only to demonstrate the "
        "'Mock folder + single main.pdf' pipeline. Replace this PDF with your "
        "own non-copyrighted book laid out the same way (one main.pdf covering "
        "all reading/listening/writing material for every test in the book).",
    ])
    add_text_page(c, "Questions 1-5", [
        "1. This text is a demonstration placeholder. (TRUE/FALSE/NOT GIVEN)",
        "2. The pipeline renders PDF pages as images. (TRUE/FALSE/NOT GIVEN)",
        "3. Answer keys live in a separate answers/ folder. (TRUE/FALSE/NOT GIVEN)",
        "4. The word used to describe this file's purpose is ______.",
        "5. This demo uses ______ generated content.",
    ])

    # Page 3: Listening Part 1 question sheet (diagram/MCQ placeholder)
    add_text_page(c, "Listening Part 1 — Questions 1-2 — page 3", [
        "1. This is a placeholder multiple-choice question. What does this demo "
        "page represent? A) A reading passage  B) A listening question sheet  "
        "C) A writing prompt",
        "2. Fill in the blank: the audio player sits ______ to this page so "
        "test-takers can see the diagram/options while they listen.",
    ])

    # Page 4: Writing Task 1 prompt
    add_text_page(c, "Writing Task 1 (demo) — page 4", [
        "Describe the trend shown in a placeholder chart (imagine a line graph "
        "here). Synthetic prompt for pipeline testing only.",
    ])
    # Page 5: Writing Task 2 prompt
    add_text_page(c, "Writing Task 2 (demo) — page 5", [
        "Some people believe placeholder text is useful for testing software. "
        "Others disagree. Discuss both views and give your own opinion.",
    ])

    c.save()

    # --- Listening audio for Test 1 ---
    make_tone_mp3(os.path.join(audio_dir, "part1.mp3"), seconds=15, freq=440)

    # --- Answer keys ---
    with open(os.path.join(answers_dir, "reading.json"), "w") as f:
        json.dump({
            "1": "TRUE", "2": "TRUE", "3": "TRUE",
            "4": ["placeholder", "demo"], "5": "synthetic",
        }, f, indent=2)
    with open(os.path.join(answers_dir, "listening.json"), "w") as f:
        json.dump({"1": "A", "2": "tone test"}, f, indent=2)

    # --- manifest.json ---
    manifest = {
        "mock_name": "Mock Demo (synthetic content)",
        "pdf_file": "main.pdf",
        "tests": {
            "Test 1": {
                "reading": {
                    "duration_minutes": 5,
                    "passages": [
                        {"pages": [1, 2], "questions": [1, 5]}
                    ],
                },
                "listening": {
                    "audio_folder": "Test 1",
                    "parts": [
                        {"file": "part1.mp3", "questions": [1, 2], "pages": [3]}
                    ],
                },
                "writing": {
                    "task1": {"page": 4, "duration_minutes": 2},
                    "task2": {"page": 5, "duration_minutes": 2},
                },
            }
        },
    }
    with open(os.path.join(MOCK_DIR, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"Demo mock created at {MOCK_DIR}")


if __name__ == "__main__":
    main()
