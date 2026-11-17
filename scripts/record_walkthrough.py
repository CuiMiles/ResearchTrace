"""Record real UI frames with local Windows Mandarin narration. No model calls."""
from pathlib import Path
import json,os,subprocess,time,math,shutil
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'deliverables';private=ROOT/'data/completion-deployment/video';private.mkdir(parents=True,exist_ok=True)
scenes=[
('/', '项目与证据流程', '研证是一个面向科研阅读的证据追踪助手。它希望帮助用户管理论文、比较不同版本、查询研究事实，并回到原文检查结论。现在录制的是项目实际运行的界面，不是设计稿。演示中展示的问答带有真实运行记录，属于已经执行的历史结果，不会冒充实时重新生成。系统把文献处理、语义索引和事实审查分别记录；解析完成并不代表向量已经建立，找到引用也不代表结论必然正确。请注意界面中的待复核、失败以及证据不足提示。它们反映当前边界，也是科研使用中需要保留的信息。'),
('/library','文献、批量导入与版本选择','文献库保存了用户提供的测试材料。核心开发围绕注意力论文的第一版、第七版、原始扫描版，以及五百四十一页的深度学习教材，其余三十五份论文作为拓展。平台支持批量导入和持久任务，二十篇论文可以进入同一个研究空间。文件内容和论文版本分开管理；遇到同一作品不同版本时，可以保留较新版本、保留两个版本，或者将本次版本设为当前版本。选择会影响新的检索范围，原文件和历史引用仍然保留。右侧状态用于区分正在解析、解析完成和语义索引覆盖。'),
('/read/dceae303ec2f41cbbc4d88f047db9424','阅读与原文定位','这里打开的是注意力论文第七版。阅读器直接展示原始PDF，保留单双栏、表格、公式和图形的版式。目录和结构化原文可以辅助跳转；引用包含文档版本、解析快照、物理页码和页内坐标，避免新版本悄悄改变旧笔记依据。选中文字可以发起翻译、解释或将文字放入提问框。翻译结果按语言、模型和原文快照缓存，不能跨工作区复用私有内容。论文中的代码和公式需要保留，中文摘要翻译为英文也使用同一个双向翻译流程。'),
('/read/82451796b5294493b9e58f696fbb8adc','扫描PDF与解析快照','扫描论文无法只靠普通文本提取。项目保留了实际的OCR与MinerU处理通道，通过独立解析服务完成文字和布局识别。新的解析结果先形成独立快照，完整成功之后才切换为活动快照。失败和部分结果不会覆盖之前已经引用的段落。高级解析配置和资源信息可以展开查看，日常阅读则优先呈现论文内容。共享GPU按实时空闲显存分配，允许多卡，但每张卡仍需保留至少两个GiB余量。资源不足时明确报告阻塞，只会终止本项目拥有的测试进程。'),
('/read/4452fbc0c75443578fb2a2987629c19c','长文档与任务持久化','这是五百四十一页教材。长文档会逐页保存处理进度，断线之后可以恢复，而不需要从头覆盖全部原文。真正的空白页与识别失败分别记录。用户可以通过页码、目录和检索定位到后半部分，不能只验证文档前几页就宣布整本书通过。文档解析与交互问答使用不同执行池，减少长任务占住全部服务的情况。研究空间之间的文献、缓存和文件访问保持隔离。原始PDF、不可变解析块以及衍生的检索片段各自有明确职责，升级切分或模型时不需要破坏历史证据。'),
('/runs/ebd46511b255427080fc1fc6eab7d3f8','真实问答与第二道审查','这一页展示此前真实执行的GPU配置问答记录。请看回答、对应的原文引用以及公开的执行步骤。系统先检索候选证据，再由生成模型分析，程序检查引用和数值，Decision模型辅助审查支持性。空引文、原文八张显卡却回答八十张，以及自由正文绕过结构化主张的情况，应当被拦截或降为证据不足。相关性重排不是事实证明，模型审查也不能取代人工核对。对论文没有报告的费用和条件，系统应明确说明缺少证据。任务日志展示工具调用和结果，不展示或伪造隐藏思维过程。'),
('/insights','引用图谱与研究建议核查','局部引用图谱由实际参考文献关系建立，不能把向量相似就画成引用边。节点使用局部PageRank、度数与介数中心性描述基石、桥梁和边缘角色，界面给出规则和适用范围。点击引用关系可以核对原条目。研究建议核查则从旧论文的未来工作出发，检索后续候选，获取可访问全文并解析，再比较发表时间、研究任务和适用条件。系统区分直接相关证据、部分覆盖和当前范围证据不足；没有搜到不能推出全球首次，只有摘要也不能证明问题已经解决。'),
('/studio','写作导出与真实验收边界','写作工坊提供领域综述、论文框架、结构图和翻译入口。综述和框架按照章节绑定主张；参考文献只能来自已核验的记录，未完成实验保留为计划。架构图使用受控节点与边生成Mermaid、DOT、TikZ及Matplotlib源码，便于编辑和复现。CSV绘图根据真实数据生成图表与说明，不执行模型任意宿主代码。项目的自动测试、浏览器检查和真实调用分别记录，不能把测试数量换算成回答准确率。当前公网HTTPS和独立评审登录已经验证；云向量额度和共享GPU造成的限制仍然如实记录。最终发布应依据逐项验收，不以演示替代证据。')]
(out/'演示讲解稿.json').write_text(json.dumps([{'route':r,'title':t,'narration':s} for r,t,s in scenes],ensure_ascii=False,indent=2))
windows=Path('/mnt/c/Users/mingy/AppData/Local/Temp/ResearchTraceNarration');windows.mkdir(exist_ok=True)
for i,(_,_,text) in enumerate(scenes):(windows/(str(i)+'.txt')).write_text(text,encoding='utf-8-sig')
ps=windows/'speak.ps1';ps.write_text('''Add-Type -AssemblyName System.Speech
$rtSpeech=New-Object System.Speech.Synthesis.SpeechSynthesizer
$rtSpeech.SelectVoice('Microsoft Huihui Desktop')
$rtSpeech.Rate=0
for ($rtIndex=0;$rtIndex -lt 8;$rtIndex++) {
 $rtRoot=Join-Path $env:LOCALAPPDATA 'Temp\\ResearchTraceNarration'
 $rtInput=Join-Path $rtRoot ($rtIndex.ToString()+'.txt')
 $rtOutput=Join-Path $rtRoot ($rtIndex.ToString()+'.wav')
 $rtSpeech.SetOutputToWaveFile($rtOutput)
 $rtSpeech.Speak([System.IO.File]::ReadAllText($rtInput,[System.Text.Encoding]::UTF8))
 $rtSpeech.SetOutputToNull()
}
$rtSpeech.Dispose()
''',encoding='utf-8-sig')
subprocess.run(['/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',r'C:\Users\mingy\AppData\Local\Temp\ResearchTraceNarration\speak.ps1'],check=True,stdout=subprocess.DEVNULL)
ffmpeg=shutil.which('ffmpeg');ffprobe=str(Path(ffmpeg).with_name('ffprobe'))
import wave
lengths=[]
for i in range(8):
 source=windows/(str(i)+'.wav');target=private/(str(i)+'.wav');shutil.copyfile(source,target)
 with wave.open(str(target)) as f:lengths.append(f.getnframes()/f.getframerate())
