# Mock Test JSON Schema v2

## Why this replaces the old format

The old `Test_N.json` files stored one flat OCR `text` blob per page plus a
`questions[]` array whose `text` field was just a slice of that same OCR
string. Because OCR reads a page in top-to-bottom, left-to-right stream
order, it interleaves table columns, note bullets and question numbers that
are visually side-by-side or nested — e.g. Test 1 Q1 came out as:

    "place 1. people) Level 1 basic theory e.g. £200 a6 : understanding the the end of the"

That is four different table cells glued together. No downstream formatting
of that string can recover the real table. So v2 does not store OCR reading
order at all. Each question group is transcribed directly from the page
image into a **typed block**, with the real layout (table rows/columns,
note bullets, boxed option lists, etc.) as structured data, and the blank
numbers as explicit `{{n}}` placeholders inside the block's text/cells.
Answers live in one place (`answer_key`) and are referenced by question
number, never duplicated inside the block.

## Top-level shape

```jsonc
{
  "mock_name": "Mock 21",
  "test_name": "Test 1",
  "listening": { "parts": [ Part, Part, Part, Part ] },
  "reading":   { "passages": [ Passage, Passage, Passage ] },
  "writing":   { "task1": Task1, "task2": Task2 }
}
```

## Block types (used in both listening parts and reading passages)

Every block has:
- `id` — stable slug, e.g. `t1-listening-p1-q1-6`
- `type` — one of the types below
- `page` — source PDF page number
- `instructions` — `{ "range": "Questions 1–6", "text": "...", "word_limit": "..." }`
  as printed on the page (word_limit only present when the task states one)

### `table-completion`
```jsonc
{
  "type": "table-completion",
  "table": {
    "title": "Oyster Bay Sailing Club Courses",
    "headers": ["Name of course", "What you learn", "Cost", "Other information"],
    "rows": [ ["Taster day", "introduction to sailing", "...", "..."], ... ]
  },
  "blanks": { "1": { "question": 1 }, "2": { "question": 2 } }
}
```
`{{n}}` inside a cell string marks where blank n sits; multi-line cell
content uses `\n`.

### `note-completion`
```jsonc
{
  "type": "note-completion",
  "title": "Sources of rubber",
  "content": [
    { "kind": "heading", "text": "Natural rubber" },
    { "kind": "text", "text": "This mainly comes from ..." },
    { "kind": "bullet", "text": "the growth of the tree is {{32}}" }
  ]
}
```
`kind` is one of `heading` (bold subheading), `text` (plain sentence/intro),
`bullet` (bulleted list item, may contain a `{{n}}` blank).

### `multiple-choice`
```jsonc
{
  "type": "multiple-choice",
  "heading": "Working as a makeup trainee",   // optional passage/talk title
  "choose": 1,                                 // 1 normally, 2 for "choose TWO"
  "items": [
    {
      "question": 11,
      "prompt": "What should trainees always expect to get ...?",
      "options": [ {"id": "A", "text": "travel expenses"}, ... ]
    }
  ]
}
```
For "choose TWO" items that share one prompt and one option list across two
question numbers (e.g. 21 & 22), `items` has ONE entry with
`"questions": [21, 22]` instead of a single `question`.

### `matching`
```jsonc
{
  "type": "matching",
  "prompt": "What ability is required for each of the following duties?",
  "options": [ {"id": "A", "text": "being well-organised"}, ... ],
  "allow_repeat": false,     // true when "NB you may use any letter more than once"
  "items": [ {"question": 17, "text": "Prepping an actor"}, ... ]
}
```

### `true-false-not-given` / `yes-no-not-given`
```jsonc
{
  "type": "true-false-not-given",
  "items": [ {"question": 8, "statement": "The Davies sisters' childhood ..."} ]
}
```

### `summary-completion`
Like note-completion but continuous prose with inline blanks, optionally
with a word bank (used for reading Q31–36):
```jsonc
{
  "type": "summary-completion",
  "title": "Sugar cultivation and production",
  "paragraphs": [ "The book ... depended on {{31}}. However, ... {{32}} continued." ],
  "word_bank": [ {"id": "A", "text": "national governments"}, ... ]
}
```

### `passage` (reading passages only)
```jsonc
{
  "passage_number": 1,
  "title": "The Davies Sisters",
  "subtitle": "Between 1908 and 1924, ...",   // italic strap-line, if present
  "instructions": "You should spend about 20 minutes on Questions 1–13 ...",
  "lettered_paragraphs": false,   // true for passages with A, B, C... section labels
  "paragraphs": [
    { "label": null, "text": "Gwendoline (1882-1951) and Margaret ..." },
    { "label": "A", "text": "Humans are finely attuned to noise ..." }
  ],
  "footnotes": [ "* philanthropic: seeking to promote the welfare of others ..." ],
  "question_groups": [ Block, Block, ... ],
  "page_range": [17, 20]
}
```

## Listening part
```jsonc
{
  "part_number": 1,
  "questions_range": [1, 10],
  "audio_files": ["C21T1P1.1.mp3", "C21T1P1.2.mp3"],
  "page": 11,
  "blocks": [ Block, Block ]
}
```

## Answer key
Kept as a **separate top-level object**, not embedded per-block, so audio
scripts/blocks can be re-transcribed without touching answers:
```jsonc
"answer_key": {
  "listening": { "1": ["10", "ten"], "2": "weather", ... },
  "reading":   { "1": "shipping", "2": "education", ... }
}
```

## Notes on this deliverable
- `answer_key.listening` for Test 1 is populated from your existing
  `listening.json` (verified against the transcribed blanks — all line up).
- `answer_key.reading` for Test 1 could **not** be populated: your uploaded
  `reading.json` has all 40 values as empty strings — there is no answer
  key in the source for reading. Rather than invent answers, those fields
  are left `null` with a `"status": "missing_in_source"` flag. If you have
  the real reading answer key (e.g. from the back of the book), send it and
  I'll fill this in.
- Writing Task 1's chart data points are my visual estimate from the line
  graph image (axis gridlines are every 5 million, decade markers every 20
  years) — treat them as approximate, not OCR-extracted.