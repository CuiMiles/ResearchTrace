# 研证 ResearchTrace

**参赛要求、评分标准、正式交付清单与新 Agent 接手顺序：[START_HERE.md](START_HERE.md)。** [赛题原件 PDF](docs/contest/official-requirements.pdf) · [评分映射](docs/RUBRIC_MATRIX.md) · [完整任务书](CODEX_TASK.md) · [验收标准](ACCEPTANCE.md)。

2026-11-16 开发快照：核心四文档本地索引已完成，其他35份索引与新闭环继续验收。保留真实失败记录；GitHub 公开不代表公网产品、正式视频/PDF或全部验收完成。旧环境的历史说明请结合 START_HERE 和最新交接读取。

**核心测试 PDF：[查看/下载四份原文件](evals/pdfs/core/README.md)**，包含 Transformer v1/v7、扫描版和 541 页《Understanding Deep Learning》。

A source-grounded research workbench: immutable PDF versions, page/block evidence, model QA, bilingual reading, live scholarly search, reference-derived local graph, Future Work audits, constrained writing, and reproducible CSV charts.

This repository is an implementation in active acceptance testing, not a claim of contest ranking or universal factual accuracy. Exact current results and limits are in [HANDOFF.md](HANDOFF.md) and [docs/TEST_REPORT.md](docs/TEST_REPORT.md).

## Install and run

Linux/WSL, Python3.12, Node22, CPU only. System dependencies: `tesseract-ocr tesseract-ocr-eng fonts-droid-fallback`. The verified local environment is Ubuntu24.04.5 WSL2 with Python3.12.3. Optional OCR/browser libraries are extracted privately under `.tools`; system libraries are untouched. Docker is not installed on this development machine, so Compose execution remains separately unverified.

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

Current verified local address: **http://127.0.0.1:18980**. The configured port in private `.env` takes precedence over the source default18970. In this checkout use `export PATH="$PWD/.tools/node-v22.16.0-linux-x64/bin:$PATH"`; Python is the normal `python3` (3.12). Large dependency/model downloads are relayed through the original server, then installed offline from `.tools/relay/`, as requested. Do not copy old virtualenv binaries or reset the quota database.

`dev.sh` installs only the application's own user systemd units when user systemd is available. An optional `researchtrace-parser` user unit provides separate fixed-library environments. Inspect with `systemctl --user status researchtrace-api researchtrace-worker researchtrace-parser`; logs with `journalctl --user -u researchtrace-api -u researchtrace-worker -n 60`. Stop owned units/processes with `./scripts/stop.sh`. Without systemd, run API and worker in separate retained terminals:

```bash
.venv/bin/python -m services.api.serve
.venv/bin/python -m services.worker.main
```

Server startup does not require provider credentials. Login uses local server access codes, not API keys. Each browser session creates an isolated workspace; refresh/restart preserves it for7days. Logging out or clearing cookies loses the local session entry point; multiuser identity recovery is a known V1 limit. The optional login workspace field cannot impersonate another workspace.

For another machine, forward the configured server port with SSH, for example `ssh -L 18980:127.0.0.1:18980 your-existing-ssh-host`. Then open http://127.0.0.1:18980. A private LAN address is not a verified public HTTPS deployment.

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

## Parser revisions on Ubuntu 24

The Reader exposes native / PaddleOCR / MinerU reparse choices and a historical snapshot selector. PaddleOCR uses CPU; MinerU offers CPU or guarded GPU. A new parser creates new immutable block identities on the same PDF version; complete results atomically become current. Failed/partial attempts leave the old active snapshot available. Historic citations still open their original text and geometry. New revisions reset dense coverage to zero and do not silently spend embedding quota.

PaddleOCR3.7.0 + PaddlePaddle3.2.2 has passed real bilingual CPU recognition and product/browser source-location checks. MinerU4.2.2 and PaddleOCR-VL-1.6 CPU product checks also passed; GPU remains BLOCKED on this WSL2 host because per-process NVML usage is unavailable. See TEST_REPORT for scope; installation or broker liveness alone does not prove inference. Runtime details and official version/license sources: [parsing README](services/parsing/README.md).

Hydrogen's four-call smoke budget is exhausted and preserved from the old environment. A new live core answer or quality benchmark is BLOCKED pending a separately explicit budget. Existing saved live answers are history; local import/read/search/CSV/snapshots do not need a new model generation. Never rerun live smoke to try to reset its allowance.
