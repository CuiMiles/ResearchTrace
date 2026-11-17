import { forwardRef, useCallback, useEffect, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { TextLayer, type PDFDocumentProxy, type RenderTask } from 'pdfjs-dist';
import { errorMessage } from './api';
import { Busy, ErrorBox } from './ui';
import type { Evidence, Version } from './types';
import type { PdfDocumentState } from './reader/usePdfDocument';
import './styles/selection.css';

export interface PdfSelection {
  text: string;
  version_id: string;
  page_index: number;
  text_anchor: { exact: string; prefix: string; suffix: string };
}
/** Position inside the document: physical page and normalized vertical offset (0–1). */
export interface ViewAnchor { page: number; y: number }
export interface PdfReaderHandle {
  scrollToAnchor: (page: number, y: number) => void;
  revealBox: (page: number, bbox: number[]) => void;
}
type PageStatus = 'loading' | 'ready' | 'empty' | 'error';

const GAP = 16;
const PAD = 20;
const MAX_FIT_WIDTH = 1080;
const POPOVER_WIDTH = 380;

function rotateBox(b: number[], rotation: number) {
  const [x, y, x1, y1] = b;
  switch ((rotation + 360) % 360) {
    case 90: return [1 - y1, x, 1 - y, x1];
    case 180: return [1 - x1, 1 - y1, 1 - x, 1 - y];
    case 270: return [y, 1 - x1, y1, 1 - x];
    default: return b;
  }
}
/** Inverse of rotateBox for a single display point. */
function unrotatePoint(x: number, y: number, rotation: number): [number, number] {
  switch ((rotation + 360) % 360) {
    case 90: return [y, 1 - x];
    case 180: return [1 - x, 1 - y];
    case 270: return [1 - y, x];
    default: return [x, y];
  }
}

interface Props {
  doc: PdfDocumentState;
  version: Version;
  pageIndex: number;
  zoom: number;
  rotation: number;
  highlight: Evidence | null;
  hoverBox?: { page_index: number; bbox: number[] } | null;
  onPages: (pages: number) => void;
  onPageChange: (page: number) => void;
  onSelection?: (selection: PdfSelection | null) => void;
  /** Rendered next to the current text selection; scrolls with the page. */
  selectionPopover?: ReactNode;
  onViewport?: (anchor: ViewAnchor) => void;
  onActivate?: () => void;
  onPagePoint?: (page: number, x: number, y: number) => void;
}

export const PdfReader = forwardRef<PdfReaderHandle, Props>(function PdfReader({
  doc, version, pageIndex, zoom, rotation, highlight, hoverBox, onPages, onPageChange, onSelection,
  selectionPopover, onViewport, onActivate, onPagePoint,
}, ref) {
  const scroller = useRef<HTMLDivElement>(null);
  const pagesHost = useRef<HTMLDivElement>(null);
  const callbacks = useRef({ onPages, onPageChange, onSelection, onViewport, onPagePoint });
  callbacks.current = { onPages, onPageChange, onSelection, onViewport, onPagePoint };
  const pdf = doc.pdf && doc.id === version.id ? doc.pdf : null;
  const [base, setBase] = useState<{ width: number; height: number; rotation: number } | null>(null);
  // Pages whose size differs from page 1, tagged with the rotation they were measured at.
  const [overrides, setOverrides] = useState<{ rotation: number; sizes: Record<number, { width: number; height: number }> }>({ rotation, sizes: {} });
  const baseRef = useRef(base);
  baseRef.current = base;
  const [containerWidth, setContainerWidth] = useState(800);
  const [range, setRange] = useState<[number, number]>([0, 2]);
  const [status, setStatus] = useState<Record<number, PageStatus>>({});
  const [placement, setPlacement] = useState<{ top: number; left: number; above: boolean } | null>(null);
  const [selectionError, setSelectionError] = useState('');
  const current = useRef(pageIndex);
  const anchor = useRef<ViewAnchor>({ page: pageIndex, y: 0 });
  const suppressReport = useRef(false);
  const frame = useRef(0);

  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const observer = new ResizeObserver(entries => setContainerWidth(entries[0].contentRect.width));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Base page size from page 1; differently sized pages correct themselves when rendered.
  useEffect(() => {
    setBase(null); setOverrides({ rotation, sizes: {} }); setStatus({}); setPlacement(null);
    if (!pdf) return;
    let live = true;
    callbacks.current.onPages(pdf.numPages);
    void pdf.getPage(1).then(page => {
      if (!live) return;
      const viewport = page.getViewport({ scale: 1, rotation: (page.rotate + rotation) % 360 });
      setBase({ width: viewport.width, height: viewport.height, rotation });
    }).catch(() => { if (live) setBase(rotation % 180 ? { width: 792, height: 612, rotation } : { width: 612, height: 792, rotation }); });
    return () => { live = false; };
  }, [pdf, rotation]);

  const pageCount = pdf?.numPages ?? 0;
  const scale = base ? Math.max(0.25, Math.min(containerWidth - PAD * 2 - 8, MAX_FIT_WIDTH) / base.width) * zoom : 1;
  const layout = useMemo(() => {
    const tops: number[] = [], widths: number[] = [], heights: number[] = [];
    if (!base) return { tops, widths, heights, total: 0, maxWidth: 0 };
    let y = PAD, maxWidth = 0;
    const sizes = overrides.rotation === base.rotation ? overrides.sizes : {};
    for (let i = 0; i < pageCount; i++) {
      const size = sizes[i] ?? base;
      tops.push(y); widths.push(size.width * scale); heights.push(size.height * scale);
      maxWidth = Math.max(maxWidth, size.width * scale);
      y += size.height * scale + GAP;
    }
    return { tops, widths, heights, total: y - GAP + PAD, maxWidth };
  }, [base, overrides, pageCount, scale]);
  const ready = Boolean(pdf && base && base.rotation === rotation && layout.tops.length);

  const pageAt = useCallback((position: number) => {
    const { tops } = layout;
    let lo = 0, hi = tops.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (tops[mid] <= position) lo = mid; else hi = mid - 1;
    }
    return Math.max(0, lo);
  }, [layout]);

  const measure = useCallback(() => {
    const el = scroller.current;
    if (!el || !layout.tops.length) return;
    const top = el.scrollTop, height = el.clientHeight;
    const first = pageAt(top), last = pageAt(top + height);
    const next: [number, number] = [Math.max(0, first - 1), Math.min(layout.tops.length - 1, last + 1)];
    setRange(prev => (prev[0] === next[0] && prev[1] === next[1] ? prev : next));
    const line = top + height * 0.1;
    const page = pageAt(line);
    const y = Math.max(0, Math.min(1, (line - layout.tops[page]) / layout.heights[page]));
    anchor.current = { page, y };
    if (suppressReport.current) { suppressReport.current = false; return; }
    const reading = pageAt(top + Math.min(height * 0.3, 240));
    if (reading !== current.current) { current.current = reading; callbacks.current.onPageChange(reading); }
    callbacks.current.onViewport?.({ page, y });
  }, [layout, pageAt]);

  const onScroll = () => {
    cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(measure);
  };
  useEffect(() => () => cancelAnimationFrame(frame.current), []);

  const scrollToAnchor = useCallback((page: number, y: number) => {
    const el = scroller.current;
    if (!el || !layout.tops.length) return;
    const p = Math.max(0, Math.min(layout.tops.length - 1, page));
    el.scrollTop = layout.tops[p] + y * layout.heights[p] - el.clientHeight * 0.1;
  }, [layout]);
  const revealBox = useCallback((page: number, bbox: number[]) => {
    const el = scroller.current;
    if (!el || !layout.tops[page]) return;
    const box = rotateBox(bbox, rotation);
    const boxTop = layout.tops[page] + box[1] * layout.heights[page];
    const boxBottom = layout.tops[page] + box[3] * layout.heights[page];
    if (boxTop < el.scrollTop + 40 || boxBottom > el.scrollTop + el.clientHeight - 40) {
      el.scrollTop = Math.max(0, boxTop - el.clientHeight * 0.25);
    }
    if (layout.widths[page] > el.clientWidth) {
      const offset = Math.max(0, (el.scrollWidth - layout.widths[page]) / 2);
      el.scrollLeft = Math.max(0, offset + (box[0] + box[2]) / 2 * layout.widths[page] - el.clientWidth / 2);
    }
  }, [layout, rotation]);
  useImperativeHandle(ref, () => ({ scrollToAnchor, revealBox }), [scrollToAnchor, revealBox]);

  // Keep the reading position when zoom, rotation or panel width change the page size.
  useLayoutEffect(() => {
    if (!ready) return;
    const el = scroller.current;
    if (!el) return;
    const { page, y } = anchor.current;
    suppressReport.current = true;
    el.scrollTop = layout.tops[Math.min(page, layout.tops.length - 1)] + y * layout.heights[Math.min(page, layout.heights.length - 1)] - el.clientHeight * 0.1;
    measure();
    // Primitive deps only: an object here can be re-created by React while it
    // rebases pending updates, which would re-run this effect without end.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, scale, rotation, layout.total]);

  // Navigation from the toolbar, outline, search or references.
  const navigated = useRef(false);
  useEffect(() => {
    if (!ready) return;
    if (navigated.current && pageIndex === current.current) return;
    navigated.current = true;
    const el = scroller.current;
    if (!el) return;
    const page = Math.max(0, Math.min(layout.tops.length - 1, pageIndex));
    current.current = page;
    anchor.current = { page, y: 0 };
    suppressReport.current = true;
    el.scrollTop = page === 0 ? 0 : layout.tops[page] - 8;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pageIndex, ready]);

  // Evidence opened from an answer: bring its region into view (declared after
  // navigation so the precise box wins over the page top).
  useEffect(() => {
    if (!ready || !highlight || highlight.version_id !== version.id) return;
    const page = highlight.page_index;
    if (page < 0 || page >= layout.tops.length) return;
    current.current = page;
    suppressReport.current = true;
    if (highlight.bbox?.length === 4) revealBox(page, highlight.bbox);
    else if (scroller.current) scroller.current.scrollTop = layout.tops[page] - 8;
    callbacks.current.onPageChange(page);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, highlight?.block_id, highlight?.page_index, highlight?.version_id]);

  // Text selection: read after the pointer is released so the popover does not
  // chase the mouse during a drag; keyboard and programmatic selections still work.
  const dragging = useRef(false);
  useEffect(() => {
    let raf = 0;
    const read = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        if (dragging.current) return;
        const host = pagesHost.current;
        const selection = window.getSelection();
        if (!host || !selection?.rangeCount || selection.isCollapsed) return;
        const range = selection.getRangeAt(0);
        const layerOf = (node: Node) => (node instanceof Element ? node : node.parentElement)?.closest('.textLayer');
        const startLayer = layerOf(range.startContainer), endLayer = layerOf(range.endContainer);
        if (!startLayer || !endLayer || !host.contains(startLayer) || !host.contains(endLayer)) return;
        const exact = selection.toString().trim();
        if (!exact) return;
        if (exact.length > 12000) { setSelectionError('选中的文字太长（超过 12000 字符），请缩小选择范围。'); setPlacement(null); callbacks.current.onSelection?.(null); return; }
        setSelectionError('');
        const pageElement = startLayer.closest<HTMLElement>('.pdf-page');
        const page = Number(pageElement?.dataset.pageIndex ?? 0);
        const before = range.cloneRange(); before.selectNodeContents(startLayer); before.setEnd(range.startContainer, range.startOffset);
        const after = range.cloneRange(); after.selectNodeContents(endLayer); after.setStart(range.endContainer, range.endOffset);
        const rect = range.getBoundingClientRect();
        const hostRect = host.getBoundingClientRect();
        const view = scroller.current!.getBoundingClientRect();
        const width = Math.min(POPOVER_WIDTH, scroller.current!.clientWidth - 16);
        const visibleLeft = scroller.current!.scrollLeft;
        const left = Math.max(visibleLeft + 8, Math.min(rect.left - hostRect.left, visibleLeft + scroller.current!.clientWidth - width - 8));
        const above = rect.bottom + 150 > view.bottom && rect.top - 150 > view.top;
        setPlacement({ left, above, top: above ? rect.top - hostRect.top - 10 : rect.bottom - hostRect.top + 10 });
        callbacks.current.onSelection?.({ text: exact, version_id: version.id, page_index: page,
          text_anchor: { exact, prefix: before.toString().slice(-64), suffix: after.toString().slice(0, 64) } });
      });
    };
    const release = () => { if (dragging.current) { dragging.current = false; read(); } };
    window.document.addEventListener('selectionchange', read);
    window.addEventListener('pointerup', release);
    return () => {
      cancelAnimationFrame(raf);
      window.document.removeEventListener('selectionchange', read);
      window.removeEventListener('pointerup', release);
    };
  }, [version.id]);

  const onPointerDown = (e: React.PointerEvent) => {
    onActivate?.();
    if ((e.target as Element).closest('.selection-popover')) return;
    if (e.button !== 0) return;
    dragging.current = true;
    if (placement) { setPlacement(null); callbacks.current.onSelection?.(null); }
  };
  const onClick = (e: React.MouseEvent) => {
    if (!callbacks.current.onPagePoint || !window.getSelection()?.isCollapsed) return;
    const pageElement = (e.target as Element).closest<HTMLElement>('.pdf-page');
    if (!pageElement || (e.target as Element).closest('.selection-popover')) return;
    const rect = pageElement.getBoundingClientRect();
    const [x, y] = unrotatePoint((e.clientX - rect.left) / rect.width, (e.clientY - rect.top) / rect.height, rotation);
    callbacks.current.onPagePoint(Number(pageElement.dataset.pageIndex), x, y);
  };

  const pageStatus = useCallback((index: number, value: PageStatus) => setStatus(s => (s[index] === value ? s : { ...s, [index]: value })), []);
  const pageSize = useCallback((index: number, width: number, height: number, measuredRotation: number) => {
    const reference = baseRef.current;
    // Ignore measurements from a previous rotation or before page 1 is known.
    if (!reference || reference.rotation !== measuredRotation) return;
    const same = (a: { width: number; height: number }) => Math.abs(a.width - width) < 0.5 && Math.abs(a.height - height) < 0.5;
    if (same(reference)) return;
    setOverrides(s => {
      if (s.rotation !== measuredRotation) return s;
      const known = s.sizes[index];
      if (known && same(known)) return s;
      return { rotation: s.rotation, sizes: { ...s.sizes, [index]: { width, height } } };
    });
  }, []);

  const box = highlight?.version_id === version.id && highlight.bbox?.length === 4 ? rotateBox(highlight.bbox, rotation) : null;
  const hover = hoverBox && hoverBox.bbox?.length === 4 ? rotateBox(hoverBox.bbox, rotation) : null;
  const currentStatus = status[pageIndex];
  const showPopover = Boolean(selectionPopover && placement);
  const pages: ReactNode[] = [];
  for (let i = 0; i < layout.tops.length; i++) {
    const active = i >= range[0] && i <= range[1];
    pages.push(<PdfPage key={i} pdf={pdf!} index={i} scale={scale} rotation={rotation} active={active}
      width={layout.widths[i]} height={layout.heights[i]} onStatus={pageStatus} onSize={pageSize}>
      {box && highlight!.page_index === i && <div className="evidence-highlight" data-testid="evidence-highlight" style={boxStyle(box)} />}
      {hover && hoverBox!.page_index === i && <div className="pdf-hover-box" style={boxStyle(hover)} />}
      {i === pageIndex && currentStatus !== 'ready' && currentStatus !== 'empty' && currentStatus !== 'error' && <div className="pdf-loading"><Busy>正在载入原文</Busy></div>}
    </PdfPage>);
  }
  return <div className="pdf-scroller" ref={scroller} onScroll={onScroll} onPointerDown={onPointerDown} onClick={onClick}
    onWheel={onActivate} onTouchStart={onActivate} onMouseEnter={onActivate} onFocus={onActivate}>
    {doc.error && doc.id === version.id && <ErrorBox error={doc.error} />}
    {(selectionError || currentStatus === 'empty') && <div className="pdf-notices">
      {selectionError && <p role="status" className="selection-notice">{selectionError}</p>}
      {currentStatus === 'empty' && <p role="status" className="selection-notice">此页没有可选择的文字（扫描页或图片）。切换到「中英对照」可查看识别出的文字。</p>}
    </div>}
    {!ready && !doc.error && <div className="pdf-pages"><div className="pdf-page pdf-sheet placeholder" style={{ width: Math.min(containerWidth - PAD * 2, 760), height: Math.min(containerWidth - PAD * 2, 760) * 1.3 }}>
      <div className="pdf-loading"><Busy>{doc.id === version.id && doc.progress !== undefined && doc.progress < 1
        ? `正在载入原文 ${Math.round(doc.progress * 100)}%`
        : '正在载入原文'}</Busy></div>
    </div></div>}
    {ready && <div className="pdf-pages" ref={pagesHost} style={{ height: layout.total, minWidth: layout.maxWidth + PAD * 2 }}>
      {pages.map((page, i) => <div className="pdf-page-slot" key={i} style={{ top: layout.tops[i], height: layout.heights[i] }}>{page}</div>)}
      {showPopover && <div className={`selection-popover ${placement!.above ? 'above' : ''}`}
        style={{ top: placement!.top, left: placement!.left, width: Math.min(POPOVER_WIDTH, containerWidth - 16) }}
        onMouseDown={e => e.preventDefault()}>{selectionPopover}</div>}
    </div>}
  </div>;
});

