# Decisions

2026-11-15: Follow requested React/TypeScript/Vite + FastAPI + SQLite/WAL + single durable worker. No GPU or training. No Sites hosting. Runtime isolated in `.venv`, port 18970 (checked unused); no existing services changed.

Backend owns schema and OpenAPI. Separate modules/directories for delegated implementation. Normalized crop-relative rotated bbox, zero-based physical pages; printed labels separately. Metadata and version identity are content derived. Uncertain labels stay uncertain. API secrets remain ignored `.env` mode 600. Reuse two previously configured Gemini credentials as explicitly authorized in this session; independence from prior user confirmation, not inferred from key count. Conservative shared quota group until independent project mapping can be verified.

Authentication uses access codes and HttpOnly opaque workspace session cookies; isolated workspaces by session. Local startup uses a locally stored access code, never provider credentials.

UI: pale blue-gray #F4F7FB canvas, white paper, midnight navy #172B4D text, teal #087F8C evidence markers, blue #315EBD action, amber #9A6700 uncertainty. Three-pane document workbench, quiet navigation, live evidence inspector; no fabricated dashboard statistics. System Chinese sans with serif document headings. The design search matched institutional colors but suggested a portfolio layout; that layout was rejected as unrelated to document work.

2026-11-15 Ubuntu24: use Node22.16.0 privately under `.tools`, rebuild Python3.12 environments and fresh npm dependencies through the source server relay. Local port18980 due host-side18970 bind conflict. Local proxy replaces only migrated project loopback settings. SQLite migrations add parser revisions separately from immutable document bytes; legacy IDs retained. Current retrieval/graph/translation export use active revisions; old evidence reads explicit parse_id. Complete revision publication is atomic, failed/partial revisions stay separate. Reparse has no automatic embedding spend, so new revision dense coverage is explicitly zero. Optional parser process is outside the lite memory budget, with a separate5G cgroup cap on this7.6GiB development machine. Paddle CPU runtime3.2.2 and OCR3.7.0 passed real bilingual inference; MinerU2.7.6 is chosen deliberately for a verified local pipeline API, not because Ubuntu24 requires the old version. See parsing README for official tagged API/license references. Large downloads occur on the source server; tiny Debian browser/OCR runtime libraries are privately extracted, without sudo or changes to system libraries.

2026-11-16 Parser Upgrade (`MinerU 4.2.2` + `PaddleOCR-VL-1.6`): User explicitly requested upgrading MinerU to latest `4.2.2` (`mineru[torch]==4.2.2`, `torch 2.15.0+cu132`) and adding `PaddleOCR-VL-1.6` (`PP-DocLayoutV3` + `PaddleOCR-VL-1.6-0.9B`), provisioning offline weights (`MinerU-4_models_torch` + `MinerU2.5-Pro-2605-1.2B-GGUF` from ModelScope, `PP-DocLayoutV3` + `PaddleOCR-VL-1.6`) with SHA256 manifests. To stay well under the 5 GiB service memory cap on the 7.6 GiB host (avoiding PaddlePaddle dynamic graph float32 OOM >7.2 GiB on `PaddleOCR-VL-1.6-0.9B`), `paddleocr_vl` runs as two isolated stages: Stage 1 `PP-DocLayoutV3` in `.tools/paddle-env` (~1 GiB RSS, exits cleanly), then Stage 2 `PaddleOCR-VL-1.6-0.9B` via Transformers PyTorch `bfloat16` (`trust_remote_code=False`, `use_cache=True`, ~2.4 GiB peak RSS) inside `.tools/mineru-env`. MinerU 4.2.2 invokes `doc_analyze(..., effort='medium', image_analysis=False)` + `render_content_list` under `MINERU_MODEL_SOURCE=local` with remote VLM URL env rejected.

2026-11-16 continuation after `ba83619`: retain user's MinerU4.2.2 and PaddleOCR-VL-1.6 upgrades. Protect page writes/publication by checking run cancellation and document deletion within the SQLite writer transaction. Every committed parser page is immutable, including empty/low-quality output; restoring a partial task skips those pages rather than overwriting anchors. Repairing output quality or switching parser/model/device requires a new revision. Translation jobs pin a revision when queued; historical exports accept parse_id and progress counts exclude other revisions. A per-run OS lock prevents resuming a cancelled worker before its old resource cleanup has ended; the API returns409 instead of resetting it to queued early. New scholar imports may explicitly select metadata-only and disable dense spending. Optional parser licenses are audited against installed metadata and the bundled4.2.2 license (not the old2.7.6 license).

