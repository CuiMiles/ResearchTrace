# Ubuntu24 验收报告

当前状态：基础服务、原生解析、不可变解析快照、PaddleOCR CPU 与 MinerU CPU 公式/表格/结构化解析、以及离线/浏览器非模型交互验收已实测通过；MinerU GPU（受 WSL2 NVML 限制）与需新模型配额项标为 BLOCKED，新环境结果与旧主机历史证据分开记录。

本机入口 http://127.0.0.1:18980；环境 Ubuntu24.04.5 WSL2、Python3.12.3、Node22.16.0、RTX4060Ti8188MiB。源码和四个SQLite库已迁移，密钥与运行数据私有保存。已知环境与产品边界见 `docs/KNOWN_LIMITATIONS.md`。

## 本轮实测

- 自动回归 `./scripts/test.sh` 当前 **142 passed**（`evidence/competition-dataset/regression.log`）；单独重复运行的子集不累计相加。
- 前端 `tsc --noEmit` / `vite build` 通过（发布 168 个构建文件），后端 `ruff` 与 `packages/contracts/openapi.json` 导出通过。
- 无密钥隔离 API/worker 真实启动、上传、解析、阅读、搜索和 CSV 绘图通过。
- PaddleOCR 3.7.0 / PaddlePaddle 3.2.2 真实双语 CPU 识别：PNG 7.82 秒、峰值 RSS 968368 KiB；产品单页快照 8.69 秒，中文文字层、FTS 与 PDF 坐标高亮通过。
- **PaddleOCR-VL-1.6**（两阶段隔离：`PP-DocLayoutV3` -> PyTorch `bfloat16` `PaddleOCR-VL-1.6-0.9B`，34 文件清单 `evidence/ubuntu24/paddle-vl-model-manifest.json`）真实 CPU 双语解析 `scan-bilingual.pdf` 通过：132.67 秒（`evidence/ubuntu24/paddleocr-vl-cpu-product.json`），Chromium 浏览器文字层/FTS/黄色坐标高亮通过（`evidence/ubuntu24/browser/paddleocr_vl-reader.json`）。
- **MinerU 4.2.2**（`mineru[torch]==4.2.2`，19 文件清单 `evidence/ubuntu24/mineru-422-model-manifest.json`）真实 CPU 结构/公式/表格/双语解析通过并保留旧快照与账本不变：`equation.pdf`（14.29s，`evidence/ubuntu24/mineru-cpu-equation.json`）、`table.pdf`（含完整 HTML BLEU Table 2，15.82s，`evidence/ubuntu24/mineru-cpu-table.json`）、`formula-page4.pdf`（含 LaTeX Attention 公式，23.73s，`evidence/ubuntu24/mineru-cpu-formula.json`）、`scan-bilingual.pdf`（9.20s，`evidence/ubuntu24/mineru-cpu-product.json`）；浏览器公式/表格/双语黄色 PDF 坐标高亮通过（`evidence/ubuntu24/mineru-graph-browser.json`、`evidence/ubuntu24/browser/mineru-reader.json`）。
- MinerU GPU 模式在 WSL2 按 fail-closed 显存保护实测阻塞：`/usr/lib/wsl/lib/nvidia-smi` 可见 8188 MiB RTX 4060 Ti，但 WSL2 NVML `--query-compute-apps` 进程显存恒为 `[N/A]`，监控终止本项目会话并返回 HTTP 503 `GPU accounting unavailable; stopping this job conservatively (WSL/NVML)`（`evidence/ubuntu24/mineru-gpu-monitor.json`）。
- 浏览器补充矩阵在 `http://127.0.0.1:18980` 全部通过（0 报错、0 越权写操作）：D02 正文与文献往返、D03 双向段落同步、D05 全状态矩阵（loading/partial/500/401/empty/429/parse-failed，`apps/web/validation/reader-extra-20261115T143101401610Z.json`），以及 E06 20+ 篇真实图谱交互与重算（29 节点/72 边，1440/1280 无溢出，`evidence/ubuntu24/mineru-graph-browser.json`）及 E08 确定性 `md`/`html`/`bib` 导出。
- 原生 Transformer v7/v1、BERT、派生扫描件通过；541页自编夹具在30页强制中断后恢复，末页可检索，恢复进程RSS109364KiB。该条仅为此前工程夹具记录；本次已另用用户资料包的原扫描15页与指定教材541页实测通过，见下方新资料记录。
- 三个真实评审workspace并发上传，在512M API/896M worker限额下完成；API+worker分别峰值相加153112576字节。独立重型解析worker不计入lite结果。
- 本轮新增供应商调用0；Hydrogen4、FlashLite22、embedding56尝试账本保留；Hydrogen冒烟已耗尽，不自动重置或收费兜底。
- 验收统计（A01–F15 共 64 项，机器可读详见 `evidence/ubuntu24/acceptance.json`）：**48 PASS**、**16 BLOCKED**、**0 FAIL**。

