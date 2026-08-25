# Text-only IELTS content v2

The v2 content model is intentionally independent of PDF rendering. The scanned PDF is an authoring/source asset only. Production UI data lives in `content/Test N.json`.

## Pipeline

```text
scanned PDF
  -> PyMuPDF page render
  -> vision model reads page image
  -> page-level semantic JSON
  -> deterministic assembly
  -> schemas/content.schema.json validation
  -> text-only web UI
```

Traditional OCR is not used for content generation. The page image is the source presented to the vision model because the supplied PDFs are scans without a usable text layer.

## Canonical object hierarchy

```text
content/Test N.json
  sections[]
    listening.groups[]
      questions[]
    reading.passages[]
      question_groups[]
        questions[]
    writing.tasks[]
```

Every question is an atomic object with a stable `id`, numeric `number`, semantic `type`, prompt/display content, answer contract, source metadata and UI hints.

## Important rules

- Do not render PDF pages in the learner-facing UI.
- Do not make OCR output the canonical content model.
- Do not guess an answer during extraction. Use an empty `answer.accepted` until a trusted answer key is entered.
- Preserve `source.pdf_pages` only for authoring/audit/debugging; it is not a UI fallback.
- Validate question coverage and duplicates before publishing a test.
- Keep raw page responses outside production content, e.g. `content/raw/`, so extraction can be audited without coupling the UI to the extraction format.

## Extraction

Install authoring dependencies:

```bash
python3 -m pip install -r requirements-extraction.txt
```

Set credentials:

```bash
export OPENAI_API_KEY=...
export OPENAI_VISION_MODEL=gpt-5.6-luna
```

Run a test extraction:

```bash
python3 scripts/extract_test_content.py \
  --pdf "tests/Cambridge 21/main.pdf" \
  --output "tests/Cambridge 21/content/Test 1.json" \
  --raw-dir "tests/Cambridge 21/content/raw/Test 1" \
  --pages 11-45 \
  --test-id cambridge-21-test-1 \
  --test-name "Test 1" \
  --variant academic
```

Then validate:

```bash
python3 scripts/validate_content.py \
  "tests/Cambridge 21/content/Test 1.json" \
  --expected-reading 40 \
  --expected-listening 40
```

The current default model is `gpt-5.6-luna`; it can be overridden through `OPENAI_VISION_MODEL` or `--model`. OpenAI's current platform supports multimodal Responses API workflows and lists GPT-5.6 Luna as a cost-sensitive model suitable for high-volume workloads. See the current OpenAI platform/pricing documentation before large batch runs.
