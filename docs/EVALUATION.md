# Evaluation scope

当前核心测试为用户资料包原始v1、v7、15页扫描版和541页教材，其余35份为拓展。39份1986页实际处理及122项定位已有记录。更早的自写夹具单独保留。

没有测得可推广的总体问答准确率。机器支持判断、原文定位、执行成功和独立人工审查分别记录。原4次Hydrogen smoke已用完，不得重跑或重置；新测试按显式授权日预算执行，失败和unknown计账。

## 2026-11-17 公网与检索补验

| 项目 | 状态 | 范围与证据 |
|---|---|---|
| 核心4本地索引 | PASS | Nemotron 5330/5330，5267合格块；不代表全39 |
| 核心4云索引与ECS同步 | PASS | 901/901，覆盖5267原始块；core-cloud-public-import.log |
| 独立评审种子 | PASS | 6231向量复制、0供应商调用；public-seed-copy.json |
| 公网新账号语义问答 | PASS | 云向量+生成+Decision辅助核查，8张P100；public-semantic-qa.json |
| 关键词80题执行 | PASS | retrieval-keyword-all.json；该状态表示实际执行，不表示80题答对 |
| Nemotron核心50题执行 | PASS | 固定相同原文片段，45道有答案题的dense及hybrid全部金标@20命中45/45；5道无答案不计检索分母。相关改写题、独立人工金标审核NOT RUN；retrieval-nemotron-core.json |
| Qwen核心50题执行 | PASS | 45道有答案题，全部金标命中：dense43/45、hybrid42/45、sparse37/45。含相关改写题，金标独立人工复核NOT RUN，不外推总体准确率 |
| 全部模型完整80题对照 | BLOCKED | 共享GPU及当日Embedding余量受限；缺失部分不补造分数 |
| 综述及Future Work质量门槛 | BLOCKED | 原始失败、主张拒绝、待复核和覆盖不足均保留 |
| 新中文PDF整篇英译 | PASS | ECS实际上传→解析→翻译→导出，自写输入；public-generation-live.json |
| ECS原始541页重解析及并发CSV | PASS | 541页290.29秒、59项检查；并发绘图5.437秒及五类导出、旧末页仍可读；public-541-pressure.json |

901片段生产索引改变了切分，不能混入固定切分模型A/B。当前汇总见docs/COMPLETION_20261117.md及evidence/completion-20261116/summary.json。

## 原始工程基线（历史，当前状态以上方为准）

# Evaluation scope

No general accuracy percentage has been measured. Targets90% factual/95% support/90% insufficiency are acceptance goals, not results.

Data provenance and SHA256 are in `evals/manifest.json`, downloaded/prepared by `scripts/prepare_evals.py`. Renamed real Transformer v7/v1 and BERT PDFs test content-based identity and unseen inputs. Scan and541page long document are clearly derived/self-authored engineering fixtures; official scan/textbook remain BLOCKED. Twenty related papers are real verified metadata records, not twenty processed full texts.

Deterministic checks cover exact version scoping, raw source quote membership, IDs/bbox, sparse indexes, CSV maxima/deltas and source-bound graph edges. Mock network tests are explicit fixtures and do not establish live model availability. Live provider probes and complete saved runs are separate evidence.

`scripts/smoke.sh --live --max-hydrogen-calls 4` is a bounded end-to-end integration test, not an accuracy benchmark. Source fact audits must inspect whether the quoted material actually supports the claim. Located quotes are labelled semantic review pending. No model-generated labels count as independent ground truth.

A50-question reviewed dataset, direct-model/basic-retrieval/current-system baseline comparison, and statistical confidence intervals are NOT RUN. They require independent annotation and an explicit additional model budget. `scripts/evaluate.sh` states this and spends no tokens. No automatic fallback evaluation consumes the remaining Hydrogen quota.

## 2026-11-17 全39本地索引与80题真实复测

固定23,185片段，核心45道有答案题49个金标块、拓展30题30个金标块；5道无答案不计Recall。两组共75道有答案题，题目含相关改写，独立人工金标复核NOT RUN。

| 阶段 | 核心全部金标@20 | 拓展全部金标@20 | 核心首个金标前5 | 拓展首个金标前5 |
|---|---:|---:|---:|---:|
| 关键词 | 37/45 | 16/30 | 22/45 | 10/30 |
| Nemotron向量 | 45/45 | 28/30 | 43/45 | 22/30 |
| BM25+向量RRF | 45/45 | 26/30 | 35/45 | 13/30 |
| 再加Nemotron重排 | 45/45 | 30/30 | 44/45 | 24/30 |

证据：retrieval-nemotron-all.json、retrieval-nemotron-all-rerank.json，保存原文跨度、模型锁定信息、实际GPU运行和缓存来源。该表比较检索排序，不能表述为生成答案准确率。Qwen只有核心同条件对照，Gemini生产切分不同，完整同条件对照仍BLOCKED。

本地全39代23185/23185向量、22950/22950合格原文块、2189排除块；ECS同代旧状态补齐及原子激活见local-full-final-activation.json。新评审空间复制29416条现有向量和43个版本/模型活动映射、0模型调用，见public-full-ready-seed-copy.json。

新自写Aster PDF真实上传→解析→独立索引→云向量问答与Decision辅助核查PASS，答案6张GPU，见new-pdf-auto-index-public.json。该测试不是赛题原件，不冒充独立人工审阅。