## 逐项状态

字段完整的机器可读记录见 `evidence/ubuntu24/acceptance.json`。PASS只覆盖所列命令和输入；模拟异常测试只证明异常处理，不证明上游服务实时可用。

| ID | 项目 | 状态 | 观察/范围 |
|---|---|---|---|
| A01 | 全新目录安装 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| A02 | 无密钥启动 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| A03 | 有密钥真实请求 | BLOCKED | Hydrogen four-call smoke budget is exhausted; no new provider generation authorized for this migration acceptance. Historical real calls remain in evidence/. |
| A04 | 重启恢复 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| A05 | 清洁构建 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| A06 | 本地与公网分开 | BLOCKED | Local18980 is verified; public HTTPS and reviewer login from outside are not provisioned or tested. |
| B01 | 双栏阅读顺序 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| B02 | 公式与表格 | PASS | 用户资料包15页原始扫描件通过 MinerU4.2.2 CPU（352.72秒，138块：4表格/6公式），实际表格与公式PDF高亮浏览器通过；GPU仍为单独BLOCKED，不计作GPU推理成功。 |
| B03 | 扫描件新输入 | PASS | 用户提供的1706.03762v1_img.pdf完整15页，经PaddleOCR CPU（234.44秒/311块）与MinerU CPU（352.72秒/138块）真实产品路径及浏览器定位通过。VL仅裁剪第4物理页区域（139.22秒/6块），不宣称全文VL测试。原包来源渠道未独立认证。 |
| B04 | 同一文件重复上传 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| B05 | 改名后的版本识别 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| B06 | 相似但不同论文 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| B07 | 版本差异可追溯 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| B08 | 旧引用不漂移 | PASS | 本次CPU/GPU解析修订逐个保留旧快照文字/块ID/bbox哈希；教材v1首次部分失败仍保留，v2独立修复发布。历史已有引用未重写。 |
| B09 | 长文完整处理 | PASS | 指定原教材541页全处理通过：pdfplumber-layout-v2新快照88.02秒/5315块，4张空白页经结构+渲染核验记blank；旧v1失败记录保留。全文FTS及中后部/末页定位通过。 |
| B10 | 后半部随机查询 | PASS | 本批39份原资料122次实际正文词FTS→版本/快照/物理页/块/bbox定位通过，包含教材后半部按文件哈希为种子选取的3个页面及第541页。仅验证关键词定位，不是语义问答质量评测。 |
| B11 | 中断与恢复 | PASS | 实际原教材在32个已提交页面时API取消，等待执行锁释放后恢复至541页，检查点块哈希不变；最终空白页修复使用独立v2快照。原MinerU两页取消恢复证据亦保留。 |
| B12 | 内存与页面懒加载 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| B13 | 文件删除与权限 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| C01 | 精确细节问答 | BLOCKED | Historical source fact answers exist; new live core facts require a separate generation budget. |
| C02 | 混合检索真实存在 | BLOCKED | Real migrated dense vectors and RRF code exist; provider-query ablation in this environment is blocked by the no-new-model acceptance scope. |
| C03 | 点击定位 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| C04 | 引用与主张匹配 | BLOCKED | Location/quote membership verified; independent substantive support quality review is not complete. |
| C05 | 无依据问题 | BLOCKED | Historical missing-evidence result retained, but no new Ubuntu24 model response may be claimed. |
| C06 | 跨文事实表 | BLOCKED | Historical comparison source bounds retained; new cross-document model run blocked by budget. |
| C07 | 版本隔离 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| C08 | 新 PDF 和新问题 | BLOCKED | New PDF import/index/source-location passed; a new live core answer remains blocked by exhausted Hydrogen budget. |
| C09 | 恶意文档指令 | BLOCKED | No shell/download permission escalation exists and local malicious-input tests pass; a new model-level injection run remains blocked. |
| C10 | 引用修复有界 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| D01 | 目录定位 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| D02 | 正文与文献往返 | PASS | Browser verification PASS for source-marker jump to reference and scroll restoration (reader-extra-20261115T143101401610Z.json). |
| D03 | 双向段落同步 | PASS | Browser verification PASS for bidirectional synchronized scrolling between source and bilingual blocks (reader-extra-20261115T143101401610Z.json). |
| D04 | 全文翻译 | BLOCKED | Full120-block historical BitNet translation remains stored; independent translation quality review/new Ubuntu24 generation not complete. |
| D05 | 可见 UI 状态 | PASS | 原UI九状态矩阵保留；新增真实教材空白页提示，以及管理员十步流程发布前/后点击、真实结果展示、5秒保留选中刷新、桌面/390px无溢出通过。 |
| D06 | 浏览器视觉检查 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| D07 | 真实 streaming | BLOCKED | Actual persistent SSE tool events/reconnect are implemented and tested; new live provider streaming not executed. |
| E01 | 标题/ID 检索入库 | BLOCKED | Fresh bounded HTTP arXiv/Crossref checks attempted2026-11-16. System DNS returned198.18.* nonpublic addresses, rejected by existing SSRF guard before source content. Real metadata import is still BLOCKED; no source bytes fetched. |
| E02 | 限流与网络失败 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| E03 | 追踪查询 | BLOCKED | Manual live watch check attempted and honestly failed on nonpublic DNS; scheduled-source acceptance NOT RUN after the2-operation/source ceiling. Concurrency, crash recovery, disable/cancel, fresh cache, scheduler fairness fixtures PASS; testwatchdisabled,preexistingwatchesunchanged. |
| E04 | 推荐反馈 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| E05 | 真实引用边 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| E06 | 20 篇级图谱 | PASS | 39份原始PDF全文已处理，v1/v7合为同作品（38个原作品），加1份裁剪辅助PDF构成39节点/162条定位引用记录（160条去重有向关系）；真实浏览器节点检查器通过。匹配精度未独立人工标注。 |
| E07 | 旧 idea 后续核查 | BLOCKED | Historical real Transformer/Longformer audit retained; new live Future Work synthesis is blocked by Hydrogen budget. |
| E08 | 源约束写作 | BLOCKED | Deterministic stored-note md/html/bib exports PASS in browser (mineru-graph-browser.json); fresh source-constrained writing generation BLOCKED by Hydrogen budget. |
| E09 | 可编辑结构图 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| E10 | 新 CSV 绘图 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| E11 | 数值与坐标 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| E12 | 图和脚本可复现 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| E13 | 不夸大研究结论 | BLOCKED | Prompt and deterministic caption policy unit tests pass; fresh live scientific-claim quality audit BLOCKED by model budget. |
| F01 | 项目级额度 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| F02 | TPM 预留 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| F03 | RPD 复位 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| F04 | 日额度耗尽 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| F05 | 百炼免费用尽 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| F06 | 费用保护 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| F07 | 幂等与 SSE 重连 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| F08 | 上游响应异常 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| F09 | 取消和恢复 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| F10 | 队列与并发 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| F11 | 凭据隔离 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| F12 | SSRF/路径穿越 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| F13 | 绘图执行隔离 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| F14 | 工作区隔离 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| F15 | 降级诚实 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |

