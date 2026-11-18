# Ubuntu24 验收报告

## 2026-11-19 蓝色演示字幕（公网 v37）

- **PASS** · 前端 TypeScript/Vite 构建。Windows Chrome 157、Edge 157、Chromium 1440 和 390 像素宽度的新会话分别播放、暂停检查三处画面、跳至 210 秒继续。四种场景均载入 51 条字幕。见 [公网验收](../evidence/demo-release-20261118/blue-captions-browsers.json)。
- **PASS** · MP4 全片解码，1920×1080、30 fps、385.50 秒。公网下载响应 HTTP 206。蓝字烧录版逐画面抽查，AAC 音频按字节与原版一致。网页 51 条字幕的文字与时间段逐条比对。

## 2026-11-18 学术配音实测（公网 v35）

- **PASS** · MiniMax M Plan 的 12 次新语音合成全部成功，复用已选 A 开场。47 条新字幕的时间戳按讲稿核对。
- **PASS** · 6:25、1920×1080、30 FPS，MP4 和 WebM 完整解码。Windows Chrome、Edge 和 Chromium 两种宽度均通过公网免登录播放、51 条字幕与进度跳转。正式下载返回 HTTP 206。见 [验收记录](../evidence/demo-release-20261118/academic-narration.json)。

## 2026-11-18 Windows 播放兼容性复测

**PASS** · Windows Chrome 157 和 Edge 157 在线播放、51 条中文字幕、跳至 210 秒后继续。针对旧 VP9 的本地故障注入确实触发 Windows 解码错误，两个浏览器都自动切换到新版 VP8 并继续播放。两档均模拟 503 后恢复，重试按钮再次可播放。对应 [浏览器记录](../evidence/demo-release-20261118/windows-playback.json)。

## 2026-11-18 参赛视频和访客入口（公网 v33）

- **PASS** · 正式 MP4 为 5:25、1920×1080、30 FPS、普通话，FFmpeg 从头到尾解码成功，含 51 条中文字幕。
- **PASS** · 公网新浏览器在 1440 和 390 像素宽度下无需凭据播放并能跳到 210 秒；字幕加载。MP4/WebM 都支持 HTTP 206。访客文献和问答 API 返回 401，评审账号登录后可访问 10 篇论文。
- **PASS** · v32 实际界面录制。541 页教材成功定位第 175 与 300 页，划词显示真实缓存译文，改名 v1 录完清理且文献 ID 集合恢复。首轮选区等待失败和一次公网网络切换分别复测通过。
- **FAIL** · 分段 TTS 有 1 次 503，使用之前同模型的 5 句音轨补接。另 10 段生成成功。校对 Flash Lite 请求 1 次，输出的时间点不完整，成片用本地识别确认分段时间。
- 记录和两张公网首页截屏见 `evidence/demo-release-20261118/`。没有重新执行问答验收或完整后端回归。

## 2026-11-18 界面重构与录制前彩排（公网 v32）

前端提交 `71605f2`，服务沿用 v23。之后的提交只含文档和未部署的 GROBID 网关修复。公网检查使用评委账号，证据在 `evidence/ui-redesign-20261118/`，文件内不含访问码。

| 项目 | 状态 | 实测范围与证据 |
|---|---|---|
| 后端回归 | PASS | 最后一次完整运行 659 项通过、8 项跳过，128.34 秒。见 `evidence/pytest.log` |
| GROBID 网关鉴权用例 | PASS | 此前在 3 次完整运行中间歇失败：网关返回 401 时不读请求体就关连接，客户端偶尔收到连接重置。网关改为有上限地读完请求体后再关闭。单测重复 25 次，修复前失败 5 次，修复后 0 次。该可选组件不在公网部署内，无需重新部署 |
| 前端构建与类型检查 | PASS | `npm run build` 通过 |
| 阅读器浏览器回归 | PASS | 21 项通过。此前有一次未复现的 `AssertionError` 和一次非 JSON 输出，之后换端口连续通过 |
| 公网录制路径彩排 | PASS | 16/16 步，页面错误 0。含真实上传 v1、版本弹窗、修订总结、逐段差异、保留 v7、删除 v1、对照阅读、拖动分栏、扫描版第 4 页、541 页教材目录跳转、引用定位、跨论文问答、图谱、写作证据、学术检索、任务面板。文献库恢复 10 篇。见 `rehearsal.json` |
| 公网只读巡检 | PASS | 10 篇文献，译文、引用定位到第 7 页 5.3 节，图谱一跳 7 篇 13 条引用，无页面错误、无横向溢出。见 `public-check.json`、`outline-check.json` |
| 手机宽度 390 | PASS | 本地页面无横向溢出 |
| 新问题的实时问答 | NOT RUN | 彩排打开的是已保存回答，未在 v32 上发起新的 Hydrogen 问答 |
| 实时划词翻译 | NOT RUN | 彩排选中的句子命中翻译缓存，界面显示「来自翻译缓存」 |
| 本地模型在线检索 | NOT RUN | GPU 已停止，评审期检索为 Gemini 向量加 BM25 |

