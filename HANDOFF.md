# ResearchTrace handoff

## 2026-11-19 游客上线与演示视频 v3（最新）

- 公网：API `researchtrace:completion-v40-video`，两个 Worker `completion-v39-seedfix`。发布目录 `/opt/researchtrace/releases/completion-v40-video-20261119`，可回滚到 v39（API）或 v38。v38 上线前做了 SQLite 在线备份 `/opt/researchtrace/data/backup-before-v38.sqlite`（约 2.4 GB），环境文件备份 `private/runtime.env.before-v38`，nginx 片段备份 `private/nginx-demo-before-v40.conf`，首次上传的 v4 媒体在 `private/demo-v4-first/`。
- 游客：`RT_GUEST_MODE=true`，种子空间为评委空间，只复制 Gemini 768 维索引。`RT_GUEST_SHOWCASE=true` 时，评委空间里已完成的问答、智能体、写作、修订总结和译文会作为已保存历史复制给每位游客（不复制额度账本）。游客的新请求只走 `gemini-3.5-flash-lite`，每人每天 20 次，全体游客每天 150 次。
- v38 上线后游客登录全部返回 500：评委空间里录制时删掉的 v1 仍留着块与解析的关联，复制时撞了唯一约束。v39 修复并补了回归测试。
- 演示视频 v3（网页文件名为 v4）：7 分 16 秒，1080p，用评委账号在公网实拍，含一次现场提问（等待回答的时间已剪掉，画面标注「快进」）。配音为 MiniMax `speech-2.8-hd`「青年大学生」，13 次合成，每次 2–6 句，按返回的逐句时间戳对齐字幕和画面。字幕烧录进画面，网页直接播放烧录版。成片在 `deliverables/ResearchTrace_实际界面演示_1080p.mp4`，复现脚本在 `scripts/video/*_v3.py`。
- 当天 Hydrogen 3 次、3.6 Flash 4 次请求在提供方失败（不是额度用完），问答自动降级到 Flash Lite，视频里的现场回答也是 Flash Lite 生成的。如果评审期间仍然失败，评委的新回答也会是 Flash Lite。
- 待人工：完整听一遍配音；确认作品介绍里的「未发表、未获奖」；用 Windows Chrome/Edge 播放一次新视频；上传完整作品压缩包。

## 2026-11-19 演示字幕

公网首页正在使用 `researchtrace:completion-v37-caption-layout`。网页字幕采用亮蓝字与深蓝底，长句分两行并避开控制栏。下载版与仓库内的正式 MP4 将蓝字烧录到画面。51 条字幕的原有时间段与配音已比对。复现命令见 [演示发布](docs/DEMO_RELEASE.md)，验收见 [测试报告](docs/TEST_REPORT.md)。

## 2026-11-18 学术配音正式版

公网首页升级至 `researchtrace:completion-v35-academic`。正式演示使用 MiniMax Speech 2.8 HD「青年大学生」，复用用户选中的 A 版开场；剩余 47 段分 12 批合成。视频约 6 分 25 秒，1080p，51 条字幕。已从 Windows Chrome、Edge 和 Chromium 桌面及手机宽度验证免登录播放、进度跳转和字幕。正式 MP4 及答辩讲稿位于 `deliverables/`。

## 2026-11-18 修复 Windows 网页播放

公网已更新为 `researchtrace:completion-v34-playback`。Windows Chrome 和 Edge 复现了 v33 首选 VP9 时的硬件解码错误。v34 优先兼容版 H.264/AAC，失败后自动试 VP8/Opus，浏览器不支持 H.264 时直接选 VP8。评审入口和正式下载保留。公网播放与跳转复测通过。

## 2026-11-18 公网演示上线

- 公网首页已提供免登录视频与 MP4 下载。评委登录后可进入原工作区，或打开 `/demo` 观看。API 镜像为 `researchtrace:completion-v33-demo`，发布目录为 `/opt/researchtrace/releases/completion-v33-demo-20261118`。两个 Worker 保持原 v32 实例。
- 成片为 `deliverables/ResearchTrace_实际界面演示_1080p.mp4`，5 分 25 秒，1920×1080，普通话和 51 条字幕。两段补录、调用次数和复现方式见 [演示发布](docs/DEMO_RELEASE.md)。
- 新浏览器桌面和手机宽度验证了播放、字幕、跳转与访客权限。评审登录后库内仍是 10 篇。验收见 `evidence/demo-release-20261118/public-demo.json`。比赛平台提交由团队处理。

## 2026-11-18 提交版

