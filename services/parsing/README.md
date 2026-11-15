# Offline parsing worker (Ubuntu 24 / Python 3.12)

This directory owns the fixed library subprocesses and their private Unix-socket
broker. Installation, remote model relay, public API snapshots, and ingestion
integration belong to the main application owner. Never download weights from a
parse request or inherit provider credentials.

## Version decision and official sources (2026-11-16)

- **PaddleOCR 3.7.0**, explicitly `PP-OCRv5_mobile_det` and
  `PP-OCRv5_mobile_rec`, CPU only in this runner.
  [Tagged API](https://github.com/PaddlePaddle/PaddleOCR/blob/v3.7.0/paddleocr/_pipelines/ocr.py),
  [Apache 2.0 license](https://github.com/PaddlePaddle/PaddleOCR/blob/v3.7.0/LICENSE).
- **PaddleOCR-VL-1.6 (`paddleocr_vl`)**, CPU only, running as two memory-isolated
  stages to stay well under the service 5 GiB cgroup cap: Stage 1 runs
  `PP-DocLayoutV3` inside `.tools/paddle-env` and exits (~1 GiB RSS); Stage 2 runs
  `PaddleOCR-VL-1.6-0.9B` in `torch.bfloat16` (`trust_remote_code=False`,
  `use_cache=True`) inside `.tools/mineru-env` (~2.4 GiB peak RSS).
- **MinerU 4.2.2 pipeline**, supporting both CPU and guarded CUDA via
  `mineru.backend.analyze.doc_analyze(..., effort='medium')` +
  `mineru.render.render_content_list`, provisioned locally with
  `MinerU-4_models_torch` (and optional `MinerU2.5-Pro-2605-1.2B-GGUF`) under
  `MINERU_MODEL_BASE_DIR` and `MINERU_MODEL_SOURCE=local`. Remote VLM server URLs
  are explicitly rejected by preflight/runner validation.
  [Current releases](https://github.com/opendatalab/MinerU/releases).

These sources establish APIs and packaging constraints, not successful execution
on any particular CUDA driver. Main-agent live evidence must establish that.

## Launch and provisioning contract

Run with the application's small FastAPI environment:

```sh
.venv/bin/python -m services.parsing.server
```

The broker holds an exclusive lock, binds `data/parsing/parser.sock` with a private
umask, accepts only fixed parser names, and runs one job at a time. It does not
load `.env`; export the relevant configuration through the service manager.

| Variable | Default / meaning |
| --- | --- |
| `RT_PADDLE_PYTHON` | `.tools/paddle-env/bin/python` |
| `RT_PADDLE_VL_PYTHON` | `.tools/mineru-env/bin/python` |
| `RT_MINERU_PYTHON` | `.tools/mineru-env/bin/python` |
| `RT_PADDLE_MODELS` | `.tools/models/paddle` with both named PP-OCRv5 models |
| `RT_PADDLE_VL_MODELS` | `.tools/models/paddle-vl` (`PP-DocLayoutV3` + `PaddleOCR-VL-1.6`) |
| `RT_MINERU_MODELS` | `.tools/models/mineru-4.2` (`MinerU-4_models_torch` + optional `MinerU2.5-Pro-2605-1.2B-GGUF`) |
| `RT_GPU_RESERVE_MIB` | 2048 minimum; lower supplied values clamp to 2048 |
| `RT_GPU_MAX_MIB` | 2048 per job, includes GPU usage of descendant processes |
| `RT_PARSER_TIMEOUT_SECONDS` | 300; valid 1..900 |

Use absolute custom paths. Paddle model folders must contain nonempty
`inference.json`, `inference.pdiparams`, and `inference.yml`. MinerU 4.2.2
uses `MINERU_MODEL_BASE_DIR` (populated offline) and `MINERU_MODEL_SOURCE=local`
with `MINERU_MODEL_SMALL_BACKEND=torch`; no remote VLM URL/provider env is allowed.

The runner uses local model source, offline Hugging Face settings, and a
Python socket egress denial policy. This is **not an OS sandbox** for native code.
Dynamic linker paths and keys from the parent are not inherited; the fixed WSL
CUDA driver directory is included when present. No old-host Intel preload patch
is applied.

`GET /healthz` is liveness only and explicitly says `ready:false`.
`GET /readyz` performs isolated offline import/model-file checks, returning
`readiness_level:offline_preflight` and `inference_verified:false`; this does not
load all models or prove successful inference. `last_runs` records actual parse
outcomes separately. A successful preflight cannot count as a live test.

`POST /parse/paddleocr?device=cpu` and `POST /parse/paddleocr_vl?device=cpu`
accept one PNG; `POST /parse/mineru?device=cpu` or `device=gpu` accepts exactly
one PDF page. Files are limited to 20 MiB, images
to 16 million pixels and 8192 pixels per side. PDF page dimensions must also fit
those bounds at 200 DPI. Multipart requests have a separate 21 MiB streamed cap.
Outputs, block counts, diagnostic logs, and execution time have limits. Logs and
monitor samples remain in each private job directory; no automatic deletion of
existing user data is performed. Operators should apply retention to these
private job directories to bound aggregate disk use.

## GPU and cancellation semantics

Each GPU request queries current free memory and selects the card with the most
free memory that can accommodate the **whole requested budget**, 2048 MiB reserve,
and 256 MiB launch margin. With the reported 5776 MiB free on an 8188 MiB card,
the default 2048 MiB budget fits; that report is not used as a cached measurement.

The broker samples free memory and sums NVML compute-app memory for **all PIDs
in its spawned session**, not just the direct runner. Torch also applies a
per-process allocator limit; this alone does not account for all native CUDA
allocations. Reserve loss, budget overflow, missing GPU, unknown usage (`N/A`),
or host PIDs not mappable in WSL cause conservative termination. If CUDA starts
but no owned PID can be attributed, the job is stopped rather than reporting
zero use. Unsupported WSL NVML accounting therefore blocks GPU execution; CPU
remains available. No global delta estimate is passed off as own-process usage.

Every exit path terminates only the broker-spawned session's process groups,
including remaining descendants after leader exit. TERM is followed by KILL even
when the leader has already exited. No process-name matching or other user's
processes are targeted. This assumes trusted fixed libraries do not deliberately
escape their session; it is not an arbitrary-code execution facility.

Pass the durable run ID as `/parse/{engine}?request_id=...`. IDs must be 1..96
ASCII letters/digits/underscores/hyphens and start with a letter or digit. Active
duplicates return 409. `POST /cancel/{request_id}` sets only that active request's
thread event; it returns `cancellation_requested` and `released:false`, not a claim
that resources are already free. Unknown/finished IDs return 404; invalid IDs
return 422. The cancelled parse response is 503 after its runner is reaped. The
caller should join the in-flight request before reporting cancellation complete.
The private Unix socket is the authority boundary for both routes.

Client disconnect or coroutine cancellation sets a thread event and retains the
single-job lock until the runner has stopped. Main worker cancellation may also
call `run_library(..., cancel_event=threading.Event())`. Polling (250 ms plus
bounded NVML command time) cannot guarantee that OOM never occurs between samples.

## Tests and current evidence

```sh
.venv/bin/python -m pytest tests/unit/test_parser_guard.py -q
```

Tests use synthetic files and telemetry plus real **test-owned** process groups.
They never invoke model providers or download assets. Passing these tests verifies
guards/contracts, not OCR quality, CUDA availability, or actual model readiness.
Live CPU/GPU parse status belongs in the main agent's evidence report.

## 2026-11-16 recovery hardening

VL helper interpreters inherit a fixed credential-free offline allowlist, use bounded private files for table payloads, and stay inside the broker-owned session. Region/token/table-expansion limits fail visibly rather than silently dropping evidence. Geometry and exact engine/version/device are validated before accepting output. Local model roots and nested symlinks cannot escape their provisioned tree. Local trusted model processor files are loaded offline; this is not a sandbox for arbitrary downloaded code.

A real layout result originally retained unused NumPy fields and failed JSON serialization; the failure is preserved in `evidence/ubuntu24/paddleocr-vl-20261116-layout-failure.*`. Only consumed JSON-safe fields are now emitted. Subsequent VL CPU product/browser recheck passed on the bilingual fixture (156.58s,6blocks; see dated evidence), while independent fixture tests cover figures-only cleanup and helper resource limits. Those figures are observations under concurrent unit testing, not a quality score or speed benchmark. GPU remains blocked by WSL NVML accounting; guards were retained.