## 2026-11-18 录制前定向回归（公网 v23）

| 项目 | 状态 | 实测范围与证据 |
|---|---|---|
| 文献库响应 | PASS | 同一评委账号 10 篇，服务端整条请求 5.27 → 0.48 秒。相同公网测量路径 3 次分别为 6.59/4.68/6.97 → 0.56/1.54/2.30 秒。见 `library-http-*.json` 与 `library-server-*.log`。 |
| v7 原生解析及标题分类 | PASS | 真实 1706.03762v7.pdf 完整重解析 15/15 页。第 4 页缩放点积注意力首段恢复正确顺序，独立公式保留。版权声明和脚注以正文和裁切块显示。见 `v7-local-before-after.json`。 |
| v7 Gemini 索引 | PASS | 新代 15/15 向量，覆盖新快照 150/150 块，生产状态已就绪。见 `production-runs.json`。 |
| v7 三题及原文定位 | PASS | 第 4 页缩放项由 Hydrogen 生成，多头参数与 Adam 参数由 Flash Lite 生成。真实 Chromium 分别点击并跳回第 4、5、7 页 PDF 高亮。旧 Adam 回答仍回到其历史快照。见 `browser-qa.json` 与 `browser-history.json`。 |
| 录制用对照翻译 | PASS | v7 共 15 页、150/150 块，扫描版前四页 48/48 块。翻译 API 逐页核验正文分别为 128/128 与 46/46。真实 Chromium 验证第 4 页同屏与 v7 公式裁切。见 `translation-verified.json` 与 `browser-bilingual-final.json`。 |
| Related Work 写作 | PASS | 专用论文框架任务由 Hydrogen 生成，三条主张均获 Decision 1 原文支持。浏览器打开产物、下载 Markdown，并分别定位三篇 PDF 的第 1 页。完整框架仍有待填实验和待补证据，运行状态为 `partial`。通用 Agent 两次失败分别为引文校验未通过与未找到证据。见 `related-work-outline.json` 和 `browser-related-work.json`。 |
| 代码回归 | PASS | 后端 667 项通过（147.81 秒），ruff 和 Git 差异检查通过。见 `full-backend-final.log`。 |

一次 v22 解析及自动索引在切换前执行，随后重新用 v23 解析、索引。账本记录本轮任务发起 Hydrogen 9 次（2 次失败）、Flash Lite 56 次（2 次失败）、3.6 Flash 2 次（均失败）、Decision 1 6 次、Embedding HTTP 23 次。证据见 [录制前验收记录](../evidence/recording-ready-20261118/)。

## 2026-11-18 赛题用例 3.1–3.3 首轮公网实测