- 公网为 `researchtrace:completion-v32`，发布目录 `/opt/researchtrace/releases/completion-v32-20261118`，前端提交 `71605f2`。v24–v32 都只更新前端，服务沿用 v23。回滚目标 v31。
- 评委账号 10 篇论文。录制路径已在公网彩排 16/16 步通过，结果见 `evidence/ui-redesign-20261118/rehearsal.json`。
- 讲稿在 `docs/DEMO_SCRIPT.md`。录制时上传的 v1 要在录完后从文献库删除，评委才能复测版本识别。
- 作品介绍沿用技术文档模板（封面、目录、样式），章节按赛题 6 项要求重排。源文件在 `docs/work-intro/`，用 `TEXINPUTS=.:../tech-report: latexmk -g -xelatex -outdir=build main.tex` 编译，成品在 `deliverables/ResearchTrace_作品介绍.pdf`。
- `deliverables/ResearchTrace_完整作品.zip` 由 Git HEAD 生成并被 Git 忽略，已做密钥和主机信息扫描。
- 待人工：确认作品介绍第 6 节「未发表、未获奖」属实；录制视频；上传压缩包并填写网盘链接。
- `71605f2` 之后的提交只含文档和 GROBID 网关的关闭修复。网关不在公网部署内，公网无需更新。

## 2026-11-18 录制前更新

