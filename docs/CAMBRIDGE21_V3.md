# Cambridge IELTS 21 content v3

This branch introduces a separate renderer for the fresh Cambridge IELTS 21 structured dataset. It does **not** reuse the legacy structured-question-extraction pipeline.

## Local content layout

Keep the book-derived files outside Git if the repository is public:

```text
tests/
└── Cambridge 21/
    ├── main.pdf
    ├── manifest.json
    ├── content/
    │   ├── Test 1.json
    │   ├── Test 2.json
    │   ├── Test 3.json
    │   └── Test 4.json
    ├── answers/
    │   ├── Test 1/
    │   │   ├── reading.json
    │   │   └── listening.json
    │   └── ...
    └── audio/
        ├── Test 1/
        ├── Test 2/
        ├── Test 3/
        └── Test 4/
```

The v3 content files use `content_schema: ieltsband.content.v3` and are consumed only by `static/js/cambridge21-content.js`.

## Rendering policy

1. Semantic text is displayed as text where the extracted layout is reliable.
2. Question groups retain `question_type`, `question_range`, and `source_pages`.
3. Layout-heavy tables, forms, maps, diagrams, and low-confidence question text expose the original PDF page through **Book page** instead of pretending OCR is exact.
4. The answer sheet is the only place that owns answer inputs, avoiding duplicate input IDs and keeping the existing scoring API unchanged.
5. Reading and Listening use the existing attempt/timer/scoring endpoints.
6. Writing uses the existing writing-feedback endpoint.

## Installing the fresh Cambridge 21 bundle

Copy the locally generated v3 bundle into `tests/Cambridge 21/`, then ensure the existing `audio/` and `answers/` folders are present. The backend's generic test loader will serve `manifest.json` and `content/Test N.json` without any Cambridge-specific backend route.

Do not commit the source PDF, complete book-derived content JSON, or audio into a public repository unless you have the rights to redistribute them.
