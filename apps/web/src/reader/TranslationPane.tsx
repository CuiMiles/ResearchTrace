import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react';
import type { PDFDocumentProxy } from 'pdfjs-dist';
import { api, errorMessage, parseObject } from '../api';
import type { Block, Page, Translation } from '../types';
import { Busy } from '../ui';
import { Languages, MessageSquare } from '../icons';
import { PdfCrop } from './PdfCrop';
import { MathText } from './MathText';
import type { ViewAnchor } from '../PdfReader';
import { startPolling } from '../app/poll';

export interface TranslationPaneHandle {
  scrollToAnchor: (page: number, y: number) => void;
  revealBlock: (blockId: string) => void;
  alignBlock: (page: number, blockId: string) => void;
}
type PageState = Block[] | 'loading' | 'error';

const HIDDEN_TYPES = new Set(['header', 'footer']);
const CROP_TYPES = new Set(['figure', 'table', 'equation', 'formula']);
const ESTIMATED_SECTION = 420;

interface Props {
  versionId: string;
  parseId?: string;
  pdf: PDFDocumentProxy | null;
  pageCount: number;
  initialPage: number;
  translations: Map<string, Translation>;
  targetLanguage: 'zh-Hans' | 'en';
  focusBlock: string | null;
  canTranslate: boolean;
  translatingPages: Set<number>;
  onTranslatePage: (page: number, blockIds: string[]) => void;
  onTranslateBlock: (block: Block) => void;
  onAskBlock: (block: Block) => void;
  onCitation: (block: Block, marker: string) => void;
  onHoverBlock: (block: Block | null) => void;
  onSelectBlock: (block: Block) => void;
  onViewport?: (anchor: ViewAnchor) => void;
  onActivate?: () => void;
}

/**
 * The right half of 中英对照: every original block of a page, in reading order,
 * aligned with its translation. Text blocks show the translation (or the
 * original, clearly muted, until translated); figures, tables and formulas are
 * crops of the real page so nothing is re-typeset.
 */
