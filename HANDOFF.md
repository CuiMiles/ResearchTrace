# ResearchTrace handoff

First live milestone is running on http://127.0.0.1:18970 and server LAN http://10.184.17.163:18970 (not a verified public URL). Login with RT_ACCESS_CODE / distinct RT_ADMIN_CODE from ignored .env. Own user services researchtrace-api / researchtrace-worker, restart via systemctl --user restart researchtrace-api researchtrace-worker. ./scripts/dev.sh installs/starts only these own units. Other services/proxies were not modified.

Verified: two Flash Lite credential probes, actual768-dimensional embedding, newly uploaded Transformer v7 fifteen pages parsed and densely indexed, real Hydrogen answer with located exact quotes. Saved evidence in evidence/live_qa_result.json. Renamed v7/v1 linked from content; old citations stay originalversion. Full eight-page BitNet translation120/120 nonemptysourceblocks through20 actual FlashLite batches. Shared project limits count keys together; paid routes absent; Hydrogen initialglobalbudget4, currently1used at this milestone (re-read ledger for current usage).

Six feature classes have real implementations. Final acceptance still running; do not interpret this intermediate milestone as all PASS. Production frontend built and first1440/1280 library screenshots inspected. Citation/rotation, Mermaid, new CSV and Future Work browser checks continue. Official scan/textbook, publicHTTPS, full50-question quality/baseline benchmark and formalcontestvideo/PDF have not been completed. See evolving docs/TEST_REPORT.md for finalcase-levelresults.


## User-requested environment switch — work paused

2026-11-15: User explicitly requested stopping development/install/tests to change environment. In-progress project-owned parser package installs were sent SIGTERM; existing API/worker services are retained. No GPU inference test was started; no other users GPU processes or host configurations were changed.

Latest requests to carry forward: actually integrate BOTH PaddleOCR and MinerU. GPU tests may share a card based on available memory; reserve at least2048MiB, monitor and stop only this project test process on limit. Parser broker/runner/normalizer source exists under services/parsing and services/api/enhanced_parsing.py but has NOT been wired into ingestion or live-validated. Do not claim these libraries are functioning in the product yet.

PaddleOCR3.7.0 + CPU PaddlePaddle3.2.2 installed in .tools/paddle-env; mobile detection/recognition model files downloaded with hashes in evidence/paddle_model_manifest.json. import paddle fails before inference: libphi_core.so expects GOMP_parallel@VERSION from libiomp5.so. Actual ldd resolves an old /opt/intel/composer_xe_2015.0.090 runtime rather than the matching runtime bundled inside the wheel. Preloading system libgomp did not fix it. No system library was replaced. New environment should recreate isolated environments, not copy virtualenv binaries.

MinerU2.7.6 pipeline installation under .tools/mineru-env was in progress (PyTorch2.6.0+cu124 reused read-only via .pth from existing modern-multimodal environment). Do not assume install completion or model availability. Current latest MinerU4.2.2 has different APIs/dependencies; pinned2.7.6 was chosen for older host compatibility; installed-version license must be checked before distribution.

Established app state: production build succeeded with staged publishing (dist-next -> assets then index last), browser citation/rotation/CSV/Mermaid cases PASS in evidence/browser/acceptance.json; 43-test full run plus final22-test core/security regression logs are present (do not add overlapping counts). Real FutureWork audit completed using Longformer fulltext plus explicit insufficient multimodal/nonsequential evidence; saved in evidence/live_idea_result.json. Hydrogen total4calls including one truncated response, FlashLite22calls, embedding56attempts at this checkpoint; no new model evaluation authorized beyond these4Hydrogen. Runtime .env remains RT_SMOKE_MODE=true, so additional Hydrogen generation is blocked.

Uncommitted implementation and evidence are intentionally retained. docs/TEST_REPORT.md and final comprehensive HANDOFF were not yet completed. Preserve root .env privately (mode600) and data/ when migrating; never publish these or copy them into source Git. .tools/ is rebuildable, ignored environment/model cache. Review current git status before resuming.

## Ubuntu 24 recovery milestone — 2026-11-15 (current local checkout)

Local checkout `/home/cui/projects/competition/传智杯2026` is now Ubuntu 24.04.5 / Python 3.12.3 in WSL2, with RTX 4060 Ti 8 GiB. The remote source and its original two commits, dirty sources, evidence and private `.env` were copied; all four SQLite databases were migrated using SQLite backup, not raw live main-db copying. Existing PDF paths were relocated in the copied database only. `.env` remains mode 600. The old host was used as the large-download relay; old Python environments were not reused.

Actual local entry: **http://127.0.0.1:18980**. Port 18970 conflicts with a host-side listener; that service was untouched. Project-owned user units are researchtrace-api, researchtrace-worker, and optional researchtrace-parser. `./scripts/dev.sh` starts these owned units; `./scripts/stop.sh` only stops units belonging to this checkout. Base API/worker limits remain 512M/896M. Optional heavy parser has 5G/2 CPU limits and is not part of the 2GB lite claim.

Ledger preserved: Hydrogen 4, Flash Lite 22, embedding 56 attempts. No additional provider requests in this milestone. RT_SMOKE_MODE and original 4-call ceiling remain enabled. Old machine proxy was replaced only in this private project config by the existing local proxy. No other project's proxy/service/library was changed.

Implemented parser revisions, current index scopes, historical reader APIs, scoped references/search, legacy evidence parse identity, and atomic publication after complete parsing. Existing block IDs/text/bbox stay unchanged. Real native HTTP reparse kept 127 old blocks byte-equivalent; see `evidence/ubuntu24/live-native-snapshots.json`. New local PDF import/search/location and damaged PDF rejection ran without embedding spend (`?index_dense=false`).

PaddleOCR 3.7.0 with PaddlePaddle 3.2.2 and explicit local PP-OCRv5 mobile models has passed genuine CPU recognition plus the actual API/worker/product revision -> search -> page-location flow. Bilingual self-authored raster fixture is clearly not an official contest scan. Direct PNG sample 7.82 seconds, peak RSS 968368 KiB; product single-page revision 8.69 seconds. See `paddle-cpu-first.json`, `paddleocr-cpu-product.json`, and input/model manifests under `evidence/ubuntu24/`.

Current regression: 75 passed (no skipped tests), one dependency deprecation warning. Browser checks of real saved model citations, rotation/zoom, CSV and Mermaid pass in `evidence/ubuntu24/browser/acceptance.json`; no new model request. Native document acceptance re-ran renamed Transformer v7/v1, BERT, derived scan and the self-authored 541-page stress fixture. Killed at page 30, resumed all 541 pages, checked pages 301/500/541; resumed parser RSS peak 109364 KiB. This does not establish official textbook acceptance or the full service's 2GB limit.

MinerU 2.7.6 pipeline environments/large dependencies are still being provisioned at this milestone; real CPU/GPU inference is NOT RUN. All 42 selected pipeline model files transferred from remote have SHA256 verified. GPU guard tests cover own session descendants, live reserve selection, missing WSL telemetry, and targeted cancellation. Unit tests do not prove actual GPU inference. Full updated acceptance report and further integration continue.

Unchanged external gaps: official scanned original/textbook, independently reviewed 50-question/baseline evaluation with separate authorized model budget, public HTTPS/reviewer validation, formal final video/PDF. Do not reuse old-host live results as Ubuntu24 PASS.

## Ubuntu 24 completion update — 2026-11-15 (current)

- **Startup & Services**: Owned systemd user units `researchtrace-api`, `researchtrace-worker`, `researchtrace-parser` active on **http://127.0.0.1:18980** with Unix socket parser broker (`data/parsing/parser.sock`). Start/stop via `./scripts/dev.sh` and `./scripts/stop.sh`.
- **MinerU 2.7.6 & GPU Guard Integration**:
  - Fixed WSL2 `nvidia-smi` discovery (`/usr/lib/wsl/lib/nvidia-smi` fallback in `services/parsing/guard.py`), pre-launch monitor logging (`services/parsing/server.py`), and broker error detail forwarding (`services/api/enhanced_parsing.py`).
  - **MinerU CPU (`B02` PASS)**: Verified real product API/worker/broker execution with unchanged prior snapshots and unchanged quota (`equation.pdf` 8 blocks / 69.81s; `table.pdf` 13 blocks with HTML BLEU Table 2 / 94.89s; `formula-page4.pdf` 12 blocks with LaTeX Attention formula / 103.38s), plus Chromium PDF yellow bbox highlighting (`evidence/ubuntu24/mineru-cpu-equation.json`, `mineru-cpu-table.json`, `mineru-cpu-formula.json`, `mineru-graph-browser.json`).
  - **MinerU GPU (WSL2 Fail-Closed BLOCKED)**: Selected `GPU-29091215-1e1a-de71-8769-739c1d0964c3` (`5921 MiB` free / `8188 MiB` total); after CUDA started, `nvidia-smi --query-compute-apps` returned `[N/A]` for per-process `used_memory`. Monitor terminated only the owned parser session (`returncode: -15`) and returned HTTP `503` (`GPU accounting unavailable; stopping this job conservatively (WSL/NVML)`) (`evidence/ubuntu24/mineru-gpu-monitor.json`).
