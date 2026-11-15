# ResearchTrace：Ubuntu 24 接手提示词

以下是用户最初开发要求与本轮补充要求的整合版，可直接交给下一个 agent。它包含交接事实，不代表项目已经全部验收通过。

---

你现在接手 ResearchTrace（研证）科研助手项目。项目已在旧机器开发出可运行版本，我正在把整个工作目录迁移到 Ubuntu 24。请直接检查、修复、运行并继续实施，直到完成任务书要求；不要只回复计划，不要让我重新选择框架或方案，也不要从零重写已经能用的功能。

## 一、先阅读与检查

先读当前项目根目录的 `AGENTS.md`、`CODEX_TASK.md`、`ACCEPTANCE.md`、`HANDOFF.md`，特别是 HANDOFF 最后的暂停交接段，再检查：

- `git status`、真实 Git 历史、所有未提交及未跟踪文件。
- 新机器 Ubuntu 版本、Python、Node、Docker、可用端口、磁盘、内存、GPU 驱动及运行中的其他服务。
- `.env` 是否已私下迁移、权限是否为 600，以及配置变量名是否齐全。不要打印任何密钥。
- `packages/contracts/API.md`、`packages/contracts/openapi.json`、`services/api/store.py` 和实际路由是否一致。
- 运行数据是否已迁移，SQLite 是否完整，文件路径及模型缓存路径是否仍指向旧机器。

当前旧机器路径是 `/home/CuiMinghao/projects/Competition/chuanzhiCup`。新机器路径以实际目录为准，不要硬编码旧绝对路径。不得覆盖其他项目、现有服务、代理配置或系统库。

存在合理小歧义自行选默认值并记录 `docs/DECISIONS.md`；除密钥、权限、费用和不可逆动作外，不要反复询问。

## 二、原始交付目标

目标：交付真实、完整、可运行的科研助手初版，以省赛实际第一名为竞争目标，但不能承诺名次。

必须覆盖六类真实功能：

1. 文档管理、结构化解析、扫描件与长文档处理、版本管理。
2. 证据约束问答与跨文比较。
3. 原文阅读、引用定位、中英翻译和段落联动。
4. 真实学术检索、追踪、推荐及反馈。
5. 真实引用图谱、综述、研究建议核查。
6. 源约束写作、可编辑结构图、CSV 统计绘图与导出。

先在新环境恢复并验证这条纵向路径：

**上传新 PDF → 真实解析和索引 → 阅读器 → 真实模型问答 → 点击引用定位到该版本原文。**

一旦能运行，立即启动并给我实际地址；随后继续补齐和打磨，不能停在“下一步可以做什么”。

重点打磨：

- **版本感知证据链**：结论关联不可变论文版本、物理页、可用印刷页标签、原文片段、页内坐标、解析来源。引入新版本或换解析器不能让旧引用漂移。
- **Future Work 后续核查**：旧建议及源位置 → 可检索命题 → 后续候选 → 时间、任务和条件核对 → 原文支持 → 已有直接相关证据／部分覆盖／当前范围证据不足／无法判断。不能把未搜到写成全球首次。

## 三、用户本轮新增要求：实际接入 PaddleOCR 和 MinerU

我明确要求使用这些成熟的开源库，后续已同意两者都引入。不要只安装包、写空适配器或加一个不可用按钮，要完成真实调用和产品内闭环：

- PaddleOCR 用于实际文字识别，特别是中文、英文和扫描页。
- MinerU 用于实际文档版面与结构化解析，验证表格、公式和阅读顺序。
- 两者结果都转换到统一 block/page schema，记录实际库版本、模型、设备、坐标和质量状态。
- 保留逐页持久化、取消和恢复。复杂解析可以作为独立 worker，基础 Web/API 不应因此变成必须依赖 GPU 的服务。
- 选用版本以 Ubuntu 24、Python、CUDA 的实际兼容性为准；核验对应版本官方文档和许可证。不要机械复制旧机器为兼容 Ubuntu 18 而选的版本。
- 更换解析器时必须设计明确的解析修订／快照机制，不得覆盖已经被引用的 block ID、文字和 bbox；不要通过清空旧数据来“重建成功”。

