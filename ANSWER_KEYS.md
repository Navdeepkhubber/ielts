# Adding answer keys by hand

Auto-scaffolding fills in as much of `answers/<Test Name>/reading.json` and
`listening.json` as it can confidently read from your book's printed answer
key. Whatever it can't read reliably, it leaves **blank** rather than risk
silently marking a test wrong — that's a deliberate safety choice, not a bug.

This guide covers everything you need to fill in the rest by hand: where
the files live, the exact format, and the specific rules the scorer
(`lib/scoring.py`) uses to mark an answer right or wrong.

---

## 1. Where the files are

```
tests/<Your Mock>/answers/<Test Name>/reading.json
tests/<Your Mock>/answers/<Test Name>/listening.json
```

Each file is a flat JSON object: question number (as a string) → correct
answer.

```json
{
  "1": "TRUE",
  "2": "TRUE",
  "3": "cotton",
  "4": ""
}
```

- Keys are **strings**, even though they're numbers — `"1"`, not `1`. This
  matches how JSON round-trips through JavaScript in the app; using a bare
  number will still often work but keep it quoted to be safe.
- An empty string `""` means "not answered yet" — this is what the
  auto-scaffolder leaves behind for anything it couldn't read. The scorer
  treats a blank the same as if the test-taker left it blank: **always
  marked wrong**, never skipped or ignored. So don't leave real gaps as
  `""` — fill them in, or that question can never be scored correct.

---

## 2. How to find the real answer

1. Open your book's PDF and go to the **"Listening and Reading Answer
   Keys"** section (almost always near the very back, often just before or
   mixed in with the tapescripts).
2. Find the block for the right test number and section (e.g. "TEST 3,
   LISTENING").
3. Match the question number to the printed answer.

If you're not sure which page that is, check the terminal output from
`scripts/scaffold_mocks.py` — any answer it couldn't confidently read
prints a line telling you the exact page:

```
Answer key page for Test 3 reading (page 121) was found but only 24/40
answers could be read reliably (poor scan quality) -- left blank rather
than risk wrong marking; type this key in by hand.
```

Go to page 121, read off the answers the log says it couldn't get.

---

## 3. Formats the scorer actually understands

This is the part worth reading carefully — matching is **case-insensitive
and forgives punctuation/whitespace differences, but does not forgive
spelling** (exactly like real IELTS marking: British/American spelling
variants are only accepted if you list both).

### Single answer
```json
"1": "TRUE"
```
Works for: True/False/Not Given, Yes/No/Not Given, multiple-choice letters
(`"A"`, `"B"`...), and single-word/short-phrase fill-ins.

The comparison lowercases both sides and strips a trailing full stop and
surrounding whitespace before comparing. So `"True"`, `"TRUE "`, and
`"true."` in the key all behave identically, and a test-taker typing
`"true"` or `"True."` will still be marked correct against a key of
`"TRUE"`.

### Multiple choice with letter-only answers
```json
"5": "C"
```
Just the letter. Don't write `"C. some option text"` — the scorer compares
literally, so `"C"` only matches a test-taker's exact input of `C`.

### Accepted alternatives (spelling variants, synonyms the key allows)
```json
"9": ["colour", "color"]
```
Use a list when the book's key itself lists more than one acceptable
answer (Cambridge usually writes this as `colour / color` or similar on
the page). Any one of the list matches. This is also how the answer-key
auto-extractor stores "IN EITHER ORDER" paired questions — see below.

### "IN EITHER ORDER" pairs
When the book says two questions can be answered in either order (common
in multiple-choice "choose TWO letters" tasks), **both question numbers
get the same list of both accepted values**:
```json
"15": ["B", "E"],
"16": ["B", "E"]
```
This means a test-taker who put `B` for Q15 and `E` for Q16 is correct,
and so is one who put `E` for Q15 and `B` for Q16 — either arrangement
scores both questions right, matching how IELTS itself marks these.

### Numbers
```json
"22": "1990"
```
Just the digits as a string. If the book accepts a written-out form too
(rare, but it happens for things like "69 / sixty-nine"), list both:
```json
"22": ["69", "sixty-nine"]
```

### Blank / not yet filled in
```json
"30": ""
```
This is the auto-scaffolder's placeholder for "couldn't read this one."
Leave it as `""` only until you've actually typed the real answer in —
don't leave it blank thinking it'll be skipped in scoring, because it
won't be; it always counts as wrong until filled in.

---

## 4. What NOT to do

- **Don't include the question text or option text** — only the answer
  itself. `"1": "A) increased significantly"` will never match anything a
  test-taker types; use `"1": "A"`.
- **Don't add extra keys** the manifest doesn't expect (e.g. a 41st
  question) — harmless, but pointless; the scorer only ever looks up
  questions the manifest configured (`question` ranges in
  `manifest.json`), and never validates a file's total key count against
  anything sensible on its own.
- **Don't remove the quotes around question numbers** — `1: "TRUE"` is
  invalid JSON and will break the whole file, taking down that entire
  section (every question), not just the one you were editing.
- **Watch your commas** — JSON is strict: no trailing comma after the
  last item in the object. If you paste a bunch of lines from the book and
  the last one has a trailing comma, the file won't parse and the section
  will fail to load entirely (you'll typically see an error/empty results
  when starting that section in the app).

---

## 5. Validate before you trust it

After editing, check the file is valid JSON before you sit the test —
a syntax error silently breaks the whole section rather than just one
question. Run this from your project folder, swapping in your actual
path:

```bash
python3 -c "import json; json.load(open('tests/Your Mock/answers/Test 1/listening.json'))" && echo "valid JSON"
```

If that prints an error instead of `valid JSON`, it'll tell you the line
number to go fix.

---

## 6. Quick reference

| Question type | Example value |
|---|---|
| True/False/Not Given | `"TRUE"` |
| Yes/No/Not Given | `"NO"` |
| Multiple choice | `"C"` |
| Short answer / fill-in | `"cotton"` |
| Spelling variants allowed | `["colour", "color"]` |
| "In either order" pair (both questions) | `["B", "E"]` on both question numbers |
| Number | `"1990"` |
| Not filled in yet | `""` |

---

## 7. Re-running the scaffolder won't erase your edits

`scripts/scaffold_mocks.py` (and the automatic scan at app startup) never
overwrites an `answers/*.json` file that already exists — it only ever
*fills blanks* (`""` entries) if it manages to extract more from the PDF
on a later run, and never touches anything you've typed in yourself. So
it's always safe to re-run it after adding a new mock, even if you've
already hand-corrected some answers in an existing one.
