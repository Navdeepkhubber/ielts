# IELTS Practice Platform

A self-hosted practice platform for Reading, Listening, and Writing — timed,
auto-marked, with progress tracking over time. It works with **any** test
material laid out in the folder convention below, so you can point it at
your own non-copyrighted PDFs/audio and reuse the exact same structure for
every mock you add.

## Why it works this way (a note on copyright)

Rather than extracting and re-typing passages/questions into a database
(which would mean duplicating a book's actual content), the platform
**renders your original PDF pages as images** and **streams your original
audio files** directly — like a page/audio viewer with a timer and
answer-sheet wrapped around it. The only data it stores per test is:

- page numbers (a "map" of where things are in the book)
- the answer key (short factual answers, e.g. `"1": "TRUE"`)

This is a deliberate design choice: it keeps the tool source-material-agnostic
and avoids reproducing anyone's copyrighted book content — you supply the
material, in whatever legal form you have it, and the app just adds the
exam experience around it.

## Setup

```bash
pip install -r requirements.txt
# Optional, for AI-graded writing feedback:
pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-...   # get one at console.anthropic.com

python3 app.py
# -> open http://localhost:5050
```

A demo mock with synthetic placeholder content is included so you can try
the flow immediately. Regenerate it any time with:

```bash
python3 scripts/make_demo_test.py
```

## Folder convention

Each **mock** (book) is one folder with a single `main.pdf` covering
everything in that book, plus audio split out per individual test:

```
tests/                              <- primary root
  Mock 19/
    main.pdf                         <- the WHOLE book: every reading passage,
                                         question sheet, listening question
                                         sheet, and writing prompt, for all
                                         4 tests, exactly as printed.
    audio/
      Test 1/
        part1.mp3
        part2.mp3
        part3.mp3
        part4.mp3
      Test 2/
        part1.mp3
        ...
      Test 3/
      Test 4/
    answers/
      Test 1/
        reading.json                 <- {"1": "TRUE", ...}
        listening.json
      Test 2/
        reading.json
        listening.json
      Test 3/
      Test 4/
    manifest.json                    <- maps each Test N to page/audio refs
  Mock 20/
    main.pdf
    audio/...
    answers/...
    manifest.json
```

You can have as many `Mock N` folders as you like under `tests/` — each one
shows up as its own card on the home screen, and opening it lists whichever
of Test 1-4 it defines.

### manifest.json

One manifest per mock, describing every test inside that book:

```json
{
  "mock_name": "Cambridge Mock 19",
  "pdf_file": "main.pdf",
  "tests": {
    "Test 1": {
      "reading": {
        "duration_minutes": 60,
        "passages": [
          {"pages": [5, 6, 7], "questions": [1, 13]},
          {"pages": [8, 9, 10], "questions": [14, 26]},
          {"pages": [11, 12, 13, 14], "questions": [27, 40]}
        ]
      },
      "listening": {
        "audio_folder": "Test 1",
        "parts": [
          {"file": "part1.mp3", "questions": [1, 10]},
          {"file": "part2.mp3", "questions": [11, 20]},
          {"file": "part3.mp3", "questions": [21, 30]},
          {"file": "part4.mp3", "questions": [31, 40]}
        ]
      },
      "writing": {
        "task1": {"page": 20, "duration_minutes": 20},
        "task2": {"page": 21, "duration_minutes": 40}
      }
    },
    "Test 2": { "...": "same shape" },
    "Test 3": { "...": "same shape" },
    "Test 4": { "...": "same shape" }
  }
}
```

- `pages` / `page` are 1-indexed page numbers **within the single shared
  `main.pdf`** — so as you move from Test 1 to Test 2 to Test 3 etc. within
  the same book, the page numbers just keep climbing (e.g. Test 1 might be
  pages 5-22, Test 2 pages 23-40, and so on) rather than resetting.
- `questions` is `[first_question_number, last_question_number]` (inclusive)
  for that passage/part, used to generate the right number of answer boxes.
- `audio_folder` names the subfolder under `audio/` for that test (so audio
  files for different tests never clash even if they're all named
  `part1.mp3`, `part2.mp3`, etc.).
- Any section (`reading` / `listening` / `writing`) can be omitted from a
  test if you don't have material for it — the buttons on the test card
  only show up for sections that exist.

### answers/&lt;Test N&gt;/reading.json and listening.json

```json
{
  "1": "TRUE",
  "2": "C",
  "3": "cotton",
  "4": ["colour", "color"]
}
```

Plain string = single accepted answer. Array = multiple accepted spellings/
variants. Matching is case-insensitive and ignores a trailing full stop, but
otherwise exact — spelling mistakes are marked wrong unless you list the
variant explicitly.

Writing has no answer key — instead it's graded by an AI feedback pass (if
`ANTHROPIC_API_KEY` is set) giving indicative band scores across the four
official criteria, or you can self/teacher-mark from your stored submission.

## Timing behaviour

- **Reading**: hard 60-minute (or whatever you set) countdown, auto-submits
  on expiry.
- **Listening**: audio-paced with unlimited replay of each part (adjust in
  `static/js/app.js` if you want stricter single-play enforcement), then a
  10-minute transfer-time countdown before final auto-submit — matching real
  exam conditions.
- **Writing**: per-task countdown (20 / 40 min defaults), auto-submits on
  expiry.

## Progress tracking

Every attempt is logged to a local SQLite database at `data/progress.db`
(created automatically) — mock, test, section, score, band estimate, and
time taken. View it under the "Progress" tab in the app, or query it
directly:

```python
from lib import storage
storage.history()                            # everything
storage.history(test_id="Mock 19::Test 1")    # one specific test
```

## Project structure

```
app.py                  Flask server + API routes
lib/
  test_loader.py         scans tests/ folder, reads manifest/answer keys
  pdf_render.py           renders main.pdf pages to PNG on demand (no text extraction/caching to disk)
  scoring.py               auto-marking + rough band conversion
  storage.py                SQLite progress history
  writing_feedback.py        optional AI feedback via Anthropic API
templates/index.html    page shell
static/js/app.js         all frontend logic (mock list, test list, exam flow, timer, results, dashboard)
static/css/style.css
scripts/make_demo_test.py  generates the synthetic demo mock
tests/                    your mock folders go here
```

## Extending

- **Question types**: the current answer sheet is a single text input per
  question, which covers TFNG/YNNG, matching, fill-in-blank, and short
  answer. For multiple choice you can type the letter; if you want native
  radio buttons/dropdowns, extend `startReading`/`startListening` in
  `app.js` to branch on a `type` field you add per question in the manifest.
- **Single-play listening**: real exams only play listening audio once.
  To enforce that, disable the `controls` attribute and drive play/pause
  from a single "Play Part N" button instead, in the listening section of
  `app.js`.
- **Multi-user**: storage is currently a single local SQLite file (single
  user, local machine). For multiple users, swap in a per-user key in
  `storage.py` or point it at a shared database.