export const TranslationPane = forwardRef<TranslationPaneHandle, Props>(function TranslationPane(props, ref) {
  const { versionId, parseId, pdf, pageCount, initialPage, translations, targetLanguage, focusBlock, canTranslate, translatingPages } = props;
  const scroller = useRef<HTMLDivElement>(null);
  const sections = useRef<(HTMLElement | null)[]>([]);
  const [pages, setPages] = useState<Record<number, PageState>>({});
  const [blank, setBlank] = useState<Set<number>>(new Set());
  const requested = useRef(new Set<number>());
  const frame = useRef(0);
  const alignJob = useRef(0);
  const callbacks = useRef(props);
  callbacks.current = props;

  useEffect(() => { setPages({}); setBlank(new Set()); requested.current = new Set(); }, [versionId, parseId]);

  const load = useCallback((first: number, last: number) => {
    for (let i = Math.max(0, first); i <= Math.min(pageCount - 1, last); i++) {
      if (requested.current.has(i)) continue;
      requested.current.add(i);
      setPages(s => ({ ...s, [i]: 'loading' }));
      const query = parseId ? `?parse_id=${encodeURIComponent(parseId)}` : '';
      api<Page>(`/documents/${versionId}/pages/${i}${query}`)
        .then(page => {
          if (page.status === 'blank') setBlank(s => new Set(s).add(i));
          setPages(s => ({ ...s, [i]: (page.blocks ?? []).map(b => ({ ...b, metadata: parseObject(b.metadata, {}) })) }));
        })
        .catch(() => { requested.current.delete(i); setPages(s => ({ ...s, [i]: 'error' })); });
    }
  }, [versionId, parseId, pageCount]);

  const sectionAt = useCallback((position: number) => {
    const list = sections.current;
    let lo = 0, hi = Math.max(0, Math.min(pageCount, list.length) - 1);
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if ((list[mid]?.offsetTop ?? Infinity) <= position) lo = mid; else hi = mid - 1;
    }
    return lo;
  }, [pageCount]);

  const measure = useCallback((report: boolean) => {
    const el = scroller.current;
    if (!el || !pageCount) return;
    const top = el.scrollTop, height = el.clientHeight;
    load(sectionAt(top) - 1, sectionAt(top + height) + 2);
    if (!report) return;
    const line = top + height * 0.1;
    const page = sectionAt(line);
    const section = sections.current[page];
    if (!section) return;
    const y = Math.max(0, Math.min(1, (line - section.offsetTop) / Math.max(1, section.offsetHeight)));
    callbacks.current.onViewport?.({ page, y });
  }, [load, pageCount, sectionAt]);

  useEffect(() => {
    // Initial position next to the page currently open in the PDF.
    load(initialPage - 1, initialPage + 2);
    const section = sections.current[initialPage];
    if (section && scroller.current) scroller.current.scrollTop = section.offsetTop;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [versionId, parseId]);

  const scrollToAnchor = useCallback((page: number, y: number) => {
    const el = scroller.current;
    const section = sections.current[page];
    if (!el || !section) return;
    el.scrollTop = section.offsetTop + y * section.offsetHeight - el.clientHeight * 0.1;
    load(page - 1, page + 2);
  }, [load]);
  const revealBlock = useCallback((blockId: string) => {
    const el = scroller.current;
    const target = el?.querySelector<HTMLElement>(`[data-block="${CSS.escape(blockId)}"]`);
    if (!el || !target) return;
    const top = target.offsetTop;
    if (top < el.scrollTop + 40 || top + target.offsetHeight > el.scrollTop + el.clientHeight - 40) {
      el.scrollTop = Math.max(0, top - el.clientHeight * 0.25);
    }
  }, []);
  /** Put a block at the top of the pane, waiting for its page to load if needed. */
  const alignBlock = useCallback((page: number, blockId: string) => {
    const job = ++alignJob.current;
    load(page - 1, page + 2);
    let tries = 0;
    const run = () => {
      const el = scroller.current;
      if (!el || job !== alignJob.current) return;
      const target = el.querySelector<HTMLElement>(`[data-block="${CSS.escape(blockId)}"]`);
      if (target) { el.scrollTop = Math.max(0, target.offsetTop - el.clientHeight * 0.06); return; }
      if (!tries && sections.current[page]) el.scrollTop = sections.current[page].offsetTop;
      if (++tries < 50) window.setTimeout(run, 100);
    };
    run();
  }, [load]);
  useImperativeHandle(ref, () => ({ scrollToAnchor, revealBlock, alignBlock }), [scrollToAnchor, revealBlock, alignBlock]);
  useEffect(() => () => cancelAnimationFrame(frame.current), []);

  const onScroll = () => {
    cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(() => measure(true));
  };

  const totalTranslated = useMemo(() => {
    let n = 0;
    for (const value of Object.values(pages)) if (Array.isArray(value)) n += value.filter(b => translations.has(b.id)).length;
    return n;
  }, [pages, translations]);

  return <div className="translation-pane parallel-column translated" ref={scroller} onScroll={onScroll}
    onWheel={props.onActivate} onTouchStart={props.onActivate} onPointerDown={props.onActivate} onMouseEnter={props.onActivate} onFocus={props.onActivate}
    aria-label={targetLanguage === 'en' ? '英文译文' : '中文译文'} data-translated={totalTranslated}>
    {Array.from({ length: pageCount }, (_, i) => {
      const state = pages[i];
      const blocks = Array.isArray(state) ? state.filter(b => !HIDDEN_TYPES.has(b.type)) : [];
      const translatable = blocks.filter(b => !CROP_TYPES.has(b.type) && b.text.trim());
      const done = translatable.filter(b => translations.has(b.id)).length;
      const busy = translatingPages.has(i) || translatingPages.has(-1);
      return <section key={i} className="tp-page" data-page={i} ref={el => { sections.current[i] = el; }}
        style={Array.isArray(state) ? undefined : { minHeight: ESTIMATED_SECTION }}>
        <header className="tp-page-head">
          <span>第 {i + 1} 页</span>
          {Array.isArray(state) && translatable.length > 0 && <small>{done === translatable.length ? '已全部翻译' : `已译 ${done}/${translatable.length} 段`}</small>}
          {Array.isArray(state) && done < translatable.length && <button className="tp-translate" disabled={!canTranslate || busy}
            onClick={() => callbacks.current.onTranslatePage(i, translatable.filter(b => !translations.has(b.id)).map(b => b.id))}>
            {busy ? <Busy>翻译中</Busy> : <><Languages size={13} />翻译此页</>}
          </button>}
        </header>
        {state === 'loading' || state === undefined ? <div className="tp-loading tp-skeleton" aria-busy="true"><span className="sr-only">载入本页文字</span><i /><i /><i /><i /><i /></div>
          : state === 'error' ? <div className="tp-loading">载入失败</div>
          : !blocks.length ? <p className="tp-empty">{blank.has(i) ? '这一页已核验为空白页' : '无正文'}</p>
          : blocks.map(block => <PaneBlock key={block.id} block={block} pdf={pdf} translation={translations.get(block.id)}
            focused={block.id === focusBlock} canTranslate={canTranslate} busy={busy}
            onHover={callbacks.current.onHoverBlock} onSelect={callbacks.current.onSelectBlock}
            onTranslate={callbacks.current.onTranslateBlock} onAsk={callbacks.current.onAskBlock} onCitation={callbacks.current.onCitation} />)}
      </section>;
    })}
  </div>;
});