## 外部与赛事交付

| 项目 | 状态 | 原因 |
|---|---|---|
| 官方扫描件与指定教材 | BLOCKED | 原件未提供，派生夹具不能替代官方通过 |
| 独立50题与三基线质量评估 | BLOCKED | 缺独立审核真值和单独明确的模型评测预算 |
| 公网HTTPS/评审登录 | BLOCKED | 未配置或验证独立公开入口；未改域名和已有站点 |
| Docker Compose运行 | BLOCKED | 本机未安装Docker；本地systemd运行与cgroup实测已完成 |
| 正式参赛视频 | NOT RUN | 脚本不等于最终视频 |
| 正式技术PDF/最终提交 | NOT RUN | 现有Markdown不等于正式PDF；未执行提交 |

## 复跑与边界

`./scripts/test.sh` 为自动测试入口；为保留旧证据，本轮日志主要写入 `evidence/ubuntu24/`。`scripts/validate_parser_live.py`只做真实本地解析、不调用模型；`scripts/validate_no_key_live.py`只启动和清理自身测试进程。所有仍有预算阻塞的live项保持BLOCKED。不要再次运行live smoke或关闭RT_SMOKE_MODE来制造通过。

解析错误、预检失败、未完成GPU测试等原始记录均保留；后续真实MinerU结果会继续追加，不把预检当推理成功。

## 2026-11-16 继续开发与回归

