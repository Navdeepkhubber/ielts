# Structured IELTS content v2

IELTS mock content can now be stored as structured JSON instead of one flattened OCR string.

## Layout

```text
schemas/
  ielts-content.schema.json

tests/<Mock>/
  main.pdf
  manifest.json
  content/
    Test 1.json
    Test 2.json
    ...
```

`tests/*` remains ignored by Git because PDFs, audio and book-derived content are local/mock assets. The schema and renderer live in the repository.

## Content model

Each `content/Test N.json` has:

- `schema_version: 2`
- `content_schema: ieltsband.content.v2`
- `sections[]`
- `sections[].parts[]` for Listening
- `sections[].passages[]` for Reading
- `sections[].tasks[]` for Writing
- `pages[].blocks[]` for selectable text
- `question_types[]` and `question_sets[]` for UI decisions
- `source_pages` / `visual_fallback` references for geometry-dependent material
- legacy `reading` / `listening` fields during migration

The browser uses `sections[].pages[].blocks` for the Reading text view and retains the PDF page as a Book view fallback. This avoids trying to reconstruct tables, maps and charts with OCR alone.

## Generating content

`lib/content_extract.py` is called by the existing scaffold process. It writes v2 content for a test only when that content file does not already exist, so hand-corrected files are not overwritten.

Validate content with:

```bash
python3 scripts/validate_content.py
```

Or validate a single file:

```bash
python3 scripts/validate_content.py 'tests/<Mock>/content/Test 1.json'
```
