# Writing / graph worktree integration

Branch: `complete/writing-graph`, isolated worktree `/tmp/rt-complete-writing`.
No keys read, no real provider calls, no GPU, no main-service restart.

## Main-owned wiring (required)

Mount before the frontend catch-all in `app.py`:

```python
from .writing_workflows import router as writing_router
app.include_router(writing_router)
```

In `jobs.work_once`, BEFORE the existing `qa/agent/writing -> qa` branch:

```python
elif run['kind'] == 'writing' and run['payload'].get('workflow'):
    from .writing_workflows import handle
    result = handle(run)
```

`writing` is already in the interactive pool. No schema migration is needed.
Keep legacy generic writing/agent runs on their current route. No `generate_role`;
all generation uses `models.generate(system,prompt,rid,role=...)`:

- survey/outline: `role='deep'`, semantic label `core_analysis`.
- diagram: `role='answer'` (main's Flash36 -> Lite chain).
- evidence review: existing `review_live` (Decision/verify per configuration).

## HTTP and handler interfaces

- `POST /api/v1/writing/surveys` -> `survey(run)`
- `POST /api/v1/writing/outlines` -> `outline(run)`
- `POST /api/v1/writing/diagrams` -> `diagram(run)`
- unified worker handler: `handle(run)`
- all queue `kind='writing'`, `payload.workflow='survey'|'outline'|'diagram'`.
- body: `{question,version_ids?,context_budget?:48000,idempotency_key,search_query?}`.
  Context bytes allowed 12000..64000, at most50 versions; surveys need >=1.
- returns existing durable run envelope `{id,run_id,status}` for RunDetail.
- `GET /api/v1/writing/artifacts/{artifact_id}/export?format=...`:
  survey/outline `md|bib`, diagram `mermaid|dot|tikz|matplotlib|json`.

A5 calls the Reader-owned `POST /api/v1/text/translations` with
`{text,target_language:'en'|'zh-Hans',idempotency_key}`. It accepts `id` or
`run_id` from that endpoint. Whole-PDF translation reuses existing
`POST /api/v1/translations` and requires explicit full-document selection.
Reader should retain its selection/cache/translation protections.

## What is implemented

- Dedicated survey, idea outline, diagram and translation UI in WritingPage.
  GraphView can open the survey composer and displays local role rules/metrics.
- Each source version is pinned at queue time. Per-paper candidate slots are
  allocated before bounded packing, using real immutable body blocks. Sparse
  library search is local and does not trigger cloud/GPU embedding requests.
- Outline searches both arXiv/Crossref through existing safe discovery and local
  library original blocks. Only source-provenance-verified records enter the
  bibliography whitelist; every selected model reference ID is validated.
  Metadata-only records never become fulltext evidence. Empty evidence yields
  partial proposals with explicit missing evidence, not fabricated results.
- Fixed section keys -> claim IDs -> existing validate_answer -> review_live ->
  reconstruction AFTER review. No free section prose bypass; reviewed claims,
  original quotes, parse/version/page/bbox and status survive export.
- Durable evidence/search/model/review receipts. Unknown/inflight requests are
  not sent again on resume; response is checkpointed before JSON validation.
  Cancellation is checked before new calls and in the artifact transaction.
- Atomic, idempotent claim/evidence/artifact writes. No new DDL.
- Strict graph JSON produces actual Mermaid/DOT/TikZ/Matplotlib sources from
  nodes/edges. No arbitrary model code executes. Mermaid keeps strict renderer;
  Graphviz uses pinned `@viz-js/viz=3.31.0` in a disposable worker with25s timeout,
  resource/HTML checks and sanitized SVG. Python/TikZ are download-only.
- `research.py` edits ONLY `build_graph`: existing PageRank power iteration over
  NetworkX DiGraph retained (no new scipy dependency); real directed normalized
  betweenness, in/out/total degree added. Repeated citation provenance is kept,
  but graph algorithms count unique directed edges. Deterministic relative role
  thresholds/explanations include isolates and no all-field authority claims.

## Executed validation

- PASS: 70 targeted backend tests (writing + research/charts + evidence + roles +
  cancellation/ownership), 17.67s. `/tmp/rt-writing-regression-final.log`.
- PASS: TypeScript noEmit and production build (177 files); pre-existing large
  bundle warning remains. `/tmp/rt-writing-build.log`.
- PASS:20 explicit browser-fixture checks with actual local Graphviz WASM
  renderer, API contracts and four widths1280/1440/1920/390, no page errors.
  `/tmp/rt-writing-browser-production/report.json` and screenshots.
  All API responses are labeled fixture; this is NOT real model quality.
- First unit invocation:18 failures from a test INSERT placeholder count, fixed;
  second25 passed; later expanded to29 new tests /70 targeted total.
- First browser run on Vite dev:10 checks passed, then existing public-vendor
  Mermaid import triggered Vite's public-module overlay. Preserved logs/report:
  `/tmp/rt-writing-browser-first.log`, `/tmp/rt-writing-vite.log`,
  `/tmp/rt-writing-browser-evidence/report.json`. Production preview passes.
- NOT RUN: main app/jobs integration (owned by main), real model quality,
  production arXiv/Crossref calls, full PDF translation, public deployment.

Reproduce backend from repository root:

```
python -m pytest tests/unit/test_writing_workflows.py tests/unit/test_research_charts.py tests/unit/test_evidence_validation_upgrade.py tests/unit/test_model_roles.py tests/integration/test_cancel_resume_ownership.py -q
```

For browser fixtures use the production build and isolated Vite preview, not a
running main API. Environment: `RT_WRITING_FIXTURE_URL=http://127.0.0.1:19050`;
`RT_BROWSER_EXECUTABLE` can select Chromium. Exact script is
`tests/e2e/writing_workflows_fixture.py`. All `/api/v1/**` requests are intercepted.

Official renderer API used: https://viz-js.com/api/ (instance + renderString).
NetworkX betweenness definition: https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.centrality.betweenness_centrality.html
