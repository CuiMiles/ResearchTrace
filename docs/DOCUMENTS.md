# Document and retrieval implementation

`services/api/documents.py` accepts bytes with a PDF header and validates with PDFium before enqueuing a persistent parse run. SHA256 is scoped to workspace, duplicate files do not create another parse/model job. Uploaded names are reduced to a basename; disk paths use opaque IDs. 70 MiB / 1500 page bounds are configurable in code for this initial deployment.

The worker uses pdfplumber page by page, closes each parsed page cache, commits blocks/FTS and checkpoint in the same transaction. Native word coordinates are converted to normalized top-left boxes. The center-gutter heuristic reads the entire left column before the right; complex mixed multi-column layouts need review. Source images/tables retain original page regions; table extraction is explicitly review-required. Equations remain linked to the source PDF region, without claiming reliable LaTeX reconstruction. Physical zero-based pages and a detected printed footer page label are separate fields.

Pages with fewer than 25 non-whitespace native characters use actual Tesseract OCR at up to 144 DPI and a maximum 2400-pixel side. User-owned Linux extraction can reside at `.tools/ocr/usr/bin/tesseract`; Docker should install `tesseract-ocr` and `tesseract-ocr-eng`. OCR is bounded to 90 seconds/page and one OpenMP thread. Missing OCR or empty recognition marks the page/version partial; images alone are never treated as searchable OCR success. Initial OCR language is English; Chinese scan recognition requires an installed language pack and `TESSERACT_LANG` configuration. The HTTP layer has a stricter 50 MiB upload limit than the parser's internal 70 MiB limit.

Identity uses frontmatter arXiv ID/version, DOI, PDF metadata and largest-font front-page title. Filename is not used to decide same-work/version order. Matching arXiv/DOI joins the same Work; similar titles without an identifier are only explicit candidates for manual association. Importing a lower numbered arXiv version keeps newer files and all old anchors. Paragraph diff is deterministic and returns before/after version/block/page/bbox. Layout changes can appear as modified paragraphs; no LLM-invented revisions.

Bibliography extraction begins only after an actual References/Bibliography heading and stores raw entries, marker and source blocks. arXiv/DOI targets are parsed only when actually present. Numbered body citation markers are retained in Block.metadata.citation_markers. Difficult author-year entry segmentation is conservative and requires review.

Retrieval always checks workspace, selected immutable version IDs and deleted state. SQLite FTS5 BM25 provides sparse candidates. The dense path calls the configured real embedding adapter; each persisted vector has model and dimension, and only the same query vector space is compared. Retrieval combines actual candidate ranks with RRF. Dense outage explicitly reports keyword-only mode. Neighbor blocks restore nearby conditions/table context. Index coverage is counted by fully covered pages; partial dense state is visible.

Unit tests use reportlab-generated synthetic PDFs and clearly labeled mock embedding vectors. They certify parser/checkpoint/scope mechanics, not provider quality, real Transformer visual fidelity or semantic accuracy. Live and browser acceptance remain the root integration responsibility.

## Executed PDF acceptance (2026-11-15)

Reproduce without API spending:

```bash
PYTHONPATH=. RT_DATA_DIR=data/document-recheck ENABLE_DENSE=false OPENBLAS_NUM_THREADS=1 \
  .venv/bin/python tests/unit/test_documents.py
```

The runner imports a fresh workspace, uses actual files in `evals/files`, kills and resumes an actual parser child, constrains its address space to 1400 MiB, and writes evidence under the selected data directory. It does not call a model or use prerecorded answers. Native/scan sources and SHA256 are recorded in `data/doc-validation-v2/evidence.json` and `evals/manifest.json`. The first execution found and fixed frontmatter reverse-digit matching, first-row column splicing, and detached math subscripts. The evidence preserves the first-pass observations plus explicit reparse corrections on the isolated, uncited validation workspace. Production cited snapshots were not reparsed.

| Check | Status | Evidence and observed result |
|---|---|---|
| Renamed real Transformer v7 then v1 | PASS | `b90f732e.pdf` → arxiv:1706.03762/v7; `c31d8f44.pdf` → same work/v1; newer-version notice; 15/15 native pages each; 40/36 raw references |
| Real version paragraph difference | PASS | `evidence.json.version_diff` contains actual added/deleted/modified source blocks and page positions |
| Unseen real BERT | PASS | `de408a19.pdf` → arxiv:1810.04805/v2, 16/16 pages; bibliography correction yields 57 raw source entries in `bert-reparse.json` |
| Actual derived textless scan | PASS | `scan_derived.pdf`, 2/2 pages through Tesseract, FTS matches actual recognized text; source is an explicit derivative, not official scan |
| New synthetic scanned PDF | PASS | Unit test generates an image-only PDF with marker7189 and independently recognizes and searches it through Tesseract |
| Synthetic longbook engineering | PASS | `long_engineering.pdf`, 541/541 pages processed and sparse indexed; no dense calls; synthetic material, not official textbook |
| Actual interruption and recovery | PASS | Parser killed with SIGKILL at page30/630 blocks; same run resumed to page541; block IDs unique; no model calls |
| Back-half/last-page sparse evidence | PASS | RTMARK0301→physical300/value5117, RTMARK0500→499/value8500, RTMARK0541→540/value9197; all exact source queries preserved |
| Parser memory under bound | PASS | Child ran under1400MiB AS limit; resumed maxRSS105860KiB (about103.4MiB), measured via `resource.getrusage`; not total-stack or CPU-performance certification |
| Official scan and official541-page textbook | BLOCKED | Official originals unavailable; engineering derivatives are labeled separately |
| General parser accuracy or semantic citation support rate | NOT RUN | These narrow fixtures and mechanics tests cannot establish a general accuracy score |

Native first-pass elapsed/peak RSS on this shared host: v7 17.901s/84.5MiB, v1 44.720s/84.8MiB, BERT55.378s/84.9MiB; derived two-page scan79.381s/103.4MiB. These are single observations under concurrent development load, not service performance promises. Longbook runs used a memory cap; total API+worker+browser memory and exact two-core throughput require separate deployment testing.

Source snapshot protection is enforced: full reparse is rejected when a version already has evidence, and cited pages cannot be overwritten. Resume skips committed pages. Restoring deleted identical bytes reindexes the original snapshot. Rebuilding with a new parser requires an independent revision snapshot; no public rebuild endpoint is provided in V1. Tests verify old block text/bbox/IDs remain unchanged.

Final module verification: `.venv/bin/python -m pytest tests/unit/test_documents.py -q` → **15 passed in56.52s**; `.venv/bin/ruff check --isolated --select E9,F63,F7,F82 services/api/documents.py services/api/retrieval.py tests/unit/test_documents.py` → **All checks passed**. Dense mechanics use explicitly labeled mock vectors in that unit test; live embedding proof belongs to the root integration ledger.

FTS query parsing separates Chinese text from technical ASCII/Greek identifiers. GPU prefix matching finds GPUs; β1 also searches β where source text has a separate subscript. Actual glyph overlap keeps β1/β2 and their values in one paragraph for new imports. Search aliases do not rewrite the source quote. Full-width/complex math still needs source-image review.

The local OCR installation used only user-owned package extraction (no sudo, no service changes): `apt-get download tesseract-ocr tesseract-ocr-eng tesseract-ocr-osd libtesseract4 liblept5`, followed by `dpkg-deb -x` into `.tools/ocr`. Binaries remain ignored by Git. Docker installs the distribution packages instead. Tesseract is Apache-2.0 and Leptonica is BSD-style; see project third-party notices.
