# ResearchTrace 参赛演示

正式 MP4 位于 [deliverables](../deliverables/ResearchTrace_实际界面演示_1080p.mp4)。片长 5 分 25 秒，1080p，普通话讲解，含 51 条中文字幕。访客在 [公网首页](https://researchtrace.sluna.xyz/) 可直接点播和下载 MP4。已有工作区会话也可以打开[演示页](https://researchtrace.sluna.xyz/demo)。评审访问码仍用于进入实际工作区。

视频使用 v32 的真实界面，架构、部署和检索对照画面引用技术文档。问答和修订总结展示已保存的结果。划词段落展示缓存译文。教材使用原件，在目录跳至 PDF 第 175 页，再在页码框定位第 300 页。版本录制使用改名 v1 和库中 v7，试录文件删除后确认评委文献库的 10 个版本 ID 完全相同。

旁白使用 `gemini-3.8-flash-tts` 的 Charon 音色，分 11 次生成，10 次成功，1 次返回 503。失败段用同模型首版音轨补齐。额外的 1 次 Flash Lite 对时尝试返回了不完整时间点，成片对时以本地语音识别和已有的首版时间轴为依据。本次录制不发起新问答或新翻译模型请求。

复现时，`scripts/synthesize_demo.py` 在服务器现有配额账本中记录调用，`scripts/assemble_demo.py CAPTURE_DIR OUTPUT_DIR` 用 FFmpeg 合成录屏、WAV 和中文字幕。生成网页播放副本：

```bash
ffmpeg -i deliverables/ResearchTrace_实际界面演示_1080p.mp4 \
  -map 0:v:0 -map 0:a:0 -c:v libvpx-vp9 -deadline realtime -cpu-used 8 \
  -tile-columns 2 -row-mt 1 -threads 8 -crf 32 -b:v 0 -c:a libopus -b:a 72k \
  researchtrace-demo-1080p.webm
```

在发布主机上把 MP4、WebM、[封面](../deliverables/ResearchTrace_演示封面.jpg)和[字幕](../deliverables/ResearchTrace_演示字幕.vtt)按 `deploy/nginx-researchtrace-demo.conf` 的文件名放入 `/opt/researchtrace/demo-media/`。仅在该站点加载该 Nginx 配置，前端使用 `VITE_PUBLIC_DEMO=1 npm run build` 构建。静态媒体由 Nginx 提供字节范围请求。准备好媒体后再启用首页入口。
