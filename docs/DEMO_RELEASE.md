# ResearchTrace 参赛演示

正式 MP4 位于 [deliverables](../deliverables/ResearchTrace_实际界面演示_1080p.mp4)。片长 5 分 25 秒，1080p，普通话讲解，含 51 条中文字幕。访客在 [公网首页](https://researchtrace.sluna.xyz/) 可直接点播和下载 MP4。已有工作区会话也可以打开[演示页](https://researchtrace.sluna.xyz/demo)。评审访问码仍用于进入实际工作区。

视频使用 v32 的真实界面，架构、部署和检索对照画面引用技术文档。问答和修订总结展示已保存的结果。划词段落展示缓存译文。教材使用原件，在目录跳至 PDF 第 175 页，再在页码框定位第 300 页。版本录制使用改名 v1 和库中 v7，试录文件删除后确认评委文献库的 10 个版本 ID 完全相同。

旁白使用 `gemini-3.8-flash-tts` 的 Charon 音色，分 11 次生成，10 次成功，1 次返回 503。失败段用同模型首版音轨补齐。额外的 1 次 Flash Lite 对时尝试返回了不完整时间点，成片对时以本地语音识别和已有的首版时间轴为依据。本次录制不发起新问答或新翻译模型请求。

复现时，`scripts/synthesize_demo.py` 在服务器现有配额账本中记录调用，`scripts/assemble_demo.py CAPTURE_DIR OUTPUT_DIR` 用 FFmpeg 合成录屏、WAV 和中文字幕。生成网页播放副本。Windows Chrome 和 Edge 实测曾在 VP9 解码时报错，网页现在优先播放兼容版 H.264/AAC，出错时自动试 VP8/Opus。正式下载文件仍是原参赛 MP4。见 [播放复测](../evidence/demo-release-20261118/windows-playback.json)。

```bash
ffmpeg -i deliverables/ResearchTrace_实际界面演示_1080p.mp4 \
  -map 0:v:0 -map 0:a:0 -vf 'scale=in_range=full:out_range=limited,format=yuv420p' \
  -c:v libx264 -preset veryfast -profile:v baseline -level:v 4.0 -crf 21 \
  -maxrate 1800k -bufsize 3600k -g 60 -keyint_min 30 \
  -color_range tv -color_primaries bt709 -color_trc bt709 -colorspace bt709 \
  -c:a aac -ac 2 -b:a 128k -movflags +faststart researchtrace-play-v2.mp4
ffmpeg -i researchtrace-play-v2.mp4 \
  -map 0:v:0 -map 0:a:0 -c:v libvpx -deadline realtime -cpu-used 8 -threads 8 \
  -crf 14 -b:v 950k -maxrate 1600k -bufsize 3200k -g 75 -pix_fmt yuv420p \
  -c:a libopus -b:a 72k researchtrace-play-v2.webm
```

在发布主机上把两份网页播放副本、正式 MP4、[封面](../deliverables/ResearchTrace_演示封面.jpg)和[字幕](../deliverables/ResearchTrace_演示字幕.vtt)按 `deploy/nginx-researchtrace-demo.conf` 的文件名放入 `/opt/researchtrace/demo-media/`。仅在该站点加载该 Nginx 配置，前端使用 `VITE_PUBLIC_DEMO=1 npm run build` 构建。准备好媒体并核实字节范围请求返回 206 后再启用首页入口。