2026-11-16 用户资料包与管理员流程：保留 `科研小助手.rar` 原包（SHA256 `a87f17843197b011b1694293a65b63514cef8a1dc72c4b465f6bbd3fc5cfc819`），解压前检查路径、链接、加密与大小，隔离存放于被忽略的 `evals/files/user-dataset-a87f17843197/`。40 个 PDF 分为39份测试输入和1份7页题目说明，清单单独存证；不执行资料内容。小型解压工具私下提取到 `.tools/archive-tools`，未改系统库。管理员先发布十步可点击流程，再开始资料功能测试；保存 `browser-before.json` 与 UTC 时间作为顺序证据。结果源为持久化 JSON 和实际任务记录，空记录为 NOT RUN，5秒轮询不触发执行。原包发布渠道未独立认证；文件和题目说明是测试依据，不冒称组委会签名包。包内说明的评分权重与先前网页记录不同，保留两者来源，功能测试仍执行项目更完整的 ACCEPTANCE.md，不默改赛事权重或截止时间。

2026-11-16 原教材空白页修复：首次541页实测发现4张只有印刷裁切线的空白页误记 empty_or_failed。原生解析器升级 `pdfplumber-layout-v2`：要求无文字/图像/其他对象，所有线条位于页边，再以低分辨率渲染确认正文区域全白，才记录 blank 并跳过OCR；扫描页、正文矢量图、淡字或渲染失败不能因此通过。旧v1部分失败快照不改写；完整新快照541页/5315块通过并原子发布。界面解释空白状态。历史FAIL仍显示，只有相同文件哈希的新PASS可通过 resolved_by解除流程总状态中的旧失败；142项回归包含这项约束。

2026-11-16 最终重构计划：保留项目名“研证 ResearchTrace”，只调整定位语为“每个结论都能回到原文的科研智能体”（改名需改仓库、服务单元、证据与文档，不增加评分项）。保留 React/TypeScript/Vite、FastAPI、SQLite 与现有任务系统；前端在原 Vite 工程内按路由逐页重建，新增路由、服务端状态层、组件体系与由 OpenAPI 生成的类型；后端新增统一模型提供方接口（Gemini 原生、OpenAI 兼容云端、本地 OpenAI 兼容服务）与显式多角色状态机，不引入新数据库、队列或编排框架。计划文档用英文撰写以便与用户本次沟通一致，界面文案仍为中文。执行顺序、取舍清单与验收口径见 `docs/REFACTOR_PLAN.md`。

2026-11-16 重构第一阶段：（1）前端未引入 Tailwind/Radix/TanStack Query，改为手写的设计令牌 CSS 与 React Router，以减少依赖与构建风险，效果同计划；（2）对话线程不新建表，复用 runs.payload.thread_id，历史只由服务器读取；（3）模型给出的自由正文与已核验主张不一致时，用主张文本替换（不发布未核验正文），不再整体拒绝；对应单测改为断言未核验句子不出现在发布结果中；（4）复核模型不可用时答案保留为“待复核”；（5）MiniMax M Plan 不接入产品路由；（6）沙箱内无法安全获取 arXiv 记录时不放宽 DNS 固定，文献卡片用 arXiv 编号推出首次提交年月。

2026-11-16 Gemini Decision 1：恢复计划中的设定，作为默认主张复核器（`RT_EVIDENCE_REVIEW_PROVIDER=decision1`），独立额度、不占用回答模型；概率低于 0.9、置信度低于 0.8 或差值小于 0.25 时保留待复核；不可用时默认回退到生成模型复核（`RT_DECISION_REVIEW_FALLBACK`）。任务路由仍只在规划模式使用，简单问答不多花一次调用。

2026-11-17 completion: continue Claude `6b02876` on `upgrade/complete-20261116`, preserving all earlier Git history and uncommitted work. Integrate separate document, reader, writing and deployment worktrees. User says team signature is not needed yet. Existing ECS nginx and main sluna.xyz remain; ResearchTrace has its own researchtrace.sluna.xyz vhost, loopback services, restricted SSH tunnels and real Let's Encrypt certificate. User added the DNS A record after the existing Workbench identity received AliDNS403. Public fresh-browser reviewer login passed.

