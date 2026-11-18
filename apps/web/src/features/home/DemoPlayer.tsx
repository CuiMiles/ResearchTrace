import { useRef, useState } from 'react';
import { Download, Play } from '../../icons';
import './demo-player.css';

const media = '/demo-media';
const videoPath = `${media}/researchtrace-demo-1080p.mp4`;

export function DemoPlayer() {
  const player = useRef<HTMLVideoElement>(null);
  const [started, setStarted] = useState(false);
  const [failed, setFailed] = useState(false);

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
          onPlay={() => setStarted(true)}
          onError={() => setFailed(true)}
          aria-label="ResearchTrace 参赛演示视频"
        >
          <source src={`${media}/researchtrace-demo-1080p.webm`} type="video/webm" />
          <source src={videoPath} type="video/mp4" />
          <track kind="captions" src={`${media}/researchtrace-demo-zh.vtt`} srcLang="zh-CN" label="简体中文" default />
        </video>
        {!started && !failed && (
          <button
            className="public-demo-play"
            type="button"
            onClick={() => void player.current?.play().catch(() => setFailed(true))}
          >
            <Play size={23} />
            播放演示
          </button>
        )}
      </div>
      <footer>
        <span>{failed ? '无法在此播放，可下载 MP4。' : '普通话讲解 · 中文字幕 · 1080p'}</span>
        <a href={videoPath} download>
          <Download size={15} />
          下载 MP4
        </a>
      </footer>
    </section>
  );
}
