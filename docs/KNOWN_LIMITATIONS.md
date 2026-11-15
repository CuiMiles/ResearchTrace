# Known Limitations (Ubuntu 24 / WSL2 Build)

## 1. GPU Parsing Accounting on WSL2 (MinerU GPU Blocked)
- **Observation**: On this Ubuntu 24.04.5 WSL2 host (RTX 4060 Ti `8188 MiB`), `nvidia-smi` resides at `/usr/lib/wsl/lib/nvidia-smi` and PyTorch (`2.15.0+cu132`) detects CUDA, but `nvidia-smi --query-compute-apps=pid,gpu_uuid,used_memory` returns `[N/A]` for per-process `used_memory`.
- **Behavior**: `services/parsing/guard.py` enforces a fail-closed VRAM budget (`2048 MiB` minimum free VRAM reserve and per-job budget). When per-process GPU accounting reports `unavailable`/`[N/A]` after CUDA initializes, `services/parsing/server.py` terminates the project-owned parser session cleanly (`SIGTERM`) and returns HTTP `503` (`GPU accounting unavailable; stopping this job conservatively (WSL/NVML)`).
- **Mitigation**: `PaddleOCR 3.7.0` (`cpu`), `PaddleOCR-VL-1.6` (`cpu`), and `MinerU 4.2.2` (`cpu`) run end-to-end cleanly through the Unix socket parser broker without resetting or altering prior parse snapshots. Native Linux NVML or Windows host execution is required for live MinerU GPU accounting.

## 2. Model Smoke Quota Exhausted (`HYDROGEN_SMOKE_LIMIT=4`)
- **Observation**: Live Hydrogen budget (`4` calls, `65537` input tokens / `23309` output tokens in SQLite `quota`) was already consumed prior to handoff, with `RT_SMOKE_MODE=true`, `HYDROGEN_SMOKE_LIMIT=4`, and `ALLOW_PAID_FALLBACK=false`.
- **Impact**: Fresh Hydrogen-dependent checks (such as full 50-question/baseline evaluation, fresh QA/synthesis/critique/writing generation, and large-scale end-to-end model workflows) remain `BLOCKED` on this quota-preserving instance until a separate review/demo budget is explicitly authorized; adding keys alone does not add quota.
- **Preservation**: Existing stored notes, citations, deterministic exports (`md`/`html`/`bib`), knowledge graph recomputation, and parse snapshot protections all operate with `0` provider calls.

## 3. User-provided competition corpus and quality scope
- **Inputs now available**: `科研小助手.rar` contains 39 test PDFs (1986 pages) plus a 7-page task description. The specified 15-page `1706.03762v1_img.pdf` and 541-page textbook are available under `evals/files/user-dataset-a87f17843197/`. The textbook bytes match the author's Release. The archive's publishing channel was not independently authenticated.
- **Actual coverage**: all39 source documents are ready. The original scan passed full15-page PaddleOCR and MinerU CPU parsing; the textbook passed native v2 full541-page parsing, including four verified blank pages. PaddleOCR-VL passed a labelled crop of physical page4 only, not full-scan VL processing. Old partial snapshots remain unchanged. See `evidence/competition-dataset/summary.json`.
- **Quality boundary**: execution, page coverage, source location, tables/formulas and snapshot protection were checked; this does not establish independently annotated OCR accuracy, QA correctness or comparative performance. The current39-node graph includes one cropped helper document; `graph-scope.json` separates original works, reference entries and distinct directed relations.
- **Import scope**: this acceptance uploaded the39 source PDFs through separate authenticated HTTP operations. A single multipart request still has a10-file limit; this run does not certify a20-file atomic upload.

## 4. Deployment & External Competition Materials
- **Deployment**: The active runtime runs locally as user `systemd` services (`researchtrace-api`, `researchtrace-worker`, `researchtrace-parser`) on `http://127.0.0.1:18980`. Public HTTPS ingress, remote Docker daemon, and public cloud deployment are outside the local WSL2 environment and remain to be provisioned manually if required.
- **Competition Packaging**: Non-code competition submission materials (recorded demo video, final PDF packaging/deck) are external deliverables generated after review-window verification.

## 5. Current scholarly-source DNS route (2026-11-16)
- Fresh bounded HTTP checks resolve `export.arxiv.org` and `api.crossref.org` to `198.18.2.3` / `198.18.2.4` on this host, which are not global public addresses. The existing SSRF policy correctly rejects them before outbound source content is fetched. Local HTTP200 means the application reported source errors, not that scholarly search succeeded.
- E01/E03 remain **BLOCKED**; the controlled scheduled online acceptance step is **NOT RUN** after the per-source ceiling was reached. Do not allow nonpublic addresses, disable DNS pinning, or use old cached results as fresh evidence. The source/proxy DNS path must supply real public addresses before source verification can pass; no other application's proxy configuration was changed.
- Watch overlap/recovery/cancellation and fresh-cache behavior have isolated tests. Newly created live-test watches are disabled and preexisting watches are unchanged. See `evidence/ubuntu24/discovery-20261116-20261115T164258011472Z/result.json`.

## 6. Immutable partial revisions and translation scope
- Already committed low-quality/empty parser output is retained on resume. A partial snapshot can complete its unprocessed pages but cannot repair existing page contents in place; create a new revision for quality repair or a changed parser/model/device.
- Translation jobs now pin the selected parse revision at queue reservation. Their progress counts and historical exports refer to that revision. These scheduling/export properties have fixture tests; they do not add a new live translation-quality claim or restore the exhausted Hydrogen budget.
