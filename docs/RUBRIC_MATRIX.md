# Rubric mapping

This is a feature-to-evidence map, not a claimed contest score. Weights originate in `CODEX_TASK.md`; acceptance states and actual measurements belong in `docs/TEST_REPORT.md`.

| Scoring direction | Implemented mechanism | Code | Evidence and limits |
|---|---|---|---|
| Agent / model technology (35%) | Durable fixed workflow, evidence retrieval, one combined synthesis, citation validation, public tool events, project quota reservation | `services/api/jobs.py`, `models.py`, `retrieval.py`, `services/worker/main.py` | Live model evidence in `evidence/`; exact call counts in TEST_REPORT. Citation location does not prove semantic support. Arbitrary code execution and open-ended tool loops are absent. |
| Research scenario innovation (25%) | Immutable PDF versions and literal coordinate-bound evidence; old future-work source compared with discovered later candidates | `documents.py`, `jobs.audit`, `app.py`, reader UI | Random-name Transformer v1/v7 inputs in `evals/manifest.json`; actual version/live cases in TEST_REPORT. A related title is insufficient to declare an idea solved. No global-first claim. |
| Engineering and robustness (10%) | WAL checkpoints, bounded queue, cancellation/resume, idempotency, SSRF defense, workspace authorization, fixed plotting template | `store.py`, `jobs.py`, `research.py`, `charts.py`, `app.py` | `tests/`, `docs/evidence/research_charts_tests.txt`, `research_charts_extra_tests.txt`. 2GiB target is a deployment constraint until a constrained run is recorded. |
| Practical research loop (10%) | Upload → read → ask → open original quote → compare/search → save note or reproducible chart | `apps/web/`, API routes | Three new-input paths in DEMO_SCRIPT/HANDOFF; official scan and official textbook remain separately BLOCKED when absent. |
| UI / UX (10%) | Document workbench, single-page PDF canvas, evidence inspector, version choices, aligned block translations and visible errors | `apps/web/src/` | Browser screenshots and actual tested sizes in TEST_REPORT. Source files alone do not establish a visual PASS. |
| Academic value and reuse (10%) | Traceable sources, verified metadata, local citation centrality, reproducible CSV statistics/script, explicit unsupported claims | `research.py`, `charts.py`, export routes, docs | Live dual-source search: `docs/evidence/research_live.json`; actual 20-node/71-edge Crossref metadata graph: `graph_20_metadata.json`. This is not a 20-paper fulltext corpus or full-field authority score. |

## Six required functions

| Function | Backend/UI path | Reproducible verification |
|---|---|---|
| Document management and parsing | `/documents`, `documents.py`; library/reader | Renamed real v7/v1, unseen BERT, derived scan, explicit corrupt/encrypted PDFs; source manifest. |
| Trusted question answering | `/qa/runs`, `jobs.qa`, `validate_answer` | Actual live run/usage and original quote; fixture tests reject nonexistent IDs/mismatched quotes; independent semantic review is separate. |
| Reading and translation | PDF.js page view, `/translations`, block translation cache/export | Actual complete-paper translation and bidirectional block positioning require their own test evidence; API presence is insufficient. |
| Search, watch and recommendations | arXiv + Crossref, `/watch-queries`, feedback | Fresh uncached two-source evidence, watch deduplication test, feedback changes cached-candidate ranking. Scheduled worker trigger is separately tested. |
| Citation graph, review and research advice | `/graphs`, `/ideas/audits`, source-constrained notes | 20 verified metadata works and 71 real deposited-reference edges; source DOI records preserved. Idea coverage requires later fulltext conditions and dates. |
| Writing and plotting | `/agent/runs`, note export, strict Mermaid UI, `/charts` | Source-bound claims; real line/bar/radar/3D renders; two different CSV PNGs and standalone script reproduction. No fabricated results/error bars/significance. |

The attributable engineering contribution is the integration of version identity, evidence anchors, auditable task execution and bounded resource use. BM25, embeddings, RRF, PageRank, PDF.js and model APIs retain their third-party attribution; they are not claimed as newly invented algorithms.
