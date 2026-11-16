# ResearchTrace 审阅升级阶段记录

基线 `cc54691`；当前分支 `upgrade/review-20261116`。本文件记录实施阶段，不代表全部发布门槛关闭。

## 验收范围

用户最新要求：核心集固定为 `1706.03762v1.pdf`、`1706.03762v7.pdf`、`1706.03762v1_img.pdf`、`UnderstandingDeepLearning_02_09_26_C.pdf`（541页）；其余35份是拓展集。文件SHA256、数据库版本、活动解析快照见 `evals/review_upgrade_scopes.json`。80条预先读取原PDF建立的问题为核心50/拓展30，包含相关的中英改写；不声称80个独立事实，也不声称已独立人工审核。

## 本阶段真实结果

| 项目 | 状态 | 证据与边界 |
|---|---|---|
| 工程自动回归 | PASS | `regression-progress6.log`：395 passed，80.29s；不是395道模型问答 |
| 前端构建、后端静态检查 | PASS | `frontend-progress6.log`；本地发布168文件，index最后替换 |
| 引用三个对抗反例 | PASS | `probes-before.json` 与 `probes-after-grounding.json`；空白引文、数字矛盾、正文绕过拦截 |
| 核心真实问答 | FAIL | `core4-qa-before-index.json` 保留首次失败；修复定位标识、作者枚举、科学计数法误判后复用原模型响应，Adam completed，作者/教材仍partial。不能算全部质量通过 |
| 20论文批量导入 | PASS | `batch-live.json`；20 ready，另1损坏文件独立失败，单项取消恢复、稳定评审空间重登录通过；批次模型调用0 |
| 双向真实翻译 | PASS | `translation-flash36-live.json`；3.6Flash两个方向各1调用，数字、引用和变量保护通过。中文来源是原中文赛题段落，不是中文论文质量基准 |
| 3.8Flash | FAIL | 两次超时/消耗未知，保留账本；另有TLS路由错误，不能认定官方故障。默认批量模型改为实测成功的3.6Flash |
| Decision1原生API | PASS | `decision-live-calibration.json`；1次createDecision、5个支持性反例+6个路由，11/11符合预设标签；这是小样本，不是整体准确率 |
| 本地BF16 GPU推理 | PASS | Nemotron Embed与Qwen8B双卡真实推理；Reranker跨卡mask/hidden device失败后修复，`rerank-device-alignment-live.json`复测通过 |
| 核心4份索引 | PASS | 5267合格源块、5330片段，5330/5330真实向量已完整构建并原子激活；云端调用0 |
| 拓展35份索引 | NOT RUN | 原39份已实际切分22950合格源块、23185片段；核心向量可按模型指纹和精确源跨度复用，拓展向量下一阶段构建 |
| 安全公开检索/全文 | PASS | `discovery-live-20261116T050427879151Z.json`：真实新查询、100页全文下载解析；SSRF/TLS/DNS固定保持 |
| 自主Agent/FutureWork新闭环 | NOT RUN | 有界反馈、子解析等待/恢复、日期区间/同年比较代码与离线测试已加入；完整新输入模型链路尚待实测 |
| 版本变化对笔记的影响 | PASS | `version-impact-live.json`：真实v1→v7，2项原引文仍可定位，4项需复核；这是原文映射，不是新版本语义支持结论，历史笔记不改写 |
| 新前端真实浏览器 | NOT RUN | 组件夹具证据单列；本阶段完整产品浏览器复验尚未完成 |
| 公网HTTPS/正式视频/PDF | NOT RUN | 本地服务不能替代外网新浏览器验证或正式文件 |

## 配额与资源

原Hydrogen smoke4及82行原始账本保留。用户随后明确授权两个模型各每日40次，并要求提高真实迭代频率；本地按模型跨项目总计40，失败和unknown同计。两Key仍按一个保守项目组去重，没有制造项目或账号。Decision单列本轮100次/日的保守测试上限，工作流5次；官方免费限额200RPM/50K输入TPM/10KRPD是供应商额度，不是已消费或保证容量。付费兜底关闭。

GPU下载和重型推理在新的远端私有目录，与旧项目/旧环境隔离。按实时空闲显存选卡，每卡保留≥2048MiB；NVML追踪本项目PID树，超过预算仅终止本项目会话。两个本项目模型服务使用自己的文件锁协调选卡，不限制或终止他人进程。第一次索引因nvidia-smi子进程探测超时而终止，失败快照保留；改用持久NVML查询后恢复同代。轮询不是绝对OOM保证。

API/文档worker/交互worker分开；重解析服务独立。`./scripts/dev.sh` 启动，当前本地入口 http://127.0.0.1:18980 。管理员“验收与截图”的10步流程已追加本轮真实记录和失败，原资料包历史记录保留。

官方接口依据：
- https://aistudio.google.com/docs/decisions-api
- https://aistudio.google.com/docs/models/gemini-decision-1
- https://aistudio.google.com/docs/rate-limits#gemini-decision
- https://aistudio.google.com/docs/pricing#gemini-decision

## 账本检查点（非官方余额）

```json
[
  {
    "model": "gemini-3.5-flash-lite",
    "status": "ok",
    "calls": 26,
    "input_tokens": 17371,
    "output_tokens": 16503
  },
  {
    "model": "gemini-3.6-flash",
    "status": "ok",
    "calls": 2,
    "input_tokens": 942,
    "output_tokens": 3356
  },
  {
    "model": "gemini-3.8-flash",
    "status": "unknown",
    "calls": 2,
    "input_tokens": 5075,
    "output_tokens": 0
  },
  {
    "model": "gemini-4-hydrogen",
    "status": "ok",
    "calls": 12,
    "input_tokens": 101038,
    "output_tokens": 51473
  },
  {
    "model": "gemini-decision-1",
    "status": "ok",
    "calls": 5,
    "input_tokens": 13387,
    "output_tokens": 0
  },
  {
    "model": "gemini-embedding-001",
    "status": "failed",
    "calls": 3,
    "input_tokens": 8611,
    "output_tokens": 0
  },
  {
    "model": "gemini-embedding-001",
    "status": "ok",
    "calls": 52,
    "input_tokens": 201057,
    "output_tokens": 0
  },
  {
    "model": "gemini-embedding-001",
    "status": "unknown",
    "calls": 1,
    "input_tokens": 5093,
    "output_tokens": 0
  }
]
```
