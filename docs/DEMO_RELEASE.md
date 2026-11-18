# ResearchTrace 参赛演示

正式 MP4 位于 [deliverables](../deliverables/ResearchTrace_实际界面演示_1080p.mp4)。片长 6 分 25 秒，1080p，普通话讲解，含 51 条亮蓝色中文字幕。访客在 [公网首页](https://researchtrace.sluna.xyz/) 可直接点播和下载 MP4。已有工作区会话也可以打开[演示页](https://researchtrace.sluna.xyz/demo)。评审访问码仍用于进入实际工作区。

视频使用 v32 的真实界面，架构、部署和检索对照画面引用技术文档。问答和修订总结展示已保存的结果。划词段落展示缓存译文。教材使用原件，在目录跳至 PDF 第 175 页，再在页码框定位第 300 页。版本录制使用改名 v1 和库中 v7，试录文件删除后确认评委文献库的 10 个版本 ID 完全相同。

配音为用户选定的 MiniMax Speech 2.8 HD「青年大学生」。开头四段复用已确认的 A 版试听，其余 47 段按 12 批使用 M Plan 合成。供应商返回逐词时间戳，按讲稿校验后用于对齐画面和字幕。现用的逐段讲稿在 [答辩讲解稿](../deliverables/研证_答辩讲解稿.json)，用量与版本验收见 [学术配音复测](../evidence/demo-release-20261118/academic-narration.json)。

`scripts/assemble_demo.py CAPTURE_DIR OUTPUT_DIR --narration-dir NARRATION_DIR` 可读取学术版讲稿、旁白 WAV 和分段时间轴并重建视频。MiniMax 只参与离线配音。网页播放使用独立的兼容副本。Windows Chrome 和 Edge 实测曾在 VP9 解码时报错，网页现在优先播放兼容版 H.264/AAC，出错时自动试 VP8/Opus。网页字幕为亮蓝字、深色底，上移至播放器控制栏上方，可在播放器内关闭。正式下载文件将相同配色的字幕烧录至画面，播放时直接可见。见 [播放复测](../evidence/demo-release-20261118/windows-playback.json)。

```bash
# 使用 assemble_demo.py 输出的未烧录字幕版本。
ffmpeg -i RENDER_DIR/researchtrace-demo-1080p.mp4 \
  -map 0:v:0 -map 0:a:0 -c copy -movflags +faststart researchtrace-play-v3.mp4
ffmpeg -i researchtrace-play-v3.mp4 \
  -map 0:v:0 -map 0:a:0 -c:v libvpx -deadline realtime -cpu-used 8 -threads 8 \
  -crf 14 -b:v 950k -maxrate 1600k -bufsize 3200k -g 75 -pix_fmt yuv420p \
  -c:a libopus -b:a 72k researchtrace-play-v3.webm
# FFmpeg 需支持 libass，系统需安装 Source Han Sans SC。
python3 scripts/style_demo_captions.py RENDER_DIR/researchtrace-demo-zh.vtt \
  researchtrace-play-v3.mp4 BLUE_OUTPUT_DIR
```

在发布主机上把两份网页播放副本、正式 MP4、[封面](../deliverables/ResearchTrace_演示封面.jpg)和[字幕](../deliverables/ResearchTrace_演示字幕.vtt)按 `deploy/nginx-researchtrace-demo.conf` 的文件名放入 `/opt/researchtrace/demo-media/`。仅在该站点加载该 Nginx 配置，前端使用 `VITE_PUBLIC_DEMO=1 npm run build` 构建。准备好媒体并核实字节范围请求返回 206 后再启用首页入口。