- 公网评委账号已使用 `researchtrace:completion-v23`。代码在 `upgrade/complete-20261116` 的 `52f504b`。上线前 SQLite 备份为 `backup-20261118T025200292359Z`，可回滚到 v22。
- 文献库索引状态查询直接限定当前工作区和活动解析。10 篇论文的服务端整条请求由 5.27 秒降至 0.48 秒。
- Attention v7 活动解析为 `361c058a4af94f2795b85043374e8bae`。第 4 页 §3.2.1 阅读顺序已纠正，版权声明与脚注在译文中按块类型展示。Gemini 索引代 `648f9547c29f4009a8392751bfd8f583` 覆盖 150/150 原块。
- 录制请用 [新 v7 三题会话](https://researchtrace.sluna.xyz/chat/th-recording-v23-attention)。已在公网浏览器点通第 4、5、7 页引用。旧回答仍可回到原解析快照，保留原文和坐标。
- v7 全文（15 页，150/150 块）及扫描版第 1–4 页（48/48 块）译文已保存。公网浏览器验证两篇各自第 4 页的原文与译文同屏。按 `docs/DEMO_SCRIPT.md` 中的链接录制。
- 写作工坊「已保存产物」里已有「研究 idea：分析降低 Transformer 注意力访存开销的方法」。其 Related Work 三条主张均通过原文校验和 Decision 1 复核。完整框架仍显示部分完成，实验结果待填。可打开 [核验记录](https://researchtrace.sluna.xyz/runs/8b4fb9b4eebf459db49e81c415f1e8d4) 点击引用。
- 完整后端回归 667 项通过。快照切换前误触发过一次 v22 解析及自动索引，随后在 v23 重新完成。两次任务与实际用量均保留，付费兜底关闭。证据在 `evidence/recording-ready-20261118/`。

## 2026-11-18 早期部署记录

- 公网：https://researchtrace.sluna.xyz （阿里云 ECS 2核2GB）。生效版本见 `docker ps`；本轮依次部署 v13–v16，
  v17（公式渲染/页面文字加载/阅读框固定）与 v18（引文图谱短标题匹配）已构建，激活状态以本节末尾记录为准。
  回滚镜像保留 `researchtrace:completion-v13…v18`；激活前备份：`backup-20261117T162214371067Z`（v16 前）、pre-v17 备份。
- 部署流程（本机无法直连 ECS，经 GPU 服务器 node01 中转）：`scripts/deploy_ecs.py --relay gpu upload/exec`；
  ECS 上 `systemd-run` 执行「基于上一镜像构建 → `backup.py --max-pause 150` → 激活（activate.sh 去掉内置备份）」。
  Workbench 单次执行 30 秒超时，长任务必须用 systemd-run，不要用 nohup。
- 模型角色（ECS `private/runtime.env`，只列模型名）：DEEP=gemini-4-hydrogen→gemini-3.6-flash；
  ANSWER=hydrogen→3.6-flash→3.5-flash-lite；LIGHT=3.5-flash-lite；VERIFY=3.6-flash。付费兜底关闭，失败重试照常记账，账本从未重置。
- 检索模型在 node01：`researchtrace-embed.service` / `researchtrace-rerank.service`（用户级 systemd），drop-in
  `split-across-cards.conf` 设 `RT_RETRIEVAL_SINGLE_GPU=0`，嵌入 2 卡各约 8.3 GB、重排 4 卡各约 4.2 GB，给共享用户留余量。
  `researchtrace-warm@embed/rerank.timer` 每 90 秒保温（runner 空闲 120 秒会退出）。旧的 `researchtrace-retrieval-warm.timer`
  仍在但无害，可人工 `systemctl --user disable --now` 后删除（自动模式下删除单元被拦截，未执行）。
- 演示账号「视频演示空间」（30 天）：访问码只在 ECS `/opt/researchtrace/private/demo-video-account-20261118.json`
  与本机被忽略的 `data-migrated/completion-deployment/` 同名文件（0600）。资料库精选 10 篇（Attention v7、扫描版、
  541 页教材、BERT、GPT-1、T5、ViT、LayerNorm、Pre-LN、FlashAttention），其余为软删除；4 个解析错的标题已按论文首页人工更正。
- 视频：`docs/DEMO_SCRIPT.md`（8 分钟顺序、操作与台词、录制前检查清单）。
- **评委账号（原 reviewer 账号）已精简**：保留 10 篇精选论文，其余 36 篇（含 v1）软删除，可恢复。删 v1 是为了让评委自己上传 v1，
  完整体验 3.1；重新上传会复用同一版本，Hydrogen 修订总结立即显示。4 个乱码标题已更正，v7 目录按解析标题重建（去掉版权声明和脚注误判，共 30 条）。
  已预生成：v1→v7 修订总结（gemini-4-hydrogen）、单篇问答（Hydrogen）、跨篇 Post-LN/Pre-LN 问答（降级到 3.6-flash，结果为部分完成）。
  录视频请用评委账号（`docs/DEMO_SCRIPT.md`）；「视频演示空间」账号没有这些预生成结果。
- GPU（2026-11-18）：0/3/4/5 号卡留给其他任务。embed 通过 drop-in `visible-cards-2-7.conf`（内容为
  `RT_RETRIEVAL_GPU_ALLOW=1,2,6,7`）只放在 1/2/6/7 号卡，每卡约 4.3 GB；rerank 因显存不足未启动。
  不需要时执行 `systemctl --user stop researchtrace-warm@embed.timer researchtrace-embed.service` 释放。
- **模型请求链路**：ECS 应用 → `GEMINI_PROXY=127.0.0.1:18987` → 由 node01 发起的 SSH 反向隧道 → node01 `127.0.0.1:7890`（共享 mihomo 代理）
  → 海外出口 → Gemini。约 5.5 万 token 的大请求会让 Hydrogen 静默思考两分多钟，中转链路在约 120 秒空闲后断开连接。
  已在 26d534a（v22）修复：跨篇回答不再重复发送证据，提示词控制在约 2.5 万 token 以内；修复后两道跨篇题都由 Hydrogen 完成。
- **评审期间是 API 模式**：GPU 服务已全部停止（embed、rerank 和保温定时器）。评委账号 10 篇论文都有 gemini-embedding-001 索引；
  在 `RT_EMBED_PROVIDER=auto` 下，本地模型不可用时自动改用 Gemini 向量加 BM25，已实测。
  重新启用 GPU：`systemctl --user start researchtrace-embed.service researchtrace-rerank.service researchtrace-warm@embed.timer researchtrace-warm@rerank.timer`。
  选卡由 drop-in 控制：embed 用 1,2,6,7，rerank 用 0,3,4,5（`RT_RETRIEVAL_GPU_ALLOW`）。
- ECS 磁盘已清理：删除 v2–v17 镜像和更早的备份，保留 v18 起的镜像与最新两份备份，使用率 72% → 49%。
- 解析修复（640b365，v21）：页脚注释、图表坐标、大字号版权声明不再被识别为标题；只对新解析生效，已在库的文档用目录修正处理。

该阶段待办为写作结果预生成及视频录制。最新进展见上节。

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

## 2026-11-16 用户原资料包测试完成（最新）

- 继续保留用户原RAR与已修改的项目，流程阶段已提交 `7a80ed4`。本阶段用真实HTTP在独立测试workspace逐文件导入39份原资料；私有会话位于 `data/competition-dataset-session.json`，未打印/提交。所有39份最终ready、1986页均处理。另7页题目说明用于阅读核对，不冒充应用解析测试。
- 教材首轮541页因为4张仅有裁切线的空白页而partial，原始失败保留。修复 `pdfplumber-layout-v2`：结构检查加白色正文区域渲染确认才记blank，图像/矢量图/淡字不能误判。创建独立新快照541页/5315块，88.02秒通过；旧块ID/文字/bbox哈希不变。原教材在32页取消、等待执行锁释放后恢复，检查点保留。
- 指定扫描件完整15页：PaddleOCR CPU234.44秒/311块，runner峰值RSS1261320KiB；MinerU4.2.2 CPU352.72秒/138块（4表格/6公式），runner峰值RSS2705092KiB。VL仅第4页裁剪区域：139.22秒/6块，runner峰值RSS2473220KiB；衍生来源页/范围/哈希均记录，不宣称全文VL。重型解析不计入2GB lite声明。
- GPU真实产品请求4.6秒后因WSL/NVML无法核算进程显存而BLOCKED；monitors保留实时选卡、2GiB余量、项目预算和仅终止本项目会话。无残留解析runner，无操作其他进程。
- 122次真实正文FTS→指定版本/parse_id/页/块/bbox查询通过，含教材后半部抽页与末页。首轮5个文件选中重复页眉、目标页不在前50条结果的失败保留并标注复测；没有将该失败冒称索引修复。浏览器29项阅读/表格/公式/VL/空白页/图谱检查通过；流程发布前39项、发布后38项通过。每个步骤可点开看真实文件、任务、结果、JSON/log和截图，5秒刷新保留选中项。
- 图谱当前39节点/162条实际定位引用记录、160条去重有向关系。39份原PDF对应38作品（v1/v7合一），另含1份裁剪辅助文档；该scope单列，未声称人工审查的引用匹配精度。由39份资料页数生成的衍生CSV已真实绘图并鉴权下载PNG/SVG/脚本/spec/CSV，原RAR无CSV。损坏PDF422、未登录401、跨workspace404、路径逃逸404；真实教材任务SSE事件有序且收到done。
- 完整 `./scripts/test.sh` **142 passed**，Ruff、TypeScript/Vite（168文件）、OpenAPI全部通过，见 `evidence/competition-dataset/regression.log`。首次脚本竞态/构建类型遗漏/浏览器CSP写法错误均有失败日志，修复后复验；原始失败没有删除。64项机器验收更新为 **48 PASS /16 BLOCKED /0 FAIL**，新流程阶段状态按执行范围独立统计。
- 当前仍为 **http://127.0.0.1:18980**，三个项目user systemd服务运行；启动 `./scripts/dev.sh`，停止 `./scripts/stop.sh`。管理员“验收与截图”顶部即十步流程。结果总览 `evidence/competition-dataset/summary.json`；明细 `workflow.json`；来源 `manifest.json`；`docs/TEST_REPORT.md` 已更新。
- 本轮0供应商新请求，完整quota行未变：Hydrogen4次（65537输入/23309输出）、FlashLite22次（15068/14624）、embedding56次尝试（214761输入，含失败/未知）。Hydrogen原4次上限和付费兜底保护未改。公开检索真实检查仍被非公网DNS安全拒绝，测试追踪关闭；独立质量真值/新模型评测预算、公网HTTPS/评审运行与正式视频PDF仍未完成。

三条本轮新输入演示：①资料包v7/v1改名上传→同论文版本比较，原扫描→Paddle/MinerU新快照→搜索高亮；②原教材541页→32页取消恢复→空白页核验→后半部与末页定位；③39份资料页数生成CSV→绘图与五类导出，并展示损坏PDF422。新增测试脚本只执行明确步骤；不要重跑任何会消费供应商配额的历史smoke脚本，不迁移/重置原账本。遗留10文件/请求上限未变，本次逐文件导入不声称20文件原子批量上传已验收。


## 2026-11-16 审阅升级进行中（最新）

审阅包基线cc54691，增量实现细节与当前PASS/FAIL/NOT RUN见 `docs/UPGRADE_STATUS_20261116.md`。核心集限定v1/v7/扫描版/541页教材，其余35份拓展。395项完整工程回归通过；真实20篇批量导入、3.6Flash双向翻译、Decision1原生11例校准与双卡本地模型已有证据。核心问答保留首次失败和复验partial；核心4索引仍在构建，未冒称全量向量完成。原smoke4与旧账本没有重置；本轮新增授权各模型每日40次，失败/unknown照计，付费兜底仍关闭。

运行服务已拆成researchtrace-api、worker-documents、worker-interactive、parser，以及本项目loopback检索隧道；旧单worker单元已停用，旧源码/用户ZIP/RAR及未跟踪文件保留。所有新增结果见 `evidence/review-upgrade/`，管理员流程已追加真实运行记录。不要据此宣称公网、正式赛事视频/PDF或全部质量门槛完成。

核心4索引已完成：run `e5d48e5600a947438dd3a5d0ca45c19d`，generation `fcdff7af26f44e369897bf3ee452089f`，5267合格源块→5330片段/5330向量，完整后已激活，云调用0。全39的staged代 `53ffb2e2e9c14cab81b122e9a4b50857` 有23185片段尚未构建全部向量。后续优先真实混合检索与核心4问答复验，并完成Qwen同切分对照、其余35拓展与公网/材料。

## 2026-11-16 全量审阅与最终重构计划（最新）

本阶段只做审阅和规划，没有修改产品代码。完整读取赛题原件、任务书、验收、审阅包与全部前后端源码后，产出 **`docs/REFACTOR_PLAN.md`**：后续开发按该计划的工作包、时间块和取舍清单执行。项目名保留“研证 ResearchTrace”，定位语改为“每个结论都能回到原文的科研智能体”。

本阶段实际执行（干净检出，Python 3.13.18 / Node 22，非锁定的 3.12 环境；无供应商密钥，模型调用 0 次）：
- `pytest tests/unit tests/integration`：477 passed、7 skipped，38.62 秒，日志 `evidence/refactor-plan/pytest-20261116.log`。
- `npm ci && npm run build`：通过；主包 1.07 MB（gzip 321 KB）。
- 本地启动 API 与两个 worker 池，经浏览器上传 9 份资料包 PDF：全部解析完成，页面巡检无页面异常；刚上传尚未解析的文档会留下页面数据 404 的控制台记录。截图见 `evidence/refactor-plan/`。

本次实测确认的缺陷（均写入计划并排了优先级）：默认原生解析下 LoRA 标题为“RA: -R”、ViT 标题为“16 16”；9 份中 8 份 `metadata.author` 为空，作者与机构被压成一个段落；无发表年份，图谱节点全部“年份未知”；目录为无层级的平铺列表；核心模型默认每工作区每日 2 次；规划 Agent 与路由默认关闭；仅 Gemini 一条模型通道；无流式输出、无多轮对话；参考文献批量下载、综述、论文框架、结构图生成等功能缺失；前端源码为超长单行、无路由/数据层/Lint/测试；无 CI，Compose 未实际运行。

未做：公网部署、任何真实模型调用、正式视频与 PDF。需要团队先完成的人工动作见计划第 10 节（确认截止时刻、评审期模型与预算、GPU 主机与隧道、ECS 与域名、团队信息）。

## 2026-11-16 重构第一阶段（最新）

按 `docs/REFACTOR_PLAN.md` 实施了 U1–U5 的主要部分和前端重建，全部在分支 `claude/bold-bardeen-wbi2ov`，逐阶段提交。

- **模型角色链**：`RT_MODEL_DEEP/ANSWER/LIGHT/VERIFY` 按顺序配置模型；只有本地额度拒绝或上游明确报错才换下一个，状态未知的请求不重发；503 在整条链失败后延迟重试一次；单任务与单工作区跨模型调用上限。`.env.example` 写明评审期示例（两个独立项目，各 20 次/日 Hydrogen 与 3.6 Flash）。
- **文献卡片**：解析完成后自动生成；标题字号聚类（修复 LoRA、ViT 标题）、作者顺序与单位/邮箱（模型抽取但每个字符串必须在原文出现）、年份、会议、摘要、PDF 书签分级目录、资产计数。接口 `/documents/{id}/card`、`/documents/{id}/outline`。
- **问答**：中文/多篇问题先改写为英文检索查询并逐篇融合；元数据问题带入作者原文块；多轮对话 `thread_id`（服务器读取同线程历史）；模型名中的数字不再被当成数量；与主张不一致的自由文本被替换为已核验主张文本而非整体失败；复核模型不可用时保留“待复核”而非任务失败。
- **前端**：新设计系统与路由（工作台、文献库、证据问答、比较、检索、图谱与核查、写作工坊、设置），逐句证据灯、证据弹出与 PDF 高亮跳转、可读执行记录、文献卡片抽屉、分级目录、阅读时紧凑导航。
- **部署**：Compose 拆分两个 worker 池并加入 Caddy 自动 HTTPS；配置已校验，镜像构建在云沙箱因网络限制 BLOCKED。

真实调用（开发密钥，单项目）：官方单篇 Q1–Q5 均得到带原文出处的正确回答（Q1 Aidan N. Gomez / University of Toronto）；多轮追问“其中 Adam…”在浏览器中通过；BERT 与 Transformer 编码器关系正确；GPT-1 上下文长度仍因关键词检索未召回而标“证据不足”，GPT-2 原文不在资料包中。开发日账本：Hydrogen 约 7 次、3.6 Flash 当日 20 次用尽、Flash Lite 若干，含失败与未知计数。

仍未完成：语义向量索引（下一步启用 Gemini embedding 或本地 GPU 服务）、参考文献按重要性批量下载、综述生成、论文框架与结构图生成、中译英独立入口、推荐理由与代码线索增强、公网部署、正式视频与 PDF。需要团队完成的人工动作见计划第 10 节。

## 2026-11-17 实际增量继续

当前 `upgrade/complete-20261116` 继承 Claude `6b02876`，已合入文档版本/参考文献、阅读器划词、写作/图谱和ECS工作。先看 `docs/COMPLETION_20261117.md`、`evidence/completion-20261116/summary.json`，其中BLOCKED不能改成已完成。用户已配置researchtrace.sluna.xyz DNS，真实TLS、独立评审登录和文献库通过。

仍有两个独立索引运行：云核心901片段记录于 `cloud-core-production.json`；本地full39运行 `bac8f0615125421191e1a8d6c150c460`，14466/23185的历史进度保留，另设受限CPU offload broker18989。先查实际PID/运行锁、显存及日志，不重复启动。旧失败/staged代均保留，不修改manifest伪造续建。云索引改切分必须与固定输入A/B分开报告。共享GPU每卡至少2GiB，只清理本项目进程。

两凭据按用户声明的两个项目配置；实际Flash1日20已限流、Flash2探针成功。旧gemini-shared账本通过RT_LEGACY_PROJECT_MAP保守归入project1，原四次smoke和所有未知调用不重置。Embedding批量按文本条数计请求单位。源码、密钥、账本切换需防止两端同时对同模型花费且互相不知；ECS初始只读/无模型密钥，仍待最终启用。禁止把HTTP尝试数误当Embedding剩余额度。

已完成实际6页技术PDF及6分钟1080p普通话视频，在deliverables；视频展示真实页面和有时间的历史结果，正式内容人工审阅仍未执行。团队姓名学校现在不需要。不要造v1.0-submission标签；发布门槛未全部关闭。


## 2026-11-17 公网账本与索引切换（覆盖此前“待启用”）

- https://researchtrace.sluna.xyz 已运行HTTPS、生成及云检索。ECS为唯一云调用端；本地RT_PROVIDER_MODE=disabled，禁止在独立旧账本上直接恢复本地云调用。
- 核心4云代65c9a6b50cc94942af343c98f6cafd56已ready，901向量/5267原文块。ECS只合并Embedding新账本，保留同期生成记录。新30天账号私有文件data/completion-deployment/reviewer-20261117.json，6231实际向量复制、0重算。
- 先看docs/COMPLETION_20261117.md、summary.json、public-runtime.json。公网语义问答、独立浏览器、中文整篇英译有真实证据。尚未关闭全部发布门槛，不创建提交标签。
- 全39索引在运行锁下续建。多卡broker18990，隧道PID为data/completion-deployment/final-gpu-tunnel.pid。实时查数据库进度，不按旧日志猜；每卡保留2GiB，只清理本项目进程。CPU超时broker已清理，失败保留。
- 新实现：无证据回答标partial；工具反馈具体参数约束；写作只修拒绝主张一次，仍不合格则明确留缺口；参考分类分批持久化、冲突保守设uncertain。Provider JSON Schema提示简化不改变本地校验。
- 新输入三路径：PDF→版本/快照→问答原文；论文检索→合法全文→时间条件核查；中文全文译英文或CSV→受控图表导出。Future Work覆盖类别、综述质量和人工准确性以真实记录为准。
- 原smoke4不重置，失败/unknown均计账。GitHub Actions因账户计费锁未启动，需要账号所有者解除外部锁；不能标CI通过。团队署名现在不需要。

## 2026-11-17 全量本地代完成（优先于以上历史进度）

- 本地full39 53ffb2e2e9c14cab81b122e9a4b50857 ready：23185/23185向量、22950合格原文块、2189排除。ECS已逐段核对并原子激活，账本0改动；旧failed/14466元数据已核对同manifest后补齐。不要重建已完成本地索引。
- Nemotron全80题+真实重排已完成，核心/拓展有答案45/30：重排全部金标@20为45/45、30/30，首个金标前5为44/45、24/30。含改写相关性，人工金标审查NOT RUN；Qwen仅核心对照，不虚报其完整80题。
- 新评审完整种子私有data/completion-deployment/reviewer-full-ready-20261117.json，29416向量直接复制0调用；此前full文件实际只6231条且已明确BLOCKED，不要混淆。旧账号仍可使用。
- 公网新输入PDF完整链已PASS；源码最新643项后端回归，后续写锁保护另有专项与全量日志。后台文档/交互池保持分离。
- 用户强调本地部署为主：发布配置local优先auto、认证回环18990/18991；云代独立，仅在本地不可用且云有完整对应索引时备用。共享GPU冷启动很慢，不能把manifest可达当作及时推理保证。
- 其余35云预检任务8682a242a7e34f7a8d4e26d8c0e3829d /代0ed88892305d4a0091007384f7c8a3fc因种子复制持写锁失败，769元数据尝试/0Embedding单位；先核对unknown/reserved与私有回执。不得重置账本，云索引不是本地验收前置。

最终v12回归：645 passed in 135.80s，worker-safe-final-regression.log。公网RT_EMBED_PROVIDER=auto，主检索本地Nemotron，认证回环18990/18991，云只做独立代际备用。35云预检写锁留下的一条reserved已有同quota_id原生计数回执，核对后补记ok/0Embedding单位，无请求重发、无账本重置；cloud-preflight-receipt-recovered.json。

## 2026-11-17 技术文档 LaTeX 版与两处解析/绘图修复（最新）

- 分支核对：`upgrade/complete-20261116`（864ef38）即最新代码；`origin/main` 仅多一个合并提交，文件树与本分支一致；`claude/bold-bardeen-wbi2ov` 是已被继承的旧分支。
- 新增 `docs/tech-report/`：赛题 2.3 技术文档的 XeLaTeX 源码（ctex + TikZ/pgfplots），`./docs/tech-report/build.sh` 编译并复制到 `deliverables/ResearchTrace_技术文档.pdf`，当前 27 页（上限 30）。27 张图中架构/流程/数据图全部为矢量源码；检索评测曲线与热力图由 `tools/make_figdata.py` 从 `evidence/review-upgrade/retrieval-*.json` 计算，不手填。旧的 6 页 `ResearchTrace_技术说明.pdf` 保留未动。
- 文档口径按用户要求突出已验证能力，局限写入“展望”；所有数字均可在 evidence 与测试日志中找到来源，未写入问答准确率、CI 通过等没有证据的结论。封面团队信息留空（`main.tex` 顶部宏）。
- 界面截图：本云端会话无模型密钥、公网站点不可达，故在本地无密钥模式导入资料包 20 篇论文后实拍文献库、文献卡片、阅读器、图谱、CSV 图表（拍摄时用 CSS 隐藏了“模型未配置”提示条）；问答定位图沿用 `docs/images/reader-evidence.png`。正式提交前建议用公网环境重拍问答页并替换 `docs/tech-report/figures/`。
- 代码修复两处（均有回归）：① `cards.layout_title` 对混排字体标题在接缝处重复读字符（FlashAttention 被读成 “FlashAttention : n: Fast…”），改为先合并垂直重叠的行，并去掉标点前的多余空格；资料包 37 篇原生 PDF 标题逐篇核对正确。② `charts.py` 绘图模板只认 Droid 字体路径，非容器环境中文图标题显示为方块；改为依次尝试 Droid / Noto Sans CJK / 文泉驿。
- 验证：本会话 Python 3.13.18 全量 `pytest tests/unit tests/integration` 为 645 passed、1 skipped（含新增的 FlashAttention 标题回归用例；修复前为 644 passed）；前端 `npm run build` 通过；模型调用 0 次，未触碰 ECS 与账本。注意：仓库根目录存在开发者 `.env`（如 `RT_PROVIDER_MODE=disabled`、`ENABLE_DENSE=false`）时，`test_parsed_index_tasks` 等 6–7 项会失败，属于测试隔离问题，尚未修。
- 仍未做：5–8 分钟演示视频（2.2）；本轮发现但未改的问题见会话最终报告（文献卡片摘要断词、无标题时图注以冒号开头、默认只画前三列、主包 1.07 MB 等）。


## 2026-11-17 WSL US 开发环境迁移（本机配置）

用户明确分工：`wsl-us` 只作代码开发，公网仍由 ECS 服务，GPU node01 作为独立检索计算节点。源项目工作区未覆盖；迁移基线 `f3acf79` 包含当前远端 `fb9daee`，源目录的9个未提交文件已私下归档，没有把旧虚拟环境或 node_modules 搬入新环境。

目的地为 `/home/dev/projects/ResearchTrace`（WSL `Ubuntu_24.04_US`，SSH `wsl-us`）；Node22.16.0校验官方SHA256安装，Python3.12新建`.venv`，49个锁定wheel重新安装，前端`npm ci`。额外安装Tesseract、CJK字体和浏览器验收依赖。VS Code本地工作区设置指向`.venv`，大量私有数据不参加索引/搜索。

一致性备份已恢复到`data-migrated`，SQLite完整性ok、120个版本路径均存在、36,890向量保留；quota/quota_context/quota_request_units/provider_state的内容哈希与快照一致。原主空间45份文献以新的本地访问码绑定，凭据只保存在`.env`与`~/rt-private/local-access.txt`（0600），从`rt-info`查看。`data-migrated/`加入本地Git排除；检索token0600，未公开。新`.env`的Gemini key为空、`RT_PROVIDER_MODE=disabled`、付费兜底关闭，不把独立库当成ECS的实时额度账本。

使用新的专用SSH密钥`~/.ssh/id_ed25519_researchtrace`和别名`rt-gpu`，主机密钥沿用已验证指纹，禁用Agent/X11转发。`rt-gpu-start`仅按需建立Embedding18990、Reranker18991、下载代理18987三个回环隧道；`rt-gpu-stop`停止。`rt-start/rt-stop`用于临时完整联调，后台单元显式加入`us_ns`，避免普通用户systemd启动脚本跑出网络命名空间。本次验收后全部开发服务已停止、没有开机自动启动；生产ECS和GPU已有服务未修改。此环境优先使用这些命令，不调用旧`./scripts/dev.sh`安装普通用户后台单元。

GitHub/默认联网继续经us_ns固定代理；显式使用18987会改用GPU服务器代理出口，故没有设为全局HTTP_PROXY。项目启用现有`RT_PUBLIC_DNS_RESOLVER=https://dns.google/resolve`以适配Fake-IP，保留SSRF、真实公网IP固定连接和TLS校验；系统代理/DNS/防火墙不改。正常GPU检索使用既有离线模型；远程SSH shell里另行执行的联网程序仍走服务器自己的网络，不继承WSL固定出口。

测试入口`rt-test`使用python-dotenv自带`PYTHON_DOTENV_DISABLED=1`，仅在测试进程内忽略开发者.env，不移动/覆盖配置。无.env完整检查为640 passed/6 skipped（136.21秒），Ruff、TypeScript/Vite和OpenAPI导出通过；已有.env时对受影响索引任务7项回归通过。私有日志在`~/rt-private/migration-logs/`。

真实本地模型验证：Embedding4096维、L2归一和指纹匹配，248.537秒；2文段Rerank相关项顺序正确、指纹匹配，239.476秒。包含首次冷启动，不能用healthz可达代替及时推理。未重建已有向量、未调用云生成，云账本哈希未变。真实UI登录、45份文献、PDF.js翻页、36条参考文献、历史3条证据定位回PDF第5页、Vite均通过；pageerror0、意外HTTP错误0。浏览器私有证据在`~/rt-private/migration-browser/`，首轮验收脚本选择器失败记录保留。

ECS现状只读核对：生成仍发Gemini，检索/重排经现有ECS回环18990/18991到node01；Gemini及公网文献的ECS代理仍为18987。ECS鉴权manifest实际返回Nemotron/Qwen模型；不经过新WSL。这次没有修改ECS、生产GPU服务或推送GitHub。


## 2026-11-17 阅读器重做与界面统一（最新）

- 起因：用户反馈阅读器只能点翻页、无法滚动；「中英对照」丢失版式；缺少好用的划词翻译；界面不协调且充满技术词。
- 阅读器：`apps/web/src/PdfReader.tsx` 改为连续滚动、按需渲染；`src/reader/` 新增 `usePdfDocument`（原文只载入一次）、`TranslationPane`（逐段对齐译文，图表公式裁剪原页）、`PdfCrop`、`SelectionPopover`（浮动划词卡片）。`Reader.tsx` 重写为可读格式，功能保持：目录编辑、参考文献往返跳转、引用标记、全文搜索、解析快照、概览卡片、选段解释/提问、译文导出。样式在 `src/styles/reader.css`，`app.css` 原第 7 节已移除。
- 全局：`tokens.css` 换成冷灰中性色板与浅色侧栏；阅读/对话页占满一屏；顶栏阅读时显示论文标题；去掉「数据持久化」和模型徽标；文献库与首页不再显示语义索引等技术状态。
- 验证见 docs/TEST_REPORT.md 同名小节：阅读器浏览器回归 20/20、后端 640 passed/6 skipped；真实译文显示未验证（本地无密钥）。
- 待办：有密钥的环境中用真实译文复查对照视图；视频与技术文档中的阅读器截图仍是旧界面，提交前建议重拍。


## 2026-11-19 问答界面、划词重影、游客模式与演示视频 v2（最新）

- 用户反馈：读论文划词有明显重影；问答页太乱，答案被执行链和检索 JSON 淹没。另外要求增加游客模式（免访问码，默认 Gemini 3.5 Flash Lite + Gemini embedding，进入时弹窗提醒性能下降和额度），并重录用于评审的视频。
- 划词重影：原因是全局 `::selection` 颜色覆盖了 PDF.js 透明文字层，已修复（`apps/web/src/styles/selection.css`）。阅读器回归现在加载 theme.css 并做断言。
- 问答：`components/AnswerView.tsx` 与 `RunPanel.tsx` 重写为对话式回答卡片，正文加引用编号，核对、来源、过程、复制和导出用图标展开，默认折叠。运行中只显示一行进度。阅读器助手面板和 `/runs/:id` 页面也显示提问。
- 游客模式：`services/api/guest_mode.py`、`/api/v1/auth/guest`、`/api/v1/guest/status`，前端在 `features/guest/`。线上启用需要在 ECS 的 `.env` 里设置：
  - `RT_GUEST_MODE=true`
  - `RT_GUEST_SEED_WORKSPACE=<一个小的模板空间 id>`：建议只放少量核心论文，并已有 ready 的 Gemini 代际，否则游客只有关键词检索
  - 额度相关的 `RT_GUEST_*` 见 `.env.example`
  
  游客调用计入同一项目账本，不是额外额度。到期清理只删语料副本，不删 runs 和账本。**线上尚未部署和验收**，部署后需在公网用新浏览器走一遍游客流程，并用 1–2 次真实 Flash Lite 调用做冒烟（计入账本）。
- 视频 v2：`deliverables/ResearchTrace_演示视频_v2_1080p.mp4`（6:06，1080p，离线 MeloTTS 普通话配音，字幕烧录），另有 VTT、封面和 `video-v2-evidence.json`；旧视频保留未动。
  - 重录：`scripts/video/record_demo.py`（录制与合成）、`slides.html`（片头和技术页）、`narration_v2.json`（讲稿与数据来源）、`retrieval_eval.csv`（由检索评测证据生成）。
  - 回放：`scripts/replay_saved_answers.py` 把 11-18 的真实回答导入本地空间，引文按原文重新定位，找不到就中止。
  - 视频里的问答是回放，中英对照和扫描件两段是 11-18 实拍截图，画面都有标注。
  - 未人工试听，提交前请团队完整看一遍；如需真人配音，可替换 `audio/` 下的音频后重新合成，脚本按每行的实际时间对齐。
- 测试：后端 666 passed、9 skipped；游客集成 8/8；阅读器 22/22；问答布局 23/23；游客流程 13/13。详见 docs/TEST_REPORT.md 同名小节。本轮模型调用 0 次。