2026-11-17 quota correction: a Gemini embedding batch consumes an upstream request unit per text, not one unit for the whole HTTP call. Retain original quota rows and add quota_request_units; legacy units without receipts use a declared conservative upper bound. The original four smoke attempts remain accounted for. The user's resource plan explicitly provides two independent projects. Live probes showed first credential Flash daily20 exhausted and second credential Flash successful. Logical labels are gemini-project-1/2; Google numeric project IDs have not been retrieved. Preserve all old gemini-shared rows through a conservative alias to project1 (including one second-key probe, intentionally overcounted). Keep authorised combined Hydrogen/Flash daily40 and embedding per-project1000 / combined2000, no paid fallback. Keys never enter public evidence. Project2 is preferred after the probe; choosing a credential never creates a new allowance.

2026-11-17 cloud retrieval: the fixed local core5330/full23185 chunks remain the source for controlled local comparisons. A real token preflight found three long cloud inputs above2048 tokens; failed/staged generations and charges are retained and never activated. An additional production-only chunker bundles complete original spans into <=2048 UTF8-byte inputs, including overlaps for oversized blocks, producing901 core4 chunks over5267 original blocks. This changes chunking and must NOT be described as a controlled same-input Gemini-vs-Nemotron comparison. Source blocks, pages and historical citations are unchanged. Incomplete vector generations never become active.

2026-11-17 reliability: schema-repair calls are bounded to one, original malformed graph/recommendation receipts are retained. Unknown sends cannot be replayed. Future Work scopes evidence to real discovered/downloaded candidates instead of filling its eight-paper budget with unrelated library entries. Null publication identities remain unknown dates. Auxiliary historical source versions cannot be classified as later work. Host backups recognise the fixed /app/data container mount and preserve quota on restore. PDF generation and narrated 1080p video are actual artifacts; the video shows actual UI/historical run timestamps and does not certify remaining release gates.


## 2026-11-17 独立覆盖审查与免生成复核

真实Future Work案例表明：方法事实获支持，仍不能证明其覆盖原计划的条件。事实校验之后新增Decision条件审查，使用相同0.9概率/0.8置信度/0.25差值门槛，只能维持或降低原类别；输入仍绑定旧建议、问题、候选全文和时间精度。失联或回执未知则保留证据不足，不重发。

新增已结束核查的revalidate接口，只复用原空间、原问题和已收到的分析回执；保留原账本与产物，新任务明确标记历史分析复用。原任务有unknown/reserved调用则拒绝绕过。条件审查输入改变时旧回执不可复用，旧产物不会被新结论覆盖。

本轮还查到Gemini Embedding原生计数与隐式截断的官方说明：countTokens不消耗Embedding配额，输入还需为模型内部token留余量。当前901片段生产索引采用保守字节上界；拟补完整文本token预检和更紧凑的原文片段合并，尚未执行的部分不标PASS。来源：https://discuss.ai.google.dev/t/gemini-embedding-001-counttokens-support-token-correspondence-and-truncation-behaviour/190649 。

## 2026-11-17 本地优先、索引持久化与写锁

主检索维持用户要求的本地Nemotron。Gemini独立云代作为共享GPU离线备用，完整35云代不阻挡本地全39验收。ECS使用auto且本地和云的快照/模型指纹各自验证，所选范围不完整则不发该模型查询。

解析可先完成阅读，自动索引单独持久入队，6/30工作区/全局并发限制不变。只有本地未发送的日额度预留失败可记录供应商实际reset_at后等待，不重置历史额度、不重发未知请求。索引token预检在单个候选边界让位于新解析；收到的计数持久保存。

源PDF含NUL时SQLite length(TEXT)可能提前终止，因此span验证用完整Python字符串，索引覆盖计数采用与chunker一致的Unicode strip策略；不清洗或重写不可变原文。全量向量复制流式64条批次，避免一次持有数百MiB BLOB。种子大事务仍可能超过30秒锁等待，空闲队列仅对SQLITE_BUSY/LOCKED退让，不吞掉其它数据库错误，不重试任务中的已发送模型调用。

2026-11-17 技术文档改用 LaTeX：按用户要求以 XeLaTeX + ctex 重写赛题 2.3 文档，源码放 `docs/tech-report/`，图表用 TikZ/pgfplots 内嵌以便后续修改；数据图由脚本读取 evidence 生成。文档只陈述有证据的结果，局限以展望形式表述，不写未测得的准确率。

## 2026-11-17 阅读器重做与界面统一

