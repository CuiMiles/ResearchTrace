# 2026-11-17 实施与验收状态

继承 Claude 分支 `6b02876`，开发分支 `upgrade/complete-20261116`。评分沿用原件 AI35/工程30/创新15/UX10/实用10。团队署名按用户要求暂不填。

公网入口：https://researchtrace.sluna.xyz 。已有 sluna.xyz 主站保留。Docker API、文档与交互 Worker、独立 nginx HTTPS、认证 GPU 隧道及夜间备份已经运行。新的 30 天评审账号位于私有 `data/completion-deployment/reviewer-20261117.json`，访问码不得提交或贴到公开日志。

已增量实现上传版本选择与差异、参考文献重要性及有界批量下载、图谱角色、20篇证据综述、来源核验的论文框架、四种图代码导出、中英双向翻译、阅读器划词与缓存、日/周推荐、真实 Agent 工具观察与补检索、Future Work 全文/日期/条件核查、独立评审种子复制。

当前证据：

- 核心4：本地 Nemotron 5330/5330 向量；Gemini 独立索引901/901片段覆盖5267原文块，完整后已原子激活并同步 ECS。云合并片段采用不同切分，必须与固定切分模型对照分开报告。全39本地索引已ready：23185/23185向量覆盖22950原文块，2189块按规则排除。ECS导入后逐段核对原文，并补齐同代旧元数据后原子激活；首次导入校验失败及元数据遗漏均保留。其余35云代正在免费token预检，未完成Embedding前保持BLOCKED。
- 新评审空间复制6231条现有向量，重新计算与供应商调用均为0；独立浏览器实际 HTTPS 登录、46份文献、工作区隔离和零页面异常，见 public-final-browser/report.json。
- 新账号真实中文问答使用云向量候选，回答“8张NVIDIA P100”，见 public-semantic-qa.json。实际 Agent 先取得设备/时长，再区分未报告费用，见 public-repair-live.json。
- 新中文PDF在ECS上传、解析、全文译英文及HTML导出通过，公式保留，见 public-generation-live.json；输入为自写测试页。
- 645项完整后端回归见worker-safe-final-regression.log（135.80秒），包括自动索引、token截断保护、Unicode跨度、批量权限、综述摘录及写锁退让。真实浏览器32项、写作夹具23项分别记录。
- 参考文献真实全文下载已通过。分类按12条持久化分批；收到的响应复用，未知请求不重发，冲突分类保守设uncertain。综述保留原响应，至多一次修正，仍未通过校验的主张显示证据缺口。
- ECS原始541页教材在独立压力工作区完成真实重解析，290.29秒/59项检查；同时CSV绘图5.437秒、五类导出和旧末页读取通过，见public-541-pressure.json。
- 原有失败、限流、Schema拒绝和低置信度均保留。程序可处理任务并不证明综述覆盖率或主张准确率已达发布目标。

生成与 Embedding 账本已经汇总到 ECS；本地 RT_PROVIDER_MODE=disabled，防止两个独立数据库同时消费同一模型额度。ECS已切回auto，本地Nemotron优先，GPU不可用时只使用独立的完整云索引备用，已有模型指纹和索引仍分开。原Hydrogen四次smoke、失败及未知调用没有重置，付费兜底关闭。最新实际用量见 public-runtime.json，配额日期按太平洋时间。

尚未关闭的发布门槛：Qwen/Gemini完整80题同输入对照、全35云向量覆盖、Future Work三种覆盖类别均取得可发布证据、全部官方问答及综述的独立人工质量复核、正式视频内容人工审阅。GitHub Actions工作流可创建任务，但账号因计费状态被锁，job未启动；属于BLOCKED，不能写作CI通过。记录见 https://github.com/CuiMiles/ResearchTrace/actions/runs/43944888341 。

交付物已实际生成：deliverables/ResearchTrace_技术说明.pdf（6页），ResearchTrace_实际界面演示_1080p.mp4（359.98秒、1920×1080、普通话讲解）。管理员流程页发布日志和材料，原始失败保留。整体尚未取得“全部验收通过”，暂不创建v1.0-submission标签。

## 本地全量检索与新输入补验

同一23,185片段/80问题上，核心45有答案题与拓展30题分开报告：关键词全部金标@20为37/45和16/30；Nemotron向量45/45和28/30；RRF融合45/45和26/30；增加真实重排后45/45和30/30，前五名命中44/45和24/30。五道无答案不进入检索Recall分母。题目含相关改写，金标独立人工复核NOT RUN，这不是问答准确率。见retrieval-nemotron-all(-rerank).json。

新自写Aster PDF已在公网完成上传→解析→独立持久索引→真实Flash与Decision问答，正确回答6张GPU，见new-pdf-auto-index-public.json。该输入是工程新输入测试，不冒充赛题核心资料。解析原文可先读，语义索引有独立排队/失败显示；额度本地预留失败时等实际供应商日界，未知已发送调用不重发。

云新切分先用4096字节候选、原生countTokens或保守字节上界，内容上限2000tokens（留48余量），超长无损拆分，完整后才切换。token元数据HTTP尝试与Embedding文本条数分别计账。其余35的当前代及任务见cloud-expansion-production.json；不得把staged或免费预检当作向量完成。