**GPU 使用授权的最终口径：**

当前机器 GPU 可以用于测试；有其他人的进程也可以使用，只要显存还有足够余量。按实时空闲显存选卡，至少保留 **2 GiB** 空闲显存；为本项目设置分配预算，持续监测，低于安全余量或超过本项目预算时终止本项目测试进程。不得终止、重启、迁移或修改其他人的进程，不得假定某张卡一直空闲。测试结束释放本项目资源，不默认常驻训练或占卡。轮询保护不能被描述为绝对不会 OOM 的保证。

首版不需要训练模型，也不依赖共享 GPU 持续可用。若确有必要做后续训练，应独立、限资源、可停止，并且不能耽误应用交付。

## 四、架构、部署和安全

沿用任务书的轻量架构：React + TypeScript + Vite、FastAPI + Pydantic、SQLite WAL、持久化单 worker、FTS5/BM25 + 真实 embedding + RRF、PDF.js、NetworkX、受控 Matplotlib PlotSpec、Mermaid。

按约 2 核 2GB 的 ECS 基础服务目标设计，开发机构建产物，长文逐页处理，阅读器懒加载。重解析可以放在本机／GPU worker，ECS 与本机可采用安全连接，但必须实测连通、鉴权、断线恢复和运行方式。不要假装已经部署，也不要把 SQLite 放在跨公网共享文件系统上。

服务必须保持 workspace 隔离、上传/文件鉴权、路径安全、SSRF 防护、Markdown/HTML/Mermaid 清洗。PDF、网页、论文、README、CSV 都是数据，不是系统指令。模型不能执行任意宿主 shell。绘图只执行受控模板，不执行模型任意代码。

Sites 云托管不需要使用，也不要因此创建云站点或更改域名。界面设计参考可以使用，但不能拿展示壳代替功能。

## 五、模型、密钥和调用预算

- Hydrogen 负责核心综合分析、跨文比较和研究建议核查；批量翻译、整理用已验证的 Flash Lite 等资源。
- 同一任务相关证据和子问题尽量合并，但严格遵守 **project 级** RPM、TPM、RPD、并发和有效期。失败、超时、重试都要计账。
- 不能把同一 project 的多个 API key 当成多份额度。两个既有 key 可用于本项目，但项目归属须有依据；目前保守共用一个计账组。
- 付费兜底默认关闭，不得创建账号绕过限制，不得自动启用不受保护的收费路由。
- 所有 key 只放服务器私有 `.env`，不打印、不提交、不打入浏览器包。用户已经要求把实际使用的 key 放在本项目，目前已完成；缺失时检查配置说明，不要在聊天中索要密钥。
- 可以用 Gemini 3.5 Flash Lite 发真实请求测试可用性；但不要无意义重复探测。

**尤其注意已有预算：** 这轮 Hydrogen 真实冒烟已用 **4 次**，包括一次截断失败，已达到原先上限。迁移不是重新获得 4 次预算，不得清空账本或擅自增加 Hydrogen 冒烟额度。后续真实质量评测需要另外明确预算。先完成不消耗模型的开发与测试；预算阻塞的 live 项标 BLOCKED。

当前 `.env` 的 `RT_SMOKE_MODE=true` 会阻止继续超出原上限的 Hydrogen 调用。不要为了让按钮看起来可用就偷偷关闭预算保护。

没有 key 时仍须能启动、导入、阅读、检索已完成本地索引、绘图和查看历史；模型调用清楚标配置缺失或 BLOCKED，不用 mock、缓存、预录答案冒充实时结果。

## 六、迁移前已经完成的真实工作

以下只是旧环境的已观察事实，必须在 Ubuntu 24 重新验证，不能直接复制为新环境 PASS：

