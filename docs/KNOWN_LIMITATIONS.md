# Known Limitations (Ubuntu 24 / WSL2 Build)

## 1. GPU Parsing Accounting on WSL2 (MinerU GPU Blocked)
- **Observation**: On this Ubuntu 24.04.5 WSL2 host (RTX 4060 Ti `8188 MiB`), `nvidia-smi` resides at `/usr/lib/wsl/lib/nvidia-smi` and PyTorch (`2.15.0+cu132`) detects CUDA, but `nvidia-smi --query-compute-apps=pid,gpu_uuid,used_memory` returns `[N/A]` for per-process `used_memory`.
- **Behavior**: `services/parsing/guard.py` enforces a fail-closed VRAM budget (`2048 MiB` minimum free VRAM reserve and per-job budget). When per-process GPU accounting reports `unavailable`/`[N/A]` after CUDA initializes, `services/parsing/server.py` terminates the project-owned parser session cleanly (`SIGTERM`) and returns HTTP `503` (`GPU accounting unavailable; stopping this job conservatively (WSL/NVML)`).
- **Mitigation**: `PaddleOCR 3.7.0` (`cpu`), `PaddleOCR-VL-1.6` (`cpu`), and `MinerU 4.2.2` (`cpu`) run end-to-end cleanly through the Unix socket parser broker without resetting or altering prior parse snapshots. Native Linux NVML or Windows host execution is required for live MinerU GPU accounting.

## 2. Model Smoke Quota Exhausted (`HYDROGEN_SMOKE_LIMIT=4`)
- **Observation**: Live Hydrogen budget (`4` calls, `65537` input tokens / `23309` output tokens in SQLite `quota`) was already consumed prior to handoff, with `RT_SMOKE_MODE=true`, `HYDROGEN_SMOKE_LIMIT=4`, and `ALLOW_PAID_FALLBACK=false`.
- **Impact**: Fresh Hydrogen-dependent checks (such as full 50-question/baseline evaluation, fresh QA/synthesis/critique/writing generation, and large-scale end-to-end model workflows) remain `BLOCKED` on this quota-preserving instance until a separate review/demo quota or fresh key configuration is explicitly authorized.
- **Preservation**: Existing stored notes, citations, deterministic exports (`md`/`html`/`bib`), knowledge graph recomputation, and parse snapshot protections all operate with `0` provider calls.

## 3. Official Scanned & Textbook PDF Fixtures
- **Observation**: Official raw scanned/textbook benchmark PDFs were not supplied in the workspace.
- **Coverage**: OCR and layout/formula/table parsing were validated on self-authored bilingual raster fixtures (`scan-bilingual.pdf`, `scan-bilingual.png`) and single-page derivatives extracted from `arxiv:1706.03762v7` (`equation.pdf`, `table.pdf`, `formula-page4.pdf`). Multi-page full-textbook scans should be tested on native hardware once original inputs are provided.

## 4. Deployment & External Competition Materials
- **Deployment**: The active runtime runs locally as user `systemd` services (`researchtrace-api`, `researchtrace-worker`, `researchtrace-parser`) on `http://127.0.0.1:18980`. Public HTTPS ingress, remote Docker daemon, and public cloud deployment are outside the local WSL2 environment and remain to be provisioned manually if required.
- **Competition Packaging**: Non-code competition submission materials (recorded demo video, final PDF packaging/deck) are external deliverables generated after review-window verification.