concat=private/'audio.txt';concat.write_text('\n'.join("file '"+str(private/(str(i)+'.wav'))+"'" for i in range(8)))
ratio=sum(lengths)/360
assert .5<ratio<2,'Narration speed falls outside bounded range'
subprocess.run([ffmpeg,'-nostdin','-y','-loglevel','error','-f','concat','-safe','0','-i',str(concat),'-af','atempo='+str(ratio),str(private/'narration.wav')],check=True)
frames=[round(l/sum(lengths)*720) for l in lengths];frames[-1]+=720-sum(frames)
session=json.loads((ROOT/'data/competition-dataset-session.json').read_text());base='http://127.0.0.1:18980'
video=out/'ResearchTrace_实际界面演示_1080p.mp4'
command=[ffmpeg,'-y','-loglevel','error','-f','image2pipe','-framerate','2','-vcodec','mjpeg','-i','pipe:0','-i',str(private/'narration.wav'),'-c:v','libx264','-threads','2','-preset','fast','-crf','23','-pix_fmt','yuv420p','-r','30','-c:a','aac','-b:a','128k','-shortest','-movflags','+faststart',str(video)]
proc=subprocess.Popen(command,stdin=subprocess.PIPE,stderr=(private/'encode.log').open('w'))
started=time.monotonic();count=0;checks=[]
with sync_playwright() as p:
 b=p.chromium.launch(executable_path=str(ROOT/'apps/web/.browser-runtime/chrome-linux/chrome'),headless=True,args=['--no-sandbox'])
 c=b.new_context(viewport={'width':1920,'height':1080});c.add_cookies([{'name':'rt_session','value':session['cookie'],'url':base}]);page=c.new_page()
 for i,((route,title,text),number) in enumerate(zip(scenes,frames)):
  response=page.goto(base+route);page.wait_for_timeout(1200)
  if '/read/' in route:page.wait_for_selector('canvas',timeout=60000)
  page.evaluate("title=>{const p=document.createElement('div');p.textContent='实际界面录制 · '+title+' · 历史结果保留真实时间';p.style='position:fixed;left:80px;bottom:10px;z-index:99999;background:#10223be8;color:white;padding:10px 18px;border-radius:8px;font:18px sans-serif;pointer-events:none';document.body.append(p)}",title)
  for n in range(number):
   before=time.monotonic()
   if i==4 and n==number//2:
    field=page.get_by_label('页码',exact=True)
    if field.count():field.fill('541');field.press('Tab')
   if i in (1,5,6,7) and n in (number//3,2*number//3):page.mouse.wheel(0,350)
   frame=page.screenshot(type='jpeg',quality=78);proc.stdin.write(frame);count+=1
   time.sleep(max(0,.5-(time.monotonic()-before)))
  checks.append({'scene':title,'route':route,'http_status':response.status,'frames':number});print({'scene':i+1,'frames':count},flush=True)
 b.close()
proc.stdin.close();status=proc.wait();assert status==0,'Video encode failed'
(out/'video-evidence.json').write_text(json.dumps({'status':'PASS','file':video.name,'width':1920,'height':1080,'duration_seconds':count/2,'actual_ui_frames':count,'capture_fps':2,'output_fps':30,'narration':'local Windows Microsoft Huihui Mandarin TTS','synthesis_live_model_calls':0,'scenes':checks,'scope':'Actual project UI and timestamped historical records; does not certify incomplete release gates'},ensure_ascii=False,indent=2))
print('Recorded real walkthrough',video,flush=True)