- **Automated Regression & Build (`./scripts/test.sh`)**: **97 passed**, 1 dependency deprecation warning (`evidence/ubuntu24/regression.log`); `ruff`, `tsc --noEmit`, `vite build` (168 files), and `export_contract.py` all pass.
- **Browser Acceptance Matrix (`http://127.0.0.1:18980`)**: D02 (reference jump/return), D03 (bidirectional scroll sync), D05 (loading/partial/500/401/empty/429/parse-failed matrix in `apps/web/validation/reader-extra-20261115T143101401610Z.json`), and E06 (29-node/72-edge real citation graph inspector/recomputation/1440+1280 no-overflow in `evidence/ubuntu24/mineru-graph-browser.json`) + E08 deterministic `md`/`html`/`bib` exports verified with `0` provider calls and `0` console/page errors.
- **Documentation & Acceptance**: Updated `packages/contracts/API.md`, `docs/KNOWN_LIMITATIONS.md`, `docs/TEST_REPORT.md`, and `evidence/ubuntu24/acceptance.json` (**46 PASS**, **18 BLOCKED**, **0 FAIL** across A01–F15).
- **Quota Ledger Integrity**: Still unchanged (`gemini-4-hydrogen: 4 ok`, `gemini-3.5-flash-lite: 22 ok`, `gemini-embedding-001: 52 ok / 3 failed / 1 unknown`).

## Ubuntu 24 parser upgrade milestone — 2026-11-16 (current)

- **MinerU 4.2.2 (`mineru[torch]==4.2.2`)**: Replaced 2.7.6 in `.tools/mineru-env` (`requirements-mineru.lock` exported, `.tools/mineru-env-276.bak` removed) with offline models (`MinerU-4_models_torch` + `MinerU2.5-Pro-2605-1.2B-GGUF`, 19 files in `evidence/ubuntu24/mineru-422-model-manifest.json`). End-to-end CPU product checks + Chromium highlights all PASS (`equation.pdf` 14.29s, `table.pdf` 15.82s, `formula-page4.pdf` 23.73s, `scan-bilingual.pdf` 9.20s); GPU remains honestly `BLOCKED` by WSL2 NVML `[N/A]` fail-closed guard (`evidence/ubuntu24/mineru-gpu-product.json`).
- **PaddleOCR-VL-1.6 (`paddleocr_vl`)**: Offline models (`PP-DocLayoutV3` + `PaddleOCR-VL-1.6-0.9B`, 34 files in `evidence/ubuntu24/paddle-vl-model-manifest.json`) integrated across broker, API, worker, and `ParseControls.tsx`. Uses two-stage CPU isolation (`PP-DocLayoutV3` in `.tools/paddle-env` -> `PaddleOCR-VL-1.6-0.9B` `bfloat16` in `.tools/mineru-env`) so peak memory stays ~2.4 GiB under `MemoryMax=5G`. Live bilingual CPU parse (`132.67s`, `evidence/ubuntu24/paddleocr-vl-cpu-product.json`) + Chromium highlight audit (`evidence/ubuntu24/browser/paddleocr_vl-reader.json`) PASS.
- **Admin Dashboard & Verification**: Updated `services/api/acceptance_report.py`, `evidence/ubuntu24/acceptance.json`, `docs/TEST_REPORT.md`, `docs/DECISIONS.md`, `docs/KNOWN_LIMITATIONS.md`, and `services/parsing/README.md`. Re-ran `./scripts/test.sh` (99 passed + Vite 168 build files), Playwright admin dashboard check, and verified SQLite `quota` unchanged (`0` new provider calls).


## 2026-11-16 后续修复（最新）

保留用户提交 `ba83619` 的 MinerU 4.2.2 / PaddleOCR-VL-1.6，以及 `b2d3d17` 的管理看板。本轮开始时工作区干净。三个项目服务继续运行于 **http://127.0.0.1:18980**，启动/停止仍使用 `./scripts/dev.sh` / `./scripts/stop.sh`。本轮没有大型下载、全局代理或系统库变更，没有新增供应商请求。