| 项目 | 结果 | 证据 |
|---|---|---|
| 全量回归（本机） | PASS | `rt-test`：651 passed, 8 skipped；ruff 与 OpenAPI 导出通过 |
| 阅读器浏览器回归 | PASS | `tests/browser/reader_selection.py` 21/21，含中英对照分栏拖动/方向键/双击复位，page_errors=[] |
| 3.1 改名上传 v1 → 按内容识别同一论文 | PASS | 公网演示账号，`paper-upload.pdf`，21 秒弹出；依据「首页正文 arXiv 编号 1706.03762」 |
| 3.1 推荐保留较新版本 | PASS | 文案「库中已有更新的 v7，建议保留…」；点「保留较新的 v7」后 current=v7，v1 不参与检索 |
| 3.1 逐段差异 | PASS | 修改 123 / 新增 0 / 删除 5 / 未变 71 段 |
| 3.1 AI 修订总结 | PASS（重试后） | 01:56 与 02:10 遇 HTTP 503（8 次请求已记账）；服务恢复后在评委账号完成，gemini-4-hydrogen，5 条要点均引用差异段落 |
| 3.2 解析结构扫描（10 篇，前 5 页/长书抽样） | PASS | 无替换字符；扫描版由 MinerU 解析，标题层级、段落完整 |
| 3.2 公式显示 | 已修复，待公网复验 | 中英对照原样显示 `$\sqrt { d _ { k } }$` → 改为 KaTeX 渲染（a44aa53） |
| 3.3 引文图谱 | PASS | 公网 v20：边数 10→16，BERT/GPT-1/T5/Pre-LN/FlashAttention → Attention 均来自真实参考文献；ViT 的那条边没连上（如实缺失） |
| 3.3 单篇 RAG 问答 | PASS | 评委账号「为什么除以 √d_k」，gemini-4-hydrogen 完成；缺推导依据时明确说明 |
| 3.3 跨篇问答 | PASS | v22 修复后：Post-LN vs Pre-LN 完成（gemini-4-hydrogen）；BERT vs GPT-1 部分完成（gemini-4-hydrogen，NSP 细节如实标为缺证据）。修复前两次在约 121 秒时被中转链路断开 |
| 评审期 API 模式（GPU 关闭） | PASS | 10/10 篇有 Gemini 索引；GPU 停止后单篇问答为 hybrid（Gemini 向量 + BM25），回答 h=8、d_k=d_v=64 正确 |
| 回归 | PASS（含 1 个时序抖动测试） | 657 passed, 8 skipped；GROBID 网关测试 3 次中失败 1 次，不含本次改动时也会失败 |
| 3.3 写作 | NOT RUN | 截止前未执行 |
| 解析：标题误判 | PASS（新解析） | 真实 PDF 前后对比：v7 去掉 5 条假标题；另外 7 篇删掉的全是脚注、坐标、表格行；回归 655 通过 |

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


## 2026-11-16 审阅升级进行中（最新）

审阅包基线cc54691，增量实现细节与当前PASS/FAIL/NOT RUN见 `docs/UPGRADE_STATUS_20261116.md`。核心集限定v1/v7/扫描版/541页教材，其余35份拓展。395项完整工程回归通过；真实20篇批量导入、3.6Flash双向翻译、Decision1原生11例校准与双卡本地模型已有证据。核心问答保留首次失败和复验partial；核心4索引仍在构建，未冒称全量向量完成。原smoke4与旧账本没有重置；本轮新增授权各模型每日40次，失败/unknown照计，付费兜底仍关闭。

运行服务已拆成researchtrace-api、worker-documents、worker-interactive、parser，以及本项目loopback检索隧道；旧单worker单元已停用，旧源码/用户ZIP/RAR及未跟踪文件保留。所有新增结果见 `evidence/review-upgrade/`，管理员流程已追加真实运行记录。不要据此宣称公网、正式赛事视频/PDF或全部质量门槛完成。

## 2026-11-16 重构规划前的基线复核

环境：干净检出 `11d4cb3`，Python 3.13.18（锁定环境为 3.12，属环境差异）、Node 22；无供应商密钥，模型调用 0 次。

| 项目 | 状态 | 证据与边界 |
|---|---|---|
| 后端单元与集成测试 | PASS | 477 passed、7 skipped，38.62 秒；`evidence/refactor-plan/pytest-20261116.log` |
| 前端类型检查与构建 | PASS | 构建通过；主包 1.07 MB，超过 500 kB 分包警告仍在 |
| 本地无密钥启动与浏览器巡检 | PASS | 上传 9 份资料包 PDF 全部解析；文献库、阅读器、比较、检索、图谱、核查、写作、资源页巡检无页面异常；刚上传尚未解析的文档有页面数据 404 的控制台记录；截图在 `evidence/refactor-plan/` |
| 标题与作者元数据抽取 | FAIL | LoRA 标题为“RA: -R”，ViT 标题为“16 16”；9 份中 8 份作者字段为空；全部无年份 |
| 真实模型问答、公网、视频、PDF | NOT RUN | 本阶段只做审阅与规划 |

后续执行顺序见 `docs/REFACTOR_PLAN.md`。

## 2026-11-16 重构第一阶段验收

环境：云沙箱，Python 3.13 / Node 22；开发用单个 Gemini 密钥经环境代理注入；数据目录在临时目录。