保留用户最新提交 `ba83619` 的 MinerU4.2.2 / PaddleOCR-VL-1.6 和管理看板。修复最后一页取消/删除仍可能写回、低质量页面恢复时覆盖冲突、混合解析器版本续跑、翻译排队后原文快照漂移和跨快照译文计数。取消执行的资源释放与恢复之间用OS文件锁协调，409是等待释放而非启动新进程。管理员证据符号链接逃逸被阻断为404。

真实 MinerU4.2.2 CPU 两页恢复：28.42秒，第一页6块保持不变，取消第二页的本项目会话后恢复完成12块/2页；旧快照文本与bbox哈希一致。日志和监控：`evidence/ubuntu24/parser-recovery-20261116.json`。这不增加官方长教材/GPU验收结论。

追踪检查加入跨进程锁、崩溃恢复、失败后推进next_check、取消/禁用保护与强制新鲜搜索。真实检索在当前DNS路由被SSRF防护阻断，E01/E03保持BLOCKED；没有修改其他服务代理或放宽非公网地址限制。每来源最多2次操作，未抓到的来源正文没有伪造hash。

新增解析边界测试区分fixture与真实推理；完整自动回归133passed（单独子集不累计）。当前VL增强校验曾暴露NumPy版面JSON序列化问题，失败日志保留于 `paddleocr-vl-20261116-layout-failure.*`，修复后真实复测结果单独追加。所有本轮供应商调用0；Hydrogen4/Flash22/embedding56账本保留。

VL修复后的真实复测：PaddleOCR-VL-1.6 CPU双语产品链路 **PASS**，156.58秒/6块、runner峰值RSS2470152KiB，期间完整单测并行执行，因此不作为独立性能比较；文字、FTS与PDF坐标浏览器复核 **PASS**，见 `paddleocr-vl-20261116-product.json`、`paddleocr-vl-20261116-runner.json`、`browser-20261116/paddleocr_vl-reader.json`。管理看板浏览器复核也通过（`admin-browser-20261116.json`），状态筛选支持动态数量，未把E01/E03阻塞标为成功。

截至本次交付，64项总状态仍为46PASS/18BLOCKED。新修复的局部恢复用例不另计为官方验收新增通过项；官方原件、独立质量评测、公网评审入口和WSL GPU限制保持各自阻塞。

## 2026-11-16 用户原资料包实测

先发布管理员十步流程，再开始功能测试，顺序由 `browser-before.json` 与 `workflow.json` 的 UTC 时间核对。输入为 `科研小助手.rar`，解压清单40个PDF（39份测试资料1986页、1份题目说明7页），原包未变；原文件被忽略，不进入源码仓库。最终39份测试资料均ready；扫描15页和教材541页的覆盖不再以自制夹具代替。

- 原教材首轮完整处理541页，但4张带裁切线的空白页误判失败。保留原始FAIL，原生v2新快照88.02秒/5315块通过，旧块哈希不变；32页取消恢复也有真实记录。
- 原扫描15页：PaddleOCR 234.44秒/311块，runner最大RSS1261320KiB；MinerU352.72秒/138块（4表格、6公式），runner最大RSS2705092KiB。VL仅第4页裁剪区域139.22秒/6块，runner最大RSS2473220KiB。重型解析独立于2GB lite目标；耗时为本机本次墙钟观测，不作独立性能基准比较。
- 122次正文词定位通过；排除了首轮选中重复页眉、目标页落在前50条结果以外造成的测试失败。初次记录及修正后的查询、快照、页、块和bbox均保留。
- 真实阅读浏览器29项检查通过；管理员流程发布前39项、发布后38项检查通过。图谱39节点/162条引用记录含1个裁剪辅助文档；原资料38个不同作品，160条去重有向关系，未宣称人工标注的匹配精度。
- 已真实下载PNG/SVG/脚本/PlotSpec/CSV；此CSV来自本批资料的实测页数，RAR本身没有CSV。实际损坏PDF422、未登录文件401、跨工作区404、路径逃逸404；读取真实教材任务SSE收到有序事件与done。
- GPU在4.6秒时被WSL/NVML显存核算保护终止，BLOCKED；仅停止本项目测试会话。公开来源仍被非公网DNS的SSRF检查拒绝。Hydrogen4次上限不变；本批0新增供应商请求，完整quota行未变。

结果入口：管理员“验收与截图”顶部“文件处理全流程”，点击任意步骤查看本批真实记录、原始JSON/log和截图。机器摘要 `evidence/competition-dataset/summary.json`，详细记录 `workflow.json`。首次空白页、测试脚本异步读取、构建类型遗漏及浏览器CSP测试写法的失败日志均保留，修复后重新验证；没有清空账本或改写旧解析结果。