function PaneBlock({ block, pdf, translation, focused, canTranslate, busy, onHover, onSelect, onTranslate, onAsk, onCitation }: {
  block: Block; pdf: PDFDocumentProxy | null; translation?: Translation; focused: boolean; canTranslate: boolean; busy: boolean;
  onHover: (b: Block | null) => void; onSelect: (b: Block) => void; onTranslate: (b: Block) => void; onAsk: (b: Block) => void;
  onCitation: (b: Block, marker: string) => void;
}) {
  const crop = CROP_TYPES.has(block.type) && pdf && block.bbox?.length === 4;
  const markers = (parseObject<Record<string, unknown>>(block.metadata, {}).citation_markers as string[] | undefined) ?? [];
  const text = translation?.text;
  const kind = block.type === 'heading' ? 'heading' : block.type === 'caption' ? 'caption' : crop ? 'crop' : 'text';
  return <div className={`tp-block ${kind} ${text ? 'done' : 'pending'} ${focused ? 'focused' : ''}`} data-block={block.id}
    tabIndex={0} role="button" aria-label={`第 ${block.page_index + 1} 页段落，点击在原文中定位`}
    onMouseEnter={() => onHover(block)} onMouseLeave={() => onHover(null)}
    onClick={e => { if (!(e.target as Element).closest('button') && window.getSelection()?.isCollapsed !== false) onSelect(block); }}
    onKeyDown={e => { if (e.key === 'Enter' && e.target === e.currentTarget) onSelect(block); }}>
    {crop ? <PdfCrop pdf={pdf!} pageIndex={block.page_index} bbox={block.bbox} label={block.type === 'figure' ? '原文图' : block.type === 'table' ? '原文表格' : '原文公式'} />
      : <p lang={text ? undefined : 'en'}><MathText text={text ?? block.text} /></p>}
    {!crop && <div className="tp-tools">
      {!text && <span className="tp-tag">原文</span>}
      {markers.slice(0, 6).map((marker, i) => <button key={i} className="tp-cite" title="跳到参考文献" onClick={() => onCitation(block, marker)}>[{marker.replace(/[[\]]/g, '')}]</button>)}
      {!text && block.text.trim() && <button disabled={!canTranslate || busy} onClick={() => onTranslate(block)}>译此段</button>}
      <button onClick={() => onAsk(block)} aria-label="就此段提问"><MessageSquare size={12} />问此段</button>
    </div>}
  </div>;
}

export function usePageTranslationRuns(onDone: () => void) {
  const [runs, setRuns] = useState<{ id: string; pages: number[] }[]>([]);
  const [error, setError] = useState('');
  const done = useRef(onDone);
  done.current = onDone;
  useEffect(() => {
    if (!runs.length) return;
    let live = true;
    let tick = 0;
    const stop = startPolling(async () => {
      tick += 1;
      // Long (whole-paper) runs save page by page; show progress as it lands.
      if (tick % 3 === 0) done.current();
      for (const run of runs) {
        try {
          const state = await api<{ status: string; error?: string | null; result?: unknown }>(`/runs/${run.id}`);
          if (!live) return null;
          if (!['queued', 'running', 'waiting_children', 'waiting_batch'].includes(state.status)) {
            setRuns(list => list.filter(r => r.id !== run.id));
            if (state.status === 'failed') setError(state.error || '翻译失败');
            // Some paragraphs failed the formula/number/citation check and were not saved.
            if (state.status === 'partial') setError(parseObject<{ reason?: string }>(state.result, {}).reason || '部分未翻译');
            done.current();
          }
        } catch (e) { if (live) setError(errorMessage(e)); }
      }
      return 1500;
    }, 1500);
    return () => { live = false; stop(); };
  }, [runs]);
  const pages = useMemo(() => new Set(runs.flatMap(r => r.pages)), [runs]);
  return { pages, track: (id: string, list: number[]) => setRuns(r => [...r, { id, pages: list }]), error, clearError: () => setError(''), active: runs.length > 0 };
}
