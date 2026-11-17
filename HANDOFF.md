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