| 项目 | 状态 | 证据与边界 |
|---|---|---|
| 后端单元与集成测试 | PASS | 507 passed、7 skipped；`test_scholarly_metadata.py::test_gateway_auth_route_whitelist_and_real_upstream_forward` 在完整套件中不稳定（单独运行通过，非首个运行时连接失败），属可选 GROBID 网关，既有问题，未修复 |
| 前端类型检查与构建 | PASS | `tsc --noEmit`、`vite build` 通过 |
| 标题抽取 | PASS | 39 份资料中 38 份标题正确；扫描件无文字层，按设计回退文件名 |
| 文献卡片（Transformer v7） | PASS | 8 位作者顺序、单位、邮箱全部正确；目录 22 项三级；arXiv 实时记录在沙箱内因 DNS 固定无法经代理而未取得（SSRF 保护未放宽） |
| 官方单篇问题 Q1–Q5 | PASS（单次运行） | 第 6 作者 Aidan N. Gomez / University of Toronto；β1=0.9、β2=0.98；8 张 P100；BLEU 28.4 对 26.36；LN 参考文献 [1] Ba, Kiros, Hinton 2016。均带逐字引文；非独立人工评测 |
| 多轮追问 | PASS | 浏览器内“其中 Adam 优化器…”在同一线程中正确回答，证据弹出并跳转第 7 页高亮 |
| 多篇问题 | PARTIAL | BERT 与 Transformer 编码器关系正确；GPT-3 上下文 2048 与参数表正确，GPT-1 上下文 512 未召回（关键词检索），GPT-2 论文不在资料包 |
| 错误前提（80 张 GPU） | PASS（单次运行） | 回答“训练使用 8 张 NVIDIA P100，80 张的前提缺乏证据”，引用第 7 页原文；此前两次因上游 503/额度未得到回答 |
| Gemini Decision 1 复核 | PASS（单次运行） | Adam 问题主张判定 supported，概率 0.986，1518 输入 token、0 输出；不可用时回退到生成模型复核（单测覆盖） |
| 浏览器巡检 1440×900 | PASS | 工作台、文献库、卡片抽屉、阅读器、问答、图谱、比较、写作、检索、设置均无控制台错误；截图 `docs/images/` |
| Docker Compose | BLOCKED | `docker compose config` 通过；镜像构建在沙箱因 Docker Hub 429 与代理拒绝 Debian 源而失败 |

## 2026-11-17 completion（持续更新）

继承Claude分支后基线516测试通过；综合集成607通过；配额/真实失败修复后611通过。后续最终回归见 `evidence/completion-20261116/final-after-live-fixes.log`，避免将阶段计数相加。真实浏览器32项、写作夹具23项、公网独立浏览器登录/文献读取分别有证据。6页PDF和360秒1080p普通话MP4已产生，视频不等同新输入验收。80题纯关键词已执行，Qwen核心对照保留；Nemotron/重排和Gemini完整对照不得写作已完成。真实问答、生成、Future Work与调用账本见completion目录，FAIL和待复核均保留。新增参考文献下载、全量云覆盖、公网生成切换以及人工准确性审核以最新运行记录为准，不能用这些单测数字代替。


## 2026-11-17 公网切换与真实补验

619项完整回归：evidence/completion-20261116/release-regression.log（135.88秒）；后续Schema及安全产物修复有专项日志。新评审账号46份资料、6231向量直接复制0调用；真实中文设备问题包含154个展开的向量源块候选，通过生成和Decision辅助核查。新中文PDF上传、英译和HTML导出通过，Agent根据真实检索区分设备/时长和未报告费用。

80题关键词、Qwen核心对照、未完成的全部模型对照见docs/EVALUATION.md。综述和Future Work的拒绝、partial及覆盖不足保留，人工质量审查NOT RUN。ECS原始541页重解析290.29秒完成，59项检查通过；文档任务运行期间CSV绘图5.437秒、五类导出成功，旧末页仍可读，见public-541-pressure.json。

夜间备份timer已启用且真实备份成功；backup.py区分写锁与总耗时，不改写旧记录。现有sluna.xyz主站保留，推理接口仍经认证回环隧道。公网生成/Embedding集中ECS计账，本地云调用关闭。

## 2026-11-17 本地全量完成与持久索引收尾