function boxStyle(box: number[]) {
  return { left: `${box[0] * 100}%`, top: `${box[1] * 100}%`, width: `${(box[2] - box[0]) * 100}%`, height: `${(box[3] - box[1]) * 100}%` };
}

function PdfPage({ pdf, index, scale, rotation, active, width, height, onStatus, onSize, children }: {
  pdf: PDFDocumentProxy; index: number; scale: number; rotation: number; active: boolean; width: number; height: number;
  onStatus: (index: number, status: PageStatus) => void; onSize: (index: number, width: number, height: number, rotation: number) => void; children?: ReactNode;
}) {
  const surface = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const root = surface.current;
    if (!root) return;
    if (!active) { root.replaceChildren(); return; }
    let disposed = false;
    let render: RenderTask | undefined;
    let textLayer: TextLayer | undefined;
    // Separate DOM surfaces ensure a cancelled render never shares a canvas
    // with its successor (including StrictMode's setup/cleanup/setup cycle).
    const canvas = window.document.createElement('canvas');
    const text = window.document.createElement('div');
    text.className = 'textLayer'; text.tabIndex = 0;
    text.setAttribute('aria-label', `第 ${index + 1} 页原文，可选择文字进行翻译、解释或提问`);
    canvas.setAttribute('aria-label', `第 ${index + 1} 页`);
    root.replaceChildren(canvas, text);
    onStatus(index, 'loading');
    void (async () => {
      const page = await pdf.getPage(index + 1);
      if (disposed) return;
      const angle = (page.rotate + rotation) % 360;
      const natural = page.getViewport({ scale: 1, rotation: angle });
      onSize(index, natural.width, natural.height, rotation);
      const viewport = page.getViewport({ scale, rotation: angle });
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.floor(viewport.width * ratio); canvas.height = Math.floor(viewport.height * ratio);
      canvas.style.width = `${viewport.width}px`; canvas.style.height = `${viewport.height}px`;
      text.style.setProperty('--scale-factor', String(viewport.scale));
      render = page.render({ canvasContext: canvas.getContext('2d')!, viewport, transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : undefined });
      const textPromise = (async () => {
        const content = await page.getTextContent();
        if (disposed) return false;
        const hasText = content.items.some(item => 'str' in item && item.str.trim());
        if (hasText) {
          textLayer = new TextLayer({ textContentSource: content, container: text, viewport });
          await textLayer.render();
        }
        return hasText;
      })();
      const [, hasText] = await Promise.all([render.promise, textPromise]);
      if (!disposed) onStatus(index, hasText ? 'ready' : 'empty');
    })().catch(e => {
      if (!disposed) { console.warn(`PDF page ${index + 1}: ${errorMessage(e)}`); onStatus(index, 'error'); }
    });
    return () => { disposed = true; render?.cancel(); textLayer?.cancel(); canvas.remove(); text.remove(); };
  }, [pdf, index, scale, rotation, active, onStatus, onSize]);
  return <div className="pdf-page pdf-sheet" data-page-index={index} style={{ width, height }}>
    <div ref={surface} className="pdf-page-surface" />
    {children}
  </div>;
}
