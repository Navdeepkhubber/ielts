# Text-only IELTS content v2

The v2 content model is independent of PDF rendering. The scanned PDF is an authoring/source asset only. Production UI data lives in `content/Test N.json`.

## Pipeline

```text
scanned PDF
  -> PyMuPDF page render
  -> local Ollama vision model reads page image
  -> page-level semantic JSON
  -> deterministic assembly
  -> schemas/content.schema.json validation
  -> text-only web UI
```

Traditional OCR is deliberately not used as the canonical content source. The page image is provided directly to a local vision-language model because the supplied PDFs are scans without a usable text layer.

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
- Do not make raw OCR output the canonical content model.
- Do not guess an answer during extraction. Use an empty `answer.accepted` until a trusted answer key is entered.
- Preserve `source.pdf_pages` only for authoring/audit/debugging; it is not a UI fallback.
- Validate question coverage and duplicates before publishing a test.
- Keep raw page responses outside production content, e.g. `content/raw/`, so extraction can be audited without coupling the UI to the extraction format.
- The extraction pipeline must work with no OpenAI or other paid API account.

## Local extraction

The default provider is Ollama running locally with Qwen3-VL. Ollama currently provides local Qwen3-VL variants including 2B, 4B, 8B, 30B and 32B sizes; choose the largest one your machine can run comfortably. Qwen3-VL is designed for visual document understanding and OCR-like tasks. See the current Ollama/Qwen documentation before choosing a model.

Install Ollama, then pull a local model:

```bash
ollama pull qwen3-vl:8b
```

The extractor talks only to `http://127.0.0.1:11434` by default.

Install authoring dependencies:

```bash
python3 -m pip install -r requirements-extraction.txt
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
  --variant academic \
  --model qwen3-vl:8b
```

For a smaller machine, use a smaller local model, for example:

```bash
--model qwen3-vl:4b
```

Then validate:

```bash
python3 scripts/validate_content.py \
  "tests/Cambridge 21/content/Test 1.json" \
  --expected-reading 40 \
  --expected-listening 40
```

No API key, OpenAI account, or per-page inference charge is required. Model inference cost is local compute only.
