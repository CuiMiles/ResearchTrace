import { useEffect, useRef, useState } from 'react';
import { getDocument, GlobalWorkerOptions, TextLayer, type PDFDocumentProxy, type RenderTask } from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import { endpoint, errorMessage } from './api';
import { Busy, ErrorBox } from './ui';
import type { Evidence, Version } from './types';
import './styles/selection.css';

GlobalWorkerOptions.workerSrc = workerUrl;
export interface PdfSelection {
  text: string;
  version_id: string;
  page_index: number;
  text_anchor: { exact: string; prefix: string; suffix: string };
}
function rotateBox(b: number[], rotation: number) {
  const [x, y, x1, y1] = b;
  switch ((rotation + 360) % 360) {
    case 90: return [1 - y1, x, 1 - y, x1];
    case 180: return [1 - x1, 1 - y1, 1 - x, 1 - y];
    case 270: return [y, 1 - x1, y1, 1 - x];
    default: return b;
  }
}
export function PdfReader({ version, pageIndex, zoom, rotation, highlight, onPages, onSelection }: {
  version: Version; pageIndex: number; zoom: number; rotation: number; highlight: Evidence | null;
  onPages: (pages: number) => void; onSelection?: (selection: PdfSelection | null) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const surface = useRef<HTMLDivElement>(null);
  const callbacks = useRef({ onPages, onSelection });
  callbacks.current = { onPages, onSelection };
  const [document, setDocument] = useState<{ id: string; pdf: PDFDocumentProxy } | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [textState, setTextState] = useState<'loading' | 'ready' | 'empty' | 'error'>('loading');
  const [size, setSize] = useState({ width: 600, height: 840 });
  const [containerWidth, setWidth] = useState(700);
  const [selectionError, setSelectionError] = useState('');
  useEffect(() => {
    const el = host.current;
    if (!el) return;
    const observer = new ResizeObserver(entries => setWidth(entries[0].contentRect.width));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    let live = true;
    let task: ReturnType<typeof getDocument> | undefined;
    const abort = new AbortController();
    setError(''); setLoading(true); setDocument(null);
    // Fetch under our AbortController before handing owned bytes to PDF.js.
    // This avoids v4's outstanding network-reader/worker teardown race during
    // rapid navigation, without swallowing unrelated global promise failures.
    void (async () => {
      const response = await fetch(endpoint(`/documents/${version.id}/file`), { credentials: 'same-origin', signal: abort.signal });
      if (!response.ok) throw new Error(`原文载入失败（${response.status}）`);
      const data = await response.arrayBuffer();
      if (!live) return;
      if (data.byteLength > 50 * 1024 * 1024) throw new Error('原文超过阅读器的 50 MiB 文件限制');
      task = getDocument({ data, isEvalSupported: false });
      const pdf = await task.promise;
      if (live) { setDocument({ id: version.id, pdf }); callbacks.current.onPages(pdf.numPages); }
    })().catch(e => { if (live) { setError(errorMessage(e)); setLoading(false); } });
    return () => {
      live = false; abort.abort();
      // Both task.promise (above) and destroy() are observed. Never suppress
      // window-level errors; only cancellation of this owned resource is quiet.
      if (task) void task.destroy().catch(() => {});
    };
  }, [version.id]);
  useEffect(() => {
    callbacks.current.onSelection?.(null); setSelectionError(''); setTextState('loading');
    if (!document || document.id !== version.id || !surface.current) return;
    let disposed = false;
    let render: RenderTask | undefined;
    let textLayer: TextLayer | undefined;
    const root = surface.current;
    // Separate DOM surfaces ensure a cancelled render never shares a canvas
    // with its successor (including StrictMode's setup/cleanup/setup cycle).
    const canvas = window.document.createElement('canvas');
    const text = window.document.createElement('div');
    text.className = 'textLayer'; text.tabIndex = 0;
    text.setAttribute('aria-label', '原文可选择文字，选择后可翻译、解释或提问');
    canvas.setAttribute('aria-label', `${version.title}，第 ${pageIndex + 1} 页`);
    root.replaceChildren(canvas, text);
    setLoading(true); setError('');
    void (async () => {
      const page = await document.pdf.getPage(pageIndex + 1);
      if (disposed) return;
      const angle = (page.rotate + rotation) % 360;
      const initial = page.getViewport({ scale: 1, rotation: angle });
      const scale = Math.max(0.25, (containerWidth - 64) / initial.width) * zoom;
      const viewport = page.getViewport({ scale, rotation: angle });
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.floor(viewport.width * ratio); canvas.height = Math.floor(viewport.height * ratio);
      canvas.style.width = `${viewport.width}px`; canvas.style.height = `${viewport.height}px`;
      setSize({ width: viewport.width, height: viewport.height });
      text.style.setProperty('--scale-factor', String(viewport.scale));
      render = page.render({ canvasContext: canvas.getContext('2d')!, viewport, transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : undefined });
      const textPromise = (async () => {
        const content = await page.getTextContent();
        if (disposed) return;
        const hasText = content.items.some(item => 'str' in item && item.str.trim());
        if (hasText) {
          textLayer = new TextLayer({ textContentSource: content, container: text, viewport });
          await textLayer.render();
        }
        if (!disposed) setTextState(hasText ? 'ready' : 'empty');
      })();
      await Promise.all([render.promise, textPromise]);
      if (!disposed) setLoading(false);
    })().catch(e => {
      if (!disposed) { setError(errorMessage(e)); setTextState('error'); setLoading(false); }
    });
    return () => { disposed = true; render?.cancel(); textLayer?.cancel(); canvas.remove(); text.remove(); };
  }, [document, version.id, pageIndex, zoom, rotation, containerWidth]);
  useEffect(() => {
    let frame = 0;
    const readSelection = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const selection = window.getSelection();
        const layer = surface.current?.querySelector('.textLayer');
        if (!selection?.rangeCount || selection.isCollapsed || !layer) return;
        const range = selection.getRangeAt(0);
        if (!layer.contains(range.startContainer) || !layer.contains(range.endContainer)) return;
        const exact = selection.toString().trim();
        if (!exact) return;
        if (exact.length > 12000) { setSelectionError('选段超过 12000 字符，请缩小选择范围。'); callbacks.current.onSelection?.(null); return; }
        setSelectionError('');
        const before = range.cloneRange(); before.selectNodeContents(layer); before.setEnd(range.startContainer, range.startOffset);
        const after = range.cloneRange(); after.selectNodeContents(layer); after.setStart(range.endContainer, range.endOffset);
        callbacks.current.onSelection?.({ text: exact, version_id: version.id, page_index: pageIndex,
          text_anchor: { exact, prefix: before.toString().slice(-64), suffix: after.toString().slice(0, 64) } });
      });
    };
    window.document.addEventListener('selectionchange', readSelection);
    return () => { cancelAnimationFrame(frame); window.document.removeEventListener('selectionchange', readSelection); };
  }, [version.id, pageIndex]);
  const box = highlight?.version_id === version.id && highlight.page_index === pageIndex && highlight.bbox?.length === 4 ? rotateBox(highlight.bbox, rotation) : null;
  useEffect(() => {
    if (loading || !box || !host.current) return;
    const el = host.current;
    el.scrollTop = Math.max(0, box[1] * size.height + 25 - el.clientHeight * .25);
    el.scrollLeft = Math.max(0, (box[0] + box[2]) * size.width / 2 + 22 - el.clientWidth / 2);
  }, [loading, highlight?.block_id, rotation, size.height, size.width]);
  return <div className="pdf-scroller" ref={host}>
    {error && <ErrorBox error={error} />}
    {selectionError && <p role="status" className="selection-notice">{selectionError}</p>}
    {textState === 'empty' && <p role="status" className="selection-notice">此页没有 PDF 文字层（可能是扫描页或空白页）。请切换「中英对照」，在 OCR 解析原文中选择段落；识别未完成时先运行 OCR 解析。</p>}
    <div className="pdf-sheet" style={{ width: size.width, height: size.height }}>
      <div ref={surface} className="pdf-page-surface" />
      {box && <div className="evidence-highlight" data-testid="evidence-highlight" style={{ left: `${box[0] * 100}%`, top: `${box[1] * 100}%`, width: `${(box[2] - box[0]) * 100}%`, height: `${(box[3] - box[1]) * 100}%` }} />}
      {loading && !error && <div className="pdf-loading"><Busy>正在载入原文</Busy></div>}
    </div>
  </div>;
}
