"""Produce a bounded technical PDF and a narrated actual-UI walkthrough plan."""
from pathlib import Path
import json,time,html
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,PageBreak,Image
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.colors import HexColor
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'deliverables';out.mkdir(exist_ok=True)
font=ROOT/'.tools/mineru-env/lib/python3.12/site-packages/docvortex/resources/fonts/DroidSansFallbackFull.ttf'
pdfmetrics.registerFont(TTFont('ResearchTraceChinese',str(font)))
body=ParagraphStyle('body',fontName='ResearchTraceChinese',fontSize=10.3,leading=17,wordWrap='CJK',spaceAfter=9,textColor=HexColor('#172b4d'))
heading=ParagraphStyle('heading',parent=body,fontSize=19,leading=28,spaceAfter=20)
pages=[
('研证 ResearchTrace · 技术说明',[
'每个结论都能回到原文的科研智能体。本文是实际开发状态说明，不能替代最终发布验收。版本日期：2026年11月17日。团队署名暂按用户要求省略。',
'参赛方向：科研小助手Agent。依据用户提供的七页赛题原件，覆盖PDF管理、知识问答、阅读翻译、学术检索与推荐、图谱综述和写作绘图。',
'评分权重：AI技术深度35%，产品功能和工程质量30%，创新性15%，用户体验10%，实用性10%。本地部署属于加分考察点，原件未给固定额外分值。',
'公开代码保留原有Git历史并继承Claude分支。所有模型密钥、评审访问码、Cookie及运行数据库只保存于私有环境。']),
('系统架构与真实输入路径',[
'React、TypeScript与Vite构成前端，PDF.js保留原论文版面并提供文本层、选择、目录和证据高亮。FastAPI提供API和统一工作区鉴权；SQLite WAL保存文献、快照、任务、引用与调用账本。',
'文档处理与交互任务使用独立Worker。任务持久化、幂等、可取消，并有单运行互斥锁。请求结果未知时保留计账，禁止直接恢复重发。',
'路径一：上传新PDF或20篇同领域论文→解析→选择版本→阅读与问答→检查引用。路径二：检索论文→下载合法可访问全文→解析→比较后续研究条件。路径三：输入idea或CSV→结构化写作、可编辑图代码或可复现数据图。',
'重型MinerU、PaddleOCR-VL及本地检索运行在隔离服务。ECS承载网页、API、SQLite与轻量调度，推理接口只绑定回环并经认证隧道访问。']),
('文档版本、解析与阅读',[
'PDF字节版本与解析快照分别保存。新引擎或重解析创建新快照，完整成功后原子切换；失败、取消和部分输出不覆盖历史锚点。每条结论绑定version_id、parse_id、block_id、物理页及区域。',
'上传时可选择保留较新版本、两个都保留或切换为本次版本，支持真实段落差异。被排除的版本仅退出新检索，历史PDF和引用仍可核对。',
'原生解析提供快速预览，已有MinerU处理复杂论文，PaddleOCR/PaddleOCR-VL处理扫描内容。题目核心四份PDF包括v1、v7、扫描版和541页教材，其余35份单独作为拓展语料。',
'阅读器新增真实PDF.js文本选择，支持翻译、解释和预填提问。翻译缓存按工作区、模型、语言、术语表和快照区分，公式及代码保留。中文摘要与全文译英文复用双向翻译服务。']),
('检索、证据检查与调用调度',[
'关键词使用对称分词的FTS5/BM25，向量按独立模型指纹和解析代际存储，以RRF融合；可选Nemotron重排用于相关性排序。重排分数不是结论支持性的证明。',
'候选本地模型为Nemotron 3.5 Embed和Rerank 8B BF16，保留Qwen3-Embedding-8B对照。GPU实时选卡、每卡至少保留2GiB，只清理本项目持有进程。资源不满足时明确降级或阻塞。',
'确定性校验检查空引文、原文子串、来源范围、数字、单位和正文绑定。Decision 1独立辅助审查，低置信度保留待复核；原文定位和语义支持分别显示。',
'账本区分HTTP尝试次数与Embedding批次中的文本条数。真实上游已确认当前云Embedding触及每日1000条额度；尚未完成的云索引不发布。历史4次Hydrogen smoke不重置，失败与未知请求始终保留。']),
('图谱、推荐、写作与查新闭环',[
'引用边来自参考文献和真实引用证据。NetworkX计算局部PageRank、入出度与介数中心性，前端Cytoscape.js支持节点角色与边证据查看。角色只解释当前文献集合，不能当作全领域权威排序。',
'参考文献重要性统计正文出现次数和章节，Lite按真实上下文分类方法依赖、实验对比或背景；下载父子任务有数量上限与取消恢复保护。',
'日/周推荐检索最新arXiv元数据，推荐理由严格限于标题和摘要。GitHub链接只显示代码线索，点赞和踩影响后续排序；定时任务需明确开启。',
'综述和论文框架按章节绑定已核验主张，References从核验来源白名单中选择。结构图由受控节点边生成Mermaid、Graphviz DOT、TikZ和Matplotlib源文件，不执行模型任意代码。',
'Future Work执行检索、全文下载、独立解析、日期区间比较和条件核查。只有更晚且通过支持性审查的本篇全文证据可以支持覆盖分类；否则标证据不足，不宣称全球首次。']),
('测试、部署与当前发布门槛',[
'集成阶段607项后端测试通过；之后的配额、缓存、证据与恢复测试另有日志。最终计数以evidence/completion-20261116/final-regression.log为准，测试数量不等于真实问答正确率。',
'实际UI在1280、1440、1920及390宽度检查，四份核心PDF实际渲染共32项检查通过。写作组件另有23项浏览器夹具检查，不把夹具等同真实模型质量。',
'公网researchtrace.sluna.xyz已签发HTTPS证书。独立浏览器完成固定评审登录和41份文献读取，零浏览器错误；生成密钥启用与调用账本切换仍需按部署记录确认。',
'80题关键词检索已实际执行，Qwen核心50题已有真实对照。Nemotron完整39份索引、云向量覆盖、全部真实生成题、Future Work三类示例及最终演示质量以逐项记录为准；不能把未执行或被限流部分写作PASS。',
'正式提交需5—8分钟1080p MP4、不超过30页技术PDF、公开仓库与Git历史、公网入口及体验账号。最终报名截止时间由团队在赛事个人中心确认。'])]
story=[]
for i,(title,paragraphs) in enumerate(pages):
 if i:story.append(PageBreak())
 story.append(Paragraph(html.escape(title),heading))
 for text in paragraphs:story.append(Paragraph(html.escape(text),body));story.append(Spacer(1,7))
 shot=ROOT/'evidence/completion-20261116/browser'/('1440-library.png' if i==0 else '1706.03762v7.pdf.png' if i==2 else '')
 if i in (0,2) and shot.is_file():story.append(Image(str(shot),width=440,height=305,kind='proportional'))
def foot(c,doc):
 c.setFont('ResearchTraceChinese',8);c.setFillColor(HexColor('#5b6b80'));c.drawString(42,25,'ResearchTrace · 实际开发与验收状态');c.drawRightString(550,25,str(doc.page))
SimpleDocTemplate(str(out/'ResearchTrace_技术说明.pdf'),pagesize=(595,842),leftMargin=42,rightMargin=42,topMargin=42,bottomMargin=45).build(story,onFirstPage=foot,onLaterPages=foot)
print('Generated technical PDF')