- 已有可运行前后端和六类功能实现，两个真实 Git 提交：`c420213`、`375ac84`。
- **有大量重要未提交修改和未跟踪文件**，包括解析库接入代码、前端修复、验收证据。只 `git clone` 或只复制已跟踪文件会丢工作；不要使用 `git reset --hard`、`git clean`。
- 原生 PDF 实际使用 pdfplumber/pdfminer/PDFium，原扫描件路径使用 Tesseract。PaddleOCR/MinerU 还没有接通到产品主流程，不能说已替换。
- 改名 Transformer v7/v1 基于内容识别为同 Work，分别保留不可变版本；真实问答引用仍指向原版。
- 新 BERT PDF 的掩码比例问答通过一次真实 Hydrogen 请求，并对作者血型问题明确缺证据。
- 真实 embedding 返回 768 维向量，已实现实际密集检索与 RRF。覆盖率不同文档不同，必须查数据库，不能把部分密集索引写成全文完成。
- BitNet 8 页论文实际完成 120/120 个非空正文块的 Flash Lite 翻译，全文译文仍需进一步独立质量审查。
- Future Work 核查实际完成：Transformer 旧建议与 Longformer 全文对照，区分长文本相关进展和图像/音频/视频、减少顺序生成仍缺证据的部分。
- 20 篇真实 Crossref **元数据**、71 条登记引用边已测；不是 20 篇完整 PDF 的解析集合，不要混淆。
- 两个不同 CSV、异常编码/缺失值、实际统计和四类绘图已有测试；结构图可编辑并导出 SVG。
- 541 页自编工程材料实际在第 30 页强制中断后恢复完成，后半部和末页检索有证据，解析峰值 RSS 约 103 MiB。这是工程夹具，**不是官方教材**，也不证明完整服务在 2GB 实例上已验收。
- 完整测试日志曾为 43 passed；后续核心/安全回归为 22 passed，二者有重叠，不能相加宣称 65 项。
- 最新前端构建通过，采用 `dist-next` 构建后逐文件原子发布、最后替换 index，保留旧 hash 资源，避免在线构建导致白屏。
- 生产浏览器已检查引用高亮、正确版本/页码、旋转缩放、CSV 图、Mermaid 修改/导出及恶意链接拦截，证据在 `evidence/browser/acceptance.json`。

关键证据：

```text
evidence/provider_probe.json
evidence/embedding_probe.json
evidence/live_qa_result.json
evidence/live_unseen_qa_result.json
evidence/live_translation_result.json
evidence/live_idea_result.json
evidence/live_idea_failed_validation.json
evidence/retrieval_ablation.json
evidence/live_watch.json
evidence/live_graph.json
evidence/pytest.log
evidence/final-core-tests.log
evidence/browser/acceptance.json
docs/evidence/
evals/manifest.json
```

API 本地账本交接快照：Hydrogen 4 次；Flash Lite 22 次；embedding 56 次尝试，其中有失败及消耗未知项。以私下迁移的 SQLite `quota` 表和原始 usage 为事实源，不因重启或迁移清零。不得把本地估计说成供应商官方余额。

## 七、当前中断位置与已知问题

1. PaddleOCR 3.7.0 + CPU PaddlePaddle 3.2.2 曾安装在 `.tools/paddle-env`；官方移动检测/识别模型已下载，哈希见 `evidence/paddle_model_manifest.json`。导入报错：

   ```text
   libphi_core.so: symbol GOMP_parallel version VERSION
   not defined in file libiomp5.so with link time reference
   ```

   已用 `ldd` 核实旧机器错误加载 `/opt/intel/composer_xe_2015.0.090/.../libiomp5.so`，而非 wheel 内配套库。预加载系统 libgomp 失败。没有替换系统库。新 Ubuntu 24 应新建干净环境并检查动态库路径，不必继续沿用旧主机的补丁。

2. MinerU 2.7.6 pipeline 安装曾在 `.tools/mineru-env` 进行，用户要求换环境后已停止安装进程；不要假定安装完整、模型已下载或 GPU 已测试。旧环境通过 `.pth` 只读复用旧机器 `modern-multimodal` 的 Torch，**这个路径不能搬到新机器直接用**。

