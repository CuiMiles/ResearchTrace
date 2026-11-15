# Ubuntu24 验收报告

当前状态：基础服务、原生解析、不可变解析快照、PaddleOCR CPU 与 MinerU CPU 公式/表格/结构化解析、以及离线/浏览器非模型交互验收已实测通过；MinerU GPU（受 WSL2 NVML 限制）与需新模型配额项标为 BLOCKED，新环境结果与旧主机历史证据分开记录。

本机入口 http://127.0.0.1:18980；环境 Ubuntu24.04.5 WSL2、Python3.12.3、Node22.16.0、RTX4060Ti8188MiB。源码和四个SQLite库已迁移，密钥与运行数据私有保存。已知环境与产品边界见 `docs/KNOWN_LIMITATIONS.md`。

## 本轮实测

- 自动回归 `./scripts/test.sh` 当前 **97 passed**（`evidence/ubuntu24/regression.log`）；单独重复运行的子集不累计相加。
- 前端 `tsc --noEmit` / `vite build` 通过（发布 168 个构建文件），后端 `ruff` 与 `packages/contracts/openapi.json` 导出通过。
- 无密钥隔离 API/worker 真实启动、上传、解析、阅读、搜索和 CSV 绘图通过。
- PaddleOCR 3.7.0 / PaddlePaddle 3.2.2 真实双语 CPU 识别：PNG 7.82 秒、峰值 RSS 968368 KiB；产品单页快照 8.69 秒，中文文字层、FTS 与 PDF 坐标高亮通过。
- MinerU 2.7.6 真实 CPU 结构/公式/表格解析通过并保留旧快照与账本不变：`equation.pdf`（8 blocks，69.81s，`evidence/ubuntu24/mineru-cpu-equation.json`）、`table.pdf`（13 blocks，含完整 HTML BLEU Table 2，94.89s，`evidence/ubuntu24/mineru-cpu-table.json`）、`formula-page4.pdf`（12 blocks，含 LaTeX Attention 公式，103.38s，`evidence/ubuntu24/mineru-cpu-formula.json`）；浏览器公式/表格黄色 PDF 坐标高亮通过（`evidence/ubuntu24/mineru-graph-browser.json`）。
- MinerU GPU 模式在 WSL2 按 fail-closed 显存保护实测阻塞：`/usr/lib/wsl/lib/nvidia-smi` 可见 8188 MiB RTX 4060 Ti，但 WSL2 NVML `--query-compute-apps` 进程显存恒为 `[N/A]`，监控终止本项目会话并返回 HTTP 503 `GPU accounting unavailable; stopping this job conservatively (WSL/NVML)`（`evidence/ubuntu24/mineru-gpu-monitor.json`）。
- 浏览器补充矩阵在 `http://127.0.0.1:18980` 全部通过（0 报错、0 越权写操作）：D02 正文与文献往返、D03 双向段落同步、D05 全状态矩阵（loading/partial/500/401/empty/429/parse-failed，`apps/web/validation/reader-extra-20261115T143101401610Z.json`），以及 E06 20+ 篇真实图谱交互与重算（29 节点/72 边，1440/1280 无溢出，`evidence/ubuntu24/mineru-graph-browser.json`）及 E08 确定性 `md`/`html`/`bib` 导出。
- 原生 Transformer v7/v1、BERT、派生扫描件通过；541页自编夹具在30页强制中断后恢复，末页可检索，恢复进程RSS109364KiB。官方扫描原件/指定教材仍不可用。
- 三个真实评审workspace并发上传，在512M API/896M worker限额下完成；API+worker分别峰值相加153112576字节。独立重型解析worker不计入lite结果。
- 本轮新增供应商调用0；Hydrogen4、FlashLite22、embedding56尝试账本保留；Hydrogen冒烟已耗尽，不自动重置或收费兜底。
- 验收统计（A01–F15 共 64 项，机器可读详见 `evidence/ubuntu24/acceptance.json`）：**46 PASS**、**18 BLOCKED**、**0 FAIL**。

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
| B02 | 公式与表格 | PASS | MinerU 2.7.6 CPU layout/formula/table extraction & browser highlight PASS (mineru-cpu-equation.json, mineru-cpu-table.json, mineru-cpu-formula.json, mineru-graph-browser.json); MinerU GPU explicitly BLOCKED on WSL2 NVML [N/A] (mineru-gpu-monitor.json). |
| B03 | 扫描件新输入 | BLOCKED | Derived bilingual scan passed PaddleOCR product/browser tests; official scan original is unavailable, so the complete official-input case remains blocked. |
| B04 | 同一文件重复上传 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| B05 | 改名后的版本识别 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| B06 | 相似但不同论文 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| B07 | 版本差异可追溯 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| B08 | 旧引用不漂移 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| B09 | 长文完整处理 | BLOCKED | 541-page engineering fixture completed, but the official specified textbook is unavailable. Dense coverage is explicitly separate. |
| B10 | 后半部随机查询 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| B11 | 中断与恢复 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
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
| D05 | 可见 UI 状态 | PASS | All 9 Chromium UI state checks PASS (loading, partial, 500, 401, empty, 429, parse-failed; reader-extra-20261115T143101401610Z.json). |
| D06 | 浏览器视觉检查 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| D07 | 真实 streaming | BLOCKED | Actual persistent SSE tool events/reconnect are implemented and tested; new live provider streaming not executed. |
| E01 | 标题/ID 检索入库 | BLOCKED | Historical arXiv/Crossref requests preserved. Fresh uncached dual-source online import has not been revalidated on Ubuntu24. |
| E02 | 限流与网络失败 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| E03 | 追踪查询 | BLOCKED | Controlled fixture watch/dedup tests passed and old live logs retained; a new scheduled online check has not been performed. |
| E04 | 推荐反馈 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| E05 | 真实引用边 | PASS | Executed local checks listed in evidence_paths; unit fixtures are not live provider proof. |
| E06 | 20 篇级图谱 | PASS | 29-node / 72-edge real graph rendered & recomputed cleanly in Chromium browser with inspector & 1440/1280 no-overflow check (mineru-graph-browser.json). |
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