实际完成：
- 页面写入和发布在 SQLite 写事务内检查取消/删除；最后一页返回的结果不会越过取消或删除重新进入索引。恢复跳过所有已提交页面，包括低质量/空输出；质量修复需创建新快照。解析器版本、模型或设备改变时拒绝混合续跑，原块保持不变。
- 每个任务持有独立 OS 执行锁。取消任务尚在释放资源时，恢复返回 HTTP409，避免重复执行。真实 MinerU CPU 两页测试用时28.42秒：第一页6块保存后取消第二页，监控记录只终止本项目会话；释放后恢复至12块/2页，第一页和旧快照哈希不变。证据：`evidence/ubuntu24/parser-recovery-20261116.json`。
- 翻译任务在排队时固定 parse_id；相同幂等键在活动快照切换后仍对应原任务。进度仅统计该快照的段落，历史导出使用 `/translations/{vid}/export?parse_id=...`。本轮翻译测试使用明确的 fixture，不增加实时译文质量结论。
- VL 子进程使用凭据隔离的离线环境和有界私有文件传递，限制输出、超时、区域数、token数及表格扩张，验证几何、模型路径和 Stage1 版本。一次真实布局 JSON 失败的日志已保留；修复未使用的 NumPy 字段后，真实 VL CPU 产品复测通过：156.58秒/6块、runner峰值RSS2470152KiB；中文文字层、FTS和PDF高亮浏览器复核通过。此时单测并行运行，耗时不作为独立性能比较。
- 追踪检查新增跨进程去重锁、异常恢复、请求前推进 next_check、新鲜搜索和取消/禁用保护。普通任务恢复接口不会把 watch 加入解析队列，追踪重试使用“立即检查”。检索入库增加 metadata_only / index_dense 选项。
- arXiv/Crossref 各最多2次真实检查；当前 DNS 返回198.18.2.3/198.18.2.4，被 SSRF 拒绝，来源正文未抓取。E01/E03仍为BLOCKED，受控定时在线验收为NOT RUN；没有放宽防护或冒用缓存。测试追踪已关闭，原有追踪未改变。证据见 `discovery-20261116-*`。
- 管理端证据符号链接逃逸返回404；已按安装包补充 MinerU4.2.2 许可证和第三方说明，未继续套用2.7.6的许可证。

验证：完整自动测试 **133 passed**，1条依赖弃用警告；Ruff通过；TypeScript/Vite构建通过，发布168个文件；OpenAPI已更新；管理看板与VL阅读器浏览器检查通过。源码和证据扫描未发现私有凭据值。日期为20261116的新日志保留在 `evidence/ubuntu24/`。

账本仍为 Hydrogen4次（输入65537/输出23309 tokens）、Flash Lite22次（输入15068/输出14624）、embedding56次尝试（输入214761，含失败和未知项）。没有重置账本或增加Hydrogen额度。

64项验收仍为46PASS/18BLOCKED。剩余阻塞：WSL NVML不能提供进程显存、官方扫描/教材原件缺失、独立质量真值与另行明确的模型评测预算、公网HTTPS/评审登录、正式视频/PDF及提交材料。133项自动测试不代表全部赛事验收通过。

三条可复现本地路径：新PDF导入（关闭dense）→MinerU CPU快照→搜索与原文高亮；两页MinerU取消/恢复→核对旧快照；新CSV绘图与导出，并演示损坏PDF拒绝。脚本和原始证据均保留。

## 2026-11-16 指定教材来源补查

已找到赛题明确点名的 `UnderstandingDeepLearning_02_09_26_C.pdf`：作者项目 `udlbook/udlbook` 的 v5.0.3 Release。按远端中转下载至 `evals/files/contest/UnderstandingDeepLearning_02_09_26_C.pdf`，实测541页；SHA256与GitHub资产公布值一致（证据 `evidence/ubuntu24/contest-textbook-source.json`）。因此此前“教材未取得”的历史记录不再代表当前文件状态。当前只完成来源/完整性核验，尚未执行该书解析验收；没有将官方资料包副本与作者文件做字节比较。扫描件 `1706.03762v1_img.pdf` 的公开官方附件仍未找到。

## 2026-11-16 用户资料包与处理流程阶段

用户提供 `科研小助手.rar`，原包保留并加入忽略；SHA256 `a87f17843197b011b1694293a65b63514cef8a1dc72c4b465f6bbd3fc5cfc819`。已安全解压到 `evals/files/user-dataset-a87f17843197/`，39份测试PDF共1986页，加7页题目说明共40文件/1993页；包括 v1/v7、完整15页扫描版与541页教材。教材哈希与作者 Release 完全相同。

按用户要求，先在管理员“验收与截图”顶部发布十步可点击流程，再执行这批资料测试。`evidence/competition-dataset/browser-before.json` 证明流程发布时 test_execution_started=false，十个节点点击、5秒保留选中刷新和桌面/390px无溢出均通过。实际记录来自 `/api/v1/admin/workflow`，证据沿用管理员白名单文件接口。前端子任务因工具额度停止，主 agent 接续已落盘内容，没有伪造其完成报告。

本阶段提交时资料测试仍在继续；当前真实进度由 `evidence/competition-dataset/workflow.json` 提供，最终结果见后续交接段。不要把本阶段提交当作全部验收通过。Hydrogen4/FlashLite22/embedding56账本仍保留，没有新增供应商请求。
