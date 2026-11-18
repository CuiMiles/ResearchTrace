import { useEffect, useRef, useState } from 'react';
import { Download, Play } from '../../icons';
import './demo-player.css';

const media = '/demo-media';
const mp4 = `${media}/researchtrace-play-v3.mp4`;
const webm = `${media}/researchtrace-play-v3.webm`;
const download = `${media}/researchtrace-demo-academic-1080p.mp4`;

export function DemoPlayer() {
  const player = useRef<HTMLVideoElement>(null);
  const sources = useRef([mp4, webm]);
  const sourceIndex = useRef(0);
  const loadId = useRef(0);
  const playRequested = useRef(false);
  const resumeAt = useRef(0);
  const exhausted = useRef(false);
  const [started, setStarted] = useState(false);
  const [notice, setNotice] = useState<'ready' | 'press-play' | 'retry'>('ready');

  useEffect(() => {
    const video = player.current;
    if (!video || video.hasAttribute('src')) return;
    // Some Chromium builds omit H.264. Browsers with both codecs use MP4 first.
    if (!video.canPlayType('video/mp4; codecs="avc1.42C028,mp4a.40.2"')
        && video.canPlayType('video/webm; codecs="vp8,opus"')) {
      sources.current = [webm, mp4];
    }
    video.src = sources.current[0];
  }, []);

  function load(video: HTMLVideoElement, index: number) {
    loadId.current += 1;
    sourceIndex.current = index;
    video.src = sources.current[index];
    video.load();
    setStarted(false);
    setNotice('ready');
  }

  function sourceFailed(video: HTMLVideoElement) {
    if (exhausted.current) return;
    if (video.currentTime > 0) resumeAt.current = video.currentTime;
    const next = sourceIndex.current + 1;
    if (next < sources.current.length) {
      load(video, next);
      if (playRequested.current) start(video);
      return;
    }
    exhausted.current = true;
    setStarted(false);
    setNotice('retry');
  }

  function start(video: HTMLVideoElement) {
    playRequested.current = true;
    const attempt = loadId.current;
    void video.play().catch((error: unknown) => {
      if (attempt !== loadId.current) return;
      const name = error instanceof DOMException ? error.name : '';
      if (name === 'AbortError') return;
      if (name === 'NotAllowedError') {
        playRequested.current = false;
        setStarted(false);
        setNotice('press-play');
        return;
      }
      sourceFailed(video);
    });
  }

  function play() {
    const video = player.current;
    if (!video) return;
    if (exhausted.current) {
      exhausted.current = false;
      load(video, 0);
    }
    start(video);
  }

  return (
    <section className="public-demo" aria-labelledby="public-demo-title">
      <header>
        <h2 id="public-demo-title">项目演示</h2>
        <p>论文版本比较、扫描件解析与原文证据核验</p>
      </header>
      <div className="public-demo-screen">
        <video
          ref={player}
          controls
          playsInline
          preload="metadata"
          poster={`${media}/researchtrace-demo-poster.jpg`}
          onPlay={() => { playRequested.current = true; }}
          onPause={(event) => { if (!event.currentTarget.error) playRequested.current = false; }}
          onPlaying={() => { setStarted(true); setNotice('ready'); }}
          onLoadedMetadata={(event) => {
            const video = event.currentTarget;
            if (resumeAt.current > 0 && resumeAt.current < video.duration) video.currentTime = resumeAt.current;
            resumeAt.current = 0;
          }}
          onError={(event) => {
            const video = event.currentTarget;
            // A queued error from an earlier source can arrive after load().
            if (video.error && video.error.code !== 1) sourceFailed(video);
          }}
          aria-label="ResearchTrace 参赛演示视频"
        >
          <track kind="captions" src={`${media}/researchtrace-demo-academic-zh.vtt`} srcLang="zh-CN" label="简体中文" default />
        </video>
        {!started && (
          <button className="public-demo-play" type="button" onClick={play}>
            <Play size={23} />
            {notice === 'retry' ? '重试播放' : notice === 'press-play' ? '继续播放' : '播放演示'}
          </button>
        )}
      </div>
      <footer>
        <span role="status">
          {notice === 'retry' ? '视频暂时未能加载，可重试或在线打开。'
            : notice === 'press-play' ? '请点击继续播放。' : '普通话 · AI 配音 · 中文字幕 · 1080p'}
        </span>
        {notice === 'retry' && <a href={mp4} target="_blank" rel="noreferrer">在线播放 MP4</a>}
        <a href={download} download>
          <Download size={15} />
          下载 MP4
        </a>
      </footer>
    </section>
  );
}