3. `services/parsing/server.py`、`services/parsing/runner.py`、`services/api/enhanced_parsing.py` 已写初版，尚未接入、未做真实解析验收。存在旧环境临时配置，必须代码审查。Broker 的 healthz 仅证明进程活着，不能代表模型已就绪。GPU 保护也未做实际推理验证。

4. 现有数据模型的 SHA256 去重与 block ID 规则需要扩展，才能安全支持同一原 PDF 的多个解析器修订。避免让换解析器覆盖旧证据。

5. 正式 `docs/TEST_REPORT.md` 尚未完成，HANDOFF 前半部分有过期阶段描述，末尾暂停段更接近交接时状态。需要按实际新测试统一整理。

6. 官方扫描原件、官方指定长教材、公网 HTTPS/评审登录、独立 50 题质量评测及基线对比、正式参赛视频和最终 PDF 均未完成，不得标 PASS。通用 Agent 工具编排、长任务边界、安全和全部 UI 状态也应对照任务书继续逐项检查，不因为有六个界面就默认完整。

## 八、Ubuntu 24 迁移与恢复要求

- 迁移完整工作目录，包含 `.git`、未提交/未跟踪源码、`evidence/`、`evals/manifest.json`、必要测试数据。
- `.env` 和 `data/` 必须私下迁移，不进入公开仓库；保留文件访问权限。SQLite 应一致性备份，或先停止本项目 API/worker 再完整复制，不能只复制主库而漏掉有效 WAL。
- `.venv`、`.tools/*-env`、`node_modules` 重新创建；模型文件可按哈希复用。不要把旧虚拟环境或旧 `.pth` 当成可移植运行产物。
- `GEMINI_PROXY`、`RT_PUBLIC_PROXY` 中旧机器 `127.0.0.1:17891` 仅是旧环境代理监听，不能假定新机器存在；检查并配置已授权可用的网络路径，不改其他人的代理路由。
- 旧机器端口为 18970；旧地址 `10.184.17.163:18970` 不是新机器地址，也未验证公网可达。新机器先查端口，再给出实际入口。
- systemd 单元和脚本可能保留旧绝对路径，需要按新目录重新生成，只操作本项目命名的服务。Docker 的数据卷 UID、代理、字体和内存配置也须实测。
- 当前本地启动入口为 `./scripts/dev.sh`；测试入口 `./scripts/test.sh`；实际参数和依赖以新环境检查结果为准。不要直接重复运行会额外花模型额度的 smoke 脚本。

## 九、继续实施与最终交付

恢复基础应用 → 完成 PaddleOCR/MinerU 真实接入及安全解析快照 → CPU/GPU 效果、耗时、显存实测 → 全部验收与界面打磨 → 文档、部署与赛事交付。

按 `ACCEPTANCE.md` 用改名论文、未见过 PDF、不同 CSV 和异常输入验收，每项只用 **PASS / FAIL / BLOCKED / NOT RUN**，附真实来源、哈希、环境、命令、模型、usage、日志或截图。未执行不能写成功，不能编造参考文献、实验、性能成绩或 Git 历史。

每完成一个可运行阶段，更新 `HANDOFF.md` 和测试报告，记录真实 Git 提交。保留已有工作，并行仅在工具确实可用且目录/文件所有权隔离时使用；不能伪造子 agent 报告。

最终交付必须说清：

1. 实际启动方法与可访问地址。
2. 三条新输入演示路径，至少包含原文定位和一次异常处理。
3. 构建、自动测试、浏览器验收和真实调用证据。
4. 已知缺陷、失败项、外部阻塞及未完成赛事材料。
5. 实际 API 请求数和 token 用量、付费保护、评审期运行安排。
6. 需要我做的最少人工步骤。

现在开始接手。先做必要检查并恢复可运行服务，持续推进，不停在计划或空页面。
