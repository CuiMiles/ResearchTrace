# 研证 ResearchTrace

A source-grounded research workbench: immutable PDF versions, page/block evidence, model QA, bilingual reading, live scholarly search, reference-derived local graph, Future Work audits, constrained writing, and reproducible CSV charts.

This repository is an implementation in active acceptance testing, not a claim of contest ranking or universal factual accuracy. Exact current results and limits are in [HANDOFF.md](HANDOFF.md) and [docs/TEST_REPORT.md](docs/TEST_REPORT.md).

## Install and run

Linux/WSL, Python3.12, Node22, CPU only. System dependencies: `tesseract-ocr tesseract-ocr-eng fonts-droid-fallback`. The current Ubuntu18 development host uses a private OCR installation under `.tools/ocr`, never overwrites system libraries. Use Docker on newer Ubuntu for a reproducible runtime.

```bash
python3.12 -m venv .venv
.venv/bin/pip install --no-compile -r requirements.lock
cp .env.example .env
chmod 600 .env
# Set private RT_ACCESS_CODE and a different RT_ADMIN_CODE in .env.
# Set server Gemini keys only if authorized. No keys: import/read/chart still work.
cd apps/web
npm ci
npm run build
cd ../..
./scripts/dev.sh
```

Default local address: http://127.0.0.1:18970. On this host Node is `/home/CuiMinghao/envs/cardweb/bin/node`; use `export PATH=/home/CuiMinghao/envs/cardweb/bin:$PATH`. Python3.12 is `/home/CuiMinghao/.local/bin/python3.12`. Neither path is required on a fresh normal host.

`dev.sh` installs only the application's own user systemd units when user systemd is available. Inspect with `systemctl --user status researchtrace-api researchtrace-worker`; logs with `journalctl --user -u researchtrace-api -u researchtrace-worker -n 60`. Stop with `systemctl --user stop researchtrace-api researchtrace-worker`. Without systemd, run API and worker in separate retained terminals:

```bash
.venv/bin/python -m services.api.serve
.venv/bin/python -m services.worker.main
```

Server startup does not require provider credentials. Login uses local server access codes, not API keys. Each browser session creates an isolated workspace; refresh/restart preserves it for7days. Logging out or clearing cookies loses the local session entry point; multiuser identity recovery is a known V1 limit. The optional login workspace field cannot impersonate another workspace.

For another machine, forward the server port with SSH: `ssh -L 18970:127.0.0.1:18970 your-existing-ssh-host`. Then open http://127.0.0.1:18970. A private LAN address is not a verified public HTTPS deployment.

## New inputs

- Upload any readable PDF in 文献库, open reader, wait for actual page coverage, ask a specific question, click its citation. English technical keywords are useful when dense indexing is temporarily unavailable. Core analysis Hydrogen: global initial budget4calls, per workspace2/day. Existing saved notes are explicitly history.
- Upload v7 then v1 under unrelated filenames, compare immutable versions. The renamed real papers and derived scan engineering fixtures can be prepared with `.venv/bin/python scripts/prepare_evals.py` (network required; no model generations).
- Upload your own CSV in 写作与绘图; generate a chart, edit columns/units/type, export SVG/PNG/PlotSpec/source/script. No model request needed. Unsupported or corrupt uploads give explicit errors.

Search calls arXiv/Crossref, never model-generated search results. Network/proxy failures are reported. Watch scheduling defaults off. Twenty-node graph tests use true metadata reference deposits and do not pretend twenty full PDFs were read.

## Verification

```bash
./scripts/test.sh
./scripts/smoke.sh --live --max-hydrogen-calls 4
./scripts/evaluate.sh
```

Live tests consume real quota. Request counts persist across restarts and retries. The evaluation command spends no tokens until a reviewed dataset and separate budget are configured. See `evals/manifest.json` for source/licensing/hash labels. `packages/contracts/openapi.json` is generated from actual backend schemas.

Docker lite: `docker compose --profile lite up -d --build`. See [deployment notes](docs/DEPLOYMENT.md), including volume ownership, host-specific proxy addresses, firewall and independent public verification. Compose execution is not claimed unless explicitly recorded in the test report.

Backup: stop worker, use SQLite online backup (`sqlite3 researchtrace.sqlite '.backup backup.sqlite'`) and copy the associated data/pdf/chart directories plus server-only `.env` through a private channel. Restore into a new data directory, set `RT_DATA_DIR`, start API+worker, check `/readyz`. Never put `.env` or uploaded private files into Git.
