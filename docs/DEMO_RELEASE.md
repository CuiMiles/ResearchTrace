# ResearchTrace 参赛演示

正式 MP4 位于 [deliverables](../deliverables/ResearchTrace_实际界面演示_1080p.mp4)：7 分 16 秒，1080p，普通话讲解，52 句中文字幕直接烧录在画面里。访客打开 [公网首页](https://researchtrace.sluna.xyz/) 即可免登录播放和下载。评委用评审访问码进入工作区；也可以选「以游客身份体验」，游客只使用 Gemini 3.5 Flash Lite 和 Gemini 向量检索。

视频用评委账号在公网系统上实拍：版本识别、修订总结、中英对照、划词翻译、扫描件、541 页教材、现场提问、跨论文问答、执行记录、发现、图谱、写作和图表，最后是技术方案、本地模型、检索评测和工程质量。现场提问等待回答的时间，以及两次页面加载已剪掉，画面标注「快进」。录制时上传的 v1 在录完后删除，评委文献库的 10 个版本与录制前一致。

配音为 MiniMax `speech-2.8-hd`「青年大学生」（`male-qn-daxuesheng`），讲稿在 [narration_v3.json](../scripts/video/narration_v3.json)，共 13 次合成，每次 2–6 句。供应商返回的逐句时间戳用来切分字幕和安排画面。图中数字的来源与复算方法见 [视频证据](../evidence/demo-release-20261119/walkthrough-v3.json)。

## 复现

```bash
# 1. 在存放 MiniMax 密钥的主机上合成（密钥只从该主机的 .env 读取）
python3 scripts/video/tts_minimax.py scripts/video/narration_v3.json out
# 2. 本机：把 out/ 放到 $RT_VIDEO_WORK/v3/audio，生成时间轴和旁白音轨
RT_VIDEO_WORK=/tmp/rt-video .venv/bin/python scripts/video/timeline_v3.py
# 3. 公网实拍（需要到公网的 SOCKS 代理 127.0.0.1:18995 和评审访问码文件），参数为片中显示的测试数
RT_VIDEO_WORK=/tmp/rt-video .venv/bin/python scripts/video/record_v3.py 669
# 4. 合成 MP4（H.264/AAC，烧录字幕）、WebM（VP8/Opus）、SRT/VTT 与封面
RT_VIDEO_WORK=/tmp/rt-video .venv/bin/python scripts/video/compose_v3.py
```

`record_v3.py` 后面可以跟场景名，只重录这些场景，例如 `record_v3.py 669 version revision`。现场提问会产生一次真实的模型调用，并计入项目账本。

## 发布

网页播放 `/demo-media/researchtrace-demo-v4-1080p.mp4`，浏览器不支持 H.264 时改用同名 `.webm`，封面为 `researchtrace-demo-v4-poster.jpg`。文件放在发布主机的 `/opt/researchtrace/demo-media/`，nginx 路径见 [nginx-researchtrace-demo.conf](../deploy/nginx-researchtrace-demo.conf)，前端用 `VITE_PUBLIC_DEMO=1 npm run build` 构建。替换媒体后，先确认范围请求返回 206，再更新前端。
