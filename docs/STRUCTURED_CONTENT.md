# Structured IELTS content

The `feature/structured-question-extraction` branch is the source of truth for the structured extraction implementation.

## Format

Generated `tests/<mock>/content/Test N.json` files use `schema_version: 3` and preserve the legacy `text` field while also storing:

- `blocks`: page-aware prose/instruction blocks
- `questions`: individually detected questions with page numbers
- `question_range`: manifest-defined expected range
- `qa`: extraction completeness/ordering diagnostics

The existing `static/js/structured-content.js` consumes schema version 2+ content and replaces the flattened text at the UI boundary with individually rendered question cards. The existing exam/audio/scoring flow remains intact.

## Schema

The committed schema is `schemas/ielts-content.schema.json`.

## Validation

Run:

```bash
python3 scripts/validate_content.py
```

or point it at a local mock/content root:

```bash
python3 scripts/validate_content.py tests/'IELTS 21'
```

Book pages remain available through the existing page endpoint because maps, charts, tables and other complex layouts should not be reconstructed from OCR when the source image is the authoritative representation.
