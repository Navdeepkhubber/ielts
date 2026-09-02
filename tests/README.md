# Local IELTS content

The `tests/` directory is the runtime content store for local development and
optional blob-storage synchronization. PDF/audio files are intentionally
ignored by git; manifests are safe to commit.

## Import the new PDF collection

From the repository root:

```bash
python scripts/import_pdf_collection.py /path/to/KeenIelts
```

The importer:

- detects complete IELTS practice tests from the PDFs;
- creates `tests/<clean-book-name>/manifest.json`;
- copies the source PDF to `tests/<clean-book-name>/main.pdf` locally;
- extracts clickable/printed external audio URLs from the PDFs;
- extracts clickable/printed answer-key URLs from the PDFs;
- keeps the app's existing page-rendering UI contract;
- does not copy extracted book text into git;
- does not use the source aggregator's branding as the app's book name.

The purchased PDFs include external Listening and answer-key links. Those
links are source data and are preserved in each generated test manifest; the
importer must not replace them with guessed local audio or answer keys.

For production, use the existing blob-storage sync flow after the local
content package has been validated.