全39本地索引和80题真实向量/重排完成，分子分母见EVALUATION.md。最新全量回归643项/133.78秒（survey-and-index-final-regression.log），其后增加SQLite写锁等待专项；最终计数以worker-safe-final-regression.log为准，不相加阶段计数。前端类型和构建PASS，automatic-index-frontend-build.log。

新文件在ECS实际解析先完成、自动索引独立入队、完成后语义检索并回答6张GPU（new-pdf-auto-index-public.json）。本地额度预留失败仅等供应商真实日界，unknown不自动重发；解析、旧引用与排队索引分开。

一次全量导入因SQLite NUL文本长度误判回滚；修为Python完整字符串跨度逐段比较。其后发现线上同代旧状态failed/14466仍在，补齐状态前检验同manifest、全部23185向量及原文，原子切换成功。原失败和初次评审复制只有6231向量的记录保留。最终新空间29416条向量复制PASS、0调用。

压力下完整种子复制写锁56.522秒，API未OOM，但交互Worker空闲唤醒遇SQLite BUSY重启1次；现已增加仅队列忙错误的等待保护，不能重发任务中的未知请求。云35预检也因写锁失败，769次元数据HTTP尝试/0Embedding单位，旧回执保留，需确认reserved/unknown再恢复。

最终v12回归：645 passed in 135.80s，worker-safe-final-regression.log。公网RT_EMBED_PROVIDER=auto，主检索本地Nemotron，认证回环18990/18991，云只做独立代际备用。35云预检写锁留下的一条reserved已有同quota_id原生计数回执，核对后补记ok/0Embedding单位，无请求重发、无账本重置；cloud-preflight-receipt-recovered.json。

## 2026-11-17 技术文档会话补充

| 项目 | 状态 | 证据与范围 |
|---|---|---|
| 后端全量回归（Python 3.13.18，无 `.env`） | PASS | 645 passed、1 skipped（含新增标题回归用例）；修复 `cards.layout_title` 与 `charts.py` 字体回退之后执行 |
| 标题提取逐篇核对 | PASS | 资料包 37 篇原生 PDF 首页标题全部正确，含此前出错的 2205.14135v2（FlashAttention） |
| 前端构建 | PASS | `npm ci && npm run build`，发布 177 个文件；主包 1,072 kB 的体积告警仍在 |
| 本地无密钥浏览器巡检 | PASS | 20 篇导入就绪（651 页）；八个路由无页面异常；390 px 下仅首页有 1 px 横向溢出 |
| 带开发者 `.env` 运行测试 | FAIL | 6–7 项索引相关用例受 `.env` 影响失败；移除 `.env` 后全部通过，测试隔离待修 |
| 技术文档 PDF | PASS | `deliverables/ResearchTrace_技术文档.pdf`，27 页，XeLaTeX 可重复编译 |
| 演示视频（新版） | NOT RUN | 本会话未制作 |

本会话模型调用 0 次；公网站点从本云端环境不可达，未做公网复测。


## 2026-11-17 WSL US 开发环境迁移（本机配置）

用户明确分工：`wsl-us` 只作代码开发，公网仍由 ECS 服务，GPU node01 作为独立检索计算节点。源项目工作区未覆盖；迁移基线 `f3acf79` 包含当前远端 `fb9daee`，源目录的9个未提交文件已私下归档，没有把旧虚拟环境或 node_modules 搬入新环境。

目的地为 `/home/dev/projects/ResearchTrace`（WSL `Ubuntu_24.04_US`，SSH `wsl-us`）；Node22.16.0校验官方SHA256安装，Python3.12新建`.venv`，49个锁定wheel重新安装，前端`npm ci`。额外安装Tesseract、CJK字体和浏览器验收依赖。VS Code本地工作区设置指向`.venv`，大量私有数据不参加索引/搜索。

一致性备份已恢复到`data-migrated`，SQLite完整性ok、120个版本路径均存在、36,890向量保留；quota/quota_context/quota_request_units/provider_state的内容哈希与快照一致。原主空间45份文献以新的本地访问码绑定，凭据只保存在`.env`与`~/rt-private/local-access.txt`（0600），从`rt-info`查看。`data-migrated/`加入本地Git排除；检索token0600，未公开。新`.env`的Gemini key为空、`RT_PROVIDER_MODE=disabled`、付费兜底关闭，不把独立库当成ECS的实时额度账本。

