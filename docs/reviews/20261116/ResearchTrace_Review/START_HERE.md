# 从这里开始

本包是对用户提交的 `ResearchTrace_完整审阅包_20261116_115055_cc54691.zip` 的审阅报告与升级任务，**不是已经修改好的项目源码**。没有修改原项目、访问其公网运行环境或在用户3090上部署模型。

## 阅读顺序

1. `AUDIT_REPORT.md`：完整评价、证据、模型选择、升级方案与优先级。
2. `CODEX_UPGRADE_TASK.md`：直接交给当前项目的Codex执行，要求增量修改。
3. `RELEASE_GATES.md`：逐项发布检查。
4. `SOURCE_EVIDENCE.md`：从原包摘取的代码路径和行号，用来复核具体判断。

## 本次新产生的证据

- `pytest_recheck_clean.log`：隔离环境142项后端测试通过；依赖差异见 `audit_environment.json`。
- `pytest_recheck.log`：首次审阅环境误设关闭dense造成一个夹具失败；修正环境后全量重跑通过，不计项目缺陷。
- `database_snapshot_stats.json`：原包主库只读统计；官方语料工作区活动块25145、向量0。
- `deterministic_probes.json`：引用校验反例、项目路由反例、中文FTS诊断，以及原语料只读检索；无模型调用。
- `run_audit_probes.py`：可在已装项目后端依赖的环境重跑：`python run_audit_probes.py --source /path/to/ResearchTrace --output probes.json`。脚本使用独立临时运行目录，读取原主库时只读；针对本次审阅包的数据结构和工作区。
- `review_scope.json`：原ZIP哈希和审阅边界。
- `browser_review.json`：本轮新浏览器验证被环境访问策略阻止，不能当作应用错误或PASS。
- `evidence/supplied_*.png`：原包已有截图，用于本次视觉评价；不是新拍的浏览器实测。

没有打包原始PDF、数据库、模型密钥、模型权重或字体。

## 发给Codex的启动指令

```text
阅读当前项目AGENTS.md及此次AUDIT_REPORT.md、CODEX_UPGRADE_TASK.md、RELEASE_GATES.md。
以现有代码为基础实施，不重建项目，不覆盖历史数据或清空额度。
先复现并修复P0，尤其是证据校验、官方语料零向量索引、模型路由和真实网络闭环。
主选Nemotron-3.5-Embed-8B-BF16及Nemotron-3.5-Rerank-8B-BF16，Qwen3-Embedding-8B做独立盲测对照。
新模型须真实部署和评测通过后才切默认；不能只改配置名。
继续完成P1三条演示：证据审计问答、版本变化影响、FutureWork时间条件核查。
先做无费用回归，真实API调用须有明确预算且与评审额度隔离。
每个阶段给出真实代码提交、验收证据和剩余阻塞，最终交付基本可提交的版本。
```