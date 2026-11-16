# 2026-11-17 实施与验收状态

继承 Claude 分支 `6b02876`，当前开发分支 `upgrade/complete-20261116`。本文件是开发状态，不是正式提交通过证明。团队署名按用户要求暂不补。

已增量实现：上传版本选择及差异；正文引用重要性、Lite分类与有界参考文献下载；局部图谱角色；20篇证据综述、核验References的idea框架；四种可编辑结构图；中译英；PDF.js划词、解释/提问与缓存；日/周推荐和反馈；Future Work发现、全文解析、日期区间与支持性约束；独立评审种子复制；项目配额路由和真实请求单位；ECS Docker、独立nginx HTTPS、受限GPU隧道、备份和CI。

实际证据：

- `evidence/completion-20261116/final-regression.log`：611项后端测试通过（后续修复另有回归，最终以最新日志为准）。
- `browser/report.json`：真实服务、四种宽度、核心四PDF，共32项通过；不是拦截API的夹具。
- `writing-browser-fixture/report.json`：23项写作交互夹具检查，不能当真实模型质量。
- `public-browser/report.json`：独立浏览器实际HTTPS、固定评审登录、工作区隔离、41份文献读取，无页面异常。
- `official-live.json`、`feature-live.json`、`future-live.json`及`future-focused-live.json`：真实运行ID、原始失败、修复结果、引用和待复核状态。
- `feature-repair-live.json`：结构图缺失端点、推荐遗漏ID的受控一次修订已实测通过；旧响应仍在。
- `credential-probe.json`：第一凭据Flash日20额度耗尽；第二凭据Flash实际成功。按用户明确的两个项目资源配置，旧账本通过保守别名继续计入项目1，未清空历史。
- `cloud-token-preflight.json`：29个大输入中3个超出云模型2048 tokens，不静默截断。
- `cloud-core-production.json`：另建901片段的完整原文跨度合并索引，覆盖5267原文块。它改变切分，不能混入固定切分模型A/B结果。构建完成才原子激活。

当前发布门槛仍有BLOCKED：全39本地索引/共享GPU排队、云索引完整激活、全部官方问答的人工准确性、Future Work三类实际证据、最终公网生成切换和正式视频内容人工复核。一次模型调用成功不表示整项验收通过。

公网：https://researchtrace.sluna.xyz 。ECS现有sluna.xyz主站保留。评审访问码及环境配置均为私有文件，不能贴进仓库。部署副本初始不加载模型密钥，待账本切换后再启用；以最终运行状态为准。

交付物已实际生成：`deliverables/ResearchTrace_技术说明.pdf`（6页）、`deliverables/ResearchTrace_实际界面演示_1080p.mp4`（6分钟、1920×1080、普通话讲解）。演示是真实界面与标明时间的历史记录；不冒充实时新输入或已关闭全部发布门槛。