- 用户反馈：读论文不能向下滚动、只能点翻页按钮；「中英对照」丢失版式；缺少好用的划词翻译；整体不协调；SHA、快照、语义索引计数等技术词干扰阅读。技术细节留在文档里，界面只保留用户需要的信息。
- 原文改为连续滚动：所有页按真实尺寸占位，只渲染视口附近的页（541 页教材实测同时只有 3 个 canvas），页码随滚动更新；目录、搜索、引用、证据跳转都滚到对应位置；缩放、旋转、面板开合时保持阅读位置。
- 「中英对照」保留原版：左侧就是原 PDF（版式、公式、表格不变），右侧按原文块顺序逐段对齐译文；图、表、公式直接裁剪原页面显示，不重排、不重新排版；未翻译的段落以浅色原文占位并明确标「原文」。两侧按「页 + 页内位置」双向同步滚动，悬停译文段落会在 PDF 上框出原文区域，点击可互相定位。
- 划词翻译改为跟随选区的浮动卡片（翻译 / 解释 / 提问 / 复制 / 切换目标语言），译文直接显示在卡片里；重复选段命中持久缓存时标注「来自翻译缓存」，不冒充新请求。「划词后自动翻译」默认关闭，避免滚动阅读时消耗额度；开启状态只保存在本浏览器。
- 浮动卡片会覆盖其下方的正文行（但不遮挡选中文字），这是有意的改变；原测试中“工具条不覆盖 PDF”的断言改为“卡片不遮挡所选文字且在阅读区内”。
- 界面统一：冷灰中性色板、浅色侧栏，替换原深色侧栏与暖米色底的搭配；阅读页与对话页占满一屏、只滚动内容区；顶栏在阅读时显示论文标题与版本；去掉「数据持久化」与模型名徽标；「未配置模型」提示可关闭；文献库只显示「可阅读 · N 页」，仅在解析中显示进度；导入批次记录可收起。
- 参考文献重要性与批量下载移入阅读器「参考文献」标签内，不再作为与阅读器并排的一列。
- `apps/web/scripts/extended-reader-check.py` 针对旧版“原文文字列 + 译文列”的对照设计，依赖已移除的 `.parallel-column:not(.translated)`；新设计由 `tests/browser/reader_selection.py` 覆盖，该旧脚本视为历史验证，不再维护。

## 2026-11-18
- 引文图谱短标题：标题规范化后 ≥24 字符可单独匹配；12–23 字符（如 "Attention Is All You Need"）须同一条参考文献同时含该论文第一作者姓氏与年份，且全库唯一命中，否则不连边。宁缺毋滥，边仍只来自真实参考文献。
- 用户更正的标题同时更新 work 标题（图谱节点、检索显示），因为它更正的是论文本身而不是某个文件。
- 中英对照分栏比例限制在 25%–75%，按浏览器记住；拖动时 PDF 暂停重排，松手后再按新宽度渲染，避免每帧重绘全部页面。
- 解析文本中的 `$…$`/`$$…$$` 用 KaTeX（trust=false）渲染；行内公式须含 LaTeX 特征（`\ _ ^ { }` 或单个字母），避免把 "$5 and $10" 当公式；无效 TeX 回退显示原文。
- 演示账号只保留 10 篇精选论文：其余文档软删除（可恢复），不动评审账号与原始语料。
- 版本修订总结使用 deep 角色（Hydrogen 优先）；服务方 503 时照实显示失败与重试按钮，不用缓存或其他论文的结果冒充。
- 最终回答提示词：检索观察只保留块 ID（正文已在 evidence 中），其他工具结果截断到 4000 字符，证据按排名保留约 9 万字符，不截断单个块。
  没有给 Hydrogen 设思考预算：该参数未经验证，误用会导致所有请求返回 400。
- 评审期改为 API 模式：检索用 Gemini 向量加 BM25，GPU 全部停止以释放共享显存；不重算 GPU 索引，也不把关键词结果说成语义召回。
- 前端改用「石墨导航 + 白纸 + 荧光标记」视觉：荧光色只用于证据高亮、引用和当前状态，图标全部用代码绘制（`apps/web/src/icons.tsx`），不再依赖 lucide。
- 界面只放关键词、图标和数字，说明性长句和防御性文字全部移除。证据约束仍由后端执行：缺证据、待复核、已降级、缓存结果、生成时间这些状态继续显示。
- 提交压缩包由 Git HEAD 生成，只放作品文档、源码和精简测试记录；第三方论文 PDF、内部任务书、交接记录和部署到具体主机的脚本不进包，文档里的主机信息替换为占位符。