使用新的专用SSH密钥`~/.ssh/id_ed25519_researchtrace`和别名`rt-gpu`，主机密钥沿用已验证指纹，禁用Agent/X11转发。`rt-gpu-start`仅按需建立Embedding18990、Reranker18991、下载代理18987三个回环隧道；`rt-gpu-stop`停止。`rt-start/rt-stop`用于临时完整联调，后台单元显式加入`us_ns`，避免普通用户systemd启动脚本跑出网络命名空间。本次验收后全部开发服务已停止、没有开机自动启动；生产ECS和GPU已有服务未修改。此环境优先使用这些命令，不调用旧`./scripts/dev.sh`安装普通用户后台单元。

GitHub/默认联网继续经us_ns固定代理；显式使用18987会改用GPU服务器代理出口，故没有设为全局HTTP_PROXY。项目启用现有`RT_PUBLIC_DNS_RESOLVER=https://dns.google/resolve`以适配Fake-IP，保留SSRF、真实公网IP固定连接和TLS校验；系统代理/DNS/防火墙不改。正常GPU检索使用既有离线模型；远程SSH shell里另行执行的联网程序仍走服务器自己的网络，不继承WSL固定出口。

测试入口`rt-test`使用python-dotenv自带`PYTHON_DOTENV_DISABLED=1`，仅在测试进程内忽略开发者.env，不移动/覆盖配置。无.env完整检查为640 passed/6 skipped（136.21秒），Ruff、TypeScript/Vite和OpenAPI导出通过；已有.env时对受影响索引任务7项回归通过。私有日志在`~/rt-private/migration-logs/`。

真实本地模型验证：Embedding4096维、L2归一和指纹匹配，248.537秒；2文段Rerank相关项顺序正确、指纹匹配，239.476秒。包含首次冷启动，不能用healthz可达代替及时推理。未重建已有向量、未调用云生成，云账本哈希未变。真实UI登录、45份文献、PDF.js翻页、36条参考文献、历史3条证据定位回PDF第5页、Vite均通过；pageerror0、意外HTTP错误0。浏览器私有证据在`~/rt-private/migration-browser/`，首轮验收脚本选择器失败记录保留。

ECS现状只读核对：生成仍发Gemini，检索/重排经现有ECS回环18990/18991到node01；Gemini及公网文献的ECS代理仍为18987。ECS鉴权manifest实际返回Nemotron/Qwen模型；不经过新WSL。这次没有修改ECS、生产GPU服务或推送GitHub。


## 2026-11-17 阅读器重做与界面统一

| 项目 | 状态 | 证据与范围 |
|---|---|---|
| 阅读器浏览器回归 `tests/browser/reader_selection.py` | PASS | 20/20，0 页面异常、0 控制台错误；真实 PDF.js + 四份核心原件，翻译/问答为明确标注的假 provider，真实模型调用 0。含：浮动划词卡片不遮挡选区、内联译文与持久缓存标注、滚轮连续翻到第 8 页、中英对照保留原 PDF、4 种旋转对齐、1280/1440/1920/390 宽度、541 页教材末页（仅 3 个 canvas）、扫描件提示、30 次快速切换文档。`evidence/reader-redesign-20261117/report.json` |
| 首轮该回归 | FAIL（已修复） | 旋转 90° 时页尺寸回调读到旧基准尺寸，触发 React 嵌套更新上限；改为按旋转标记尺寸并只用原始值作布局依赖后通过 |
| 后端全量 `rt-test` | PASS | 640 passed、6 skipped（130.34 秒），Ruff、TypeScript/Vite 构建、OpenAPI 导出通过 |
| 真实界面巡检（本地 API + 生产构建，无模型密钥） | PASS | 13 页论文滚轮从第 1 页连续滚到第 13 页（修改前 scrollTop 恒为 0）；历史答案「在原文中定位」打开第 5 页并高亮在视口内，旋转、放大后仍可见；参考文献 71 条、原文搜索、中英对照同步滚动、悬停框选原文、13 处图/表/公式裁剪均正常；390 px 手机布局修复（`.app-shell.compact` 原先在手机上把内容压进 64 px 列） |
| 真实译文显示 | NOT RUN | 本地无模型密钥，当前工作区没有已存译文；对照视图的译文排版只用浏览器内假数据检查过，未提交这些截图 |
| `apps/web/scripts/extended-reader-check.py` | NOT RUN | 针对已替换的旧对照设计，见 DECISIONS |

本轮模型调用 0 次；未触碰 ECS、GPU 隧道与账本。
