# Rubric mapping

This is a feature-to-evidence map, not a claimed contest score. Weights originate in `CODEX_TASK.md`; acceptance states and actual measurements belong in `docs/TEST_REPORT.md`.

| Scoring direction | Implemented mechanism | Code | Evidence and limits |
|---|---|---|---|
| AI技术深度（35%） | 结构解析、检索代际、混合召回与重排、有界工具、独立证据复核 | services/api/retrieval.py、index_generations.py、jobs.py、services/retrieval_runtime | 本地模型仅在真实推理、覆盖与评测通过后视为已部署；单元测试数不是回答准确率。 |
| 产品功能和工程质量（30%） | 六类功能、不可变版本/解析快照、批次放行、恢复、预算、权限与安全 | services/api、services/worker、apps/web | 测试结果与发布阻塞见TEST_REPORT；公网与评审资源另行验收。 |
| 创新性（15%） | 版本感知主张、结论与原文绑定、FutureWork时间和条件核查 | snapshots.py、evidence_validation.py、jobs.py | 开源组件如实归属；主张支持、全文发现和新颖性判断不能从相关性推导。 |
| 用户体验（10%） | 内容优先阅读、证据状态、批量进度、双向翻译、可展开执行步骤 | apps/web/src | 浏览器实拍和状态矩阵才能证明交互通过。 |
| 实用性（10%） | 新输入→真实检索/回答→原文定位→比较/笔记/可复现导出 | app.py、research.py、charts.py | 三条完整新输入演示、公网入口及正式材料仍按发布门槛逐项记录。 |

权重来源：用户原资料包《科研小助手Agent-AI大模型.pdf》第6–7页。此表是功能与证据映射，不是官方得分或名次预测。模型/网络/费用配置和新测状态见最新HANDOFF，不复用旧主机结果冒充新测试。

## Six required functions

| Function | Backend/UI path | Reproducible verification |
|---|---|---|
| Document management and parsing | `/documents`, `documents.py`; library/reader | Renamed real v7/v1, unseen BERT, derived scan, explicit corrupt/encrypted PDFs; source manifest. |
| Trusted question answering | `/qa/runs`, `jobs.qa`, `validate_answer` | Actual live run/usage and original quote; fixture tests reject nonexistent IDs/mismatched quotes; independent semantic review is separate. |
| Reading and translation | PDF.js page view, `/translations`, block translation cache/export | Actual complete-paper translation and bidirectional block positioning require their own test evidence; API presence is insufficient. |
| Search, watch and recommendations | arXiv + Crossref, `/watch-queries`, feedback | Fresh uncached two-source evidence, watch deduplication test, feedback changes cached-candidate ranking. Scheduled worker trigger is separately tested. |
| Citation graph, review and research advice | `/graphs`, `/ideas/audits`, source-constrained notes | 20 verified metadata works and 71 real deposited-reference edges; source DOI records preserved. Idea coverage requires later fulltext conditions and dates. |
| Writing and plotting | `/agent/runs`, note export, strict Mermaid UI, `/charts` | Source-bound claims; real line/bar/radar/3D renders; two different CSV PNGs and standalone script reproduction. No fabricated results/error bars/significance. |

The attributable engineering contribution is the integration of version identity, evidence anchors, auditable task execution and bounded resource use. BM25, embeddings, RRF, PageRank, PDF.js and model APIs retain their third-party attribution; they are not claimed as newly invented algorithms.
