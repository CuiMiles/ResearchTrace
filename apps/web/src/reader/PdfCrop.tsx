import { useEffect, useRef, useState } from 'react';
import type { PDFDocumentProxy } from 'pdfjs-dist';

/*
 * Figures, tables and formulas are shown in the bilingual pane as crops of the
 * original page, so their layout is never re-flowed or re-typeset. One page
 * raster is shared by every crop on that page; a small LRU bounds memory even
 * for the 541-page book.
 */
const RASTER_SCALE = 2;
const LRU_LIMIT = 4;
const rasters = new Map<string, Promise<HTMLCanvasElement>>();
const owners = new WeakMap<PDFDocumentProxy, string>();
let ownerSeq = 0;

function docKey(pdf: PDFDocumentProxy) {
  let key = owners.get(pdf);
  if (!key) { key = `doc${++ownerSeq}`; owners.set(pdf, key); }
  return key;
}

function pageRaster(pdf: PDFDocumentProxy, pageIndex: number) {
  const key = `${docKey(pdf)}:${pageIndex}`;
  const hit = rasters.get(key);
  if (hit) {
    rasters.delete(key); rasters.set(key, hit); // refresh LRU position
    return hit;
  }
  const job = (async () => {
    const page = await pdf.getPage(pageIndex + 1);
    const viewport = page.getViewport({ scale: RASTER_SCALE });
    const canvas = document.createElement('canvas');
    canvas.width = Math.floor(viewport.width);
    canvas.height = Math.floor(viewport.height);
    await page.render({ canvasContext: canvas.getContext('2d')!, viewport }).promise;
    return canvas;
  })();
  job.catch(() => rasters.delete(key));
  rasters.set(key, job);
  while (rasters.size > LRU_LIMIT) rasters.delete(rasters.keys().next().value!);
  return job;
}

export function PdfCrop({ pdf, pageIndex, bbox, label }: {
  pdf: PDFDocumentProxy; pageIndex: number; bbox: number[]; label: string;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'failed'>('loading');
  const box = bbox.join(',');
  useEffect(() => {
    let live = true;
    setState('loading');
    pageRaster(pdf, pageIndex).then(source => {
      const target = canvas.current;
      if (!live || !target) return;
      const pad = 0.006;
      const [x0, y0, x1, y1] = bbox.map(Number);
      const left = Math.max(0, Math.min(x0, x1) - pad) * source.width;
      const top = Math.max(0, Math.min(y0, y1) - pad) * source.height;
      const right = Math.min(1, Math.max(x0, x1) + pad) * source.width;
      const bottom = Math.min(1, Math.max(y0, y1) + pad) * source.height;
      const width = Math.max(1, Math.round(right - left));
      const height = Math.max(1, Math.round(bottom - top));
      target.width = width; target.height = height;
      target.style.width = `${Math.round(width / RASTER_SCALE * 1.15)}px`;
      target.getContext('2d')!.drawImage(source, left, top, width, height, 0, 0, width, height);
      setState('ready');
    }).catch(() => { if (live) setState('failed'); });
    return () => { live = false; };
    // bbox identity changes on every render; its joined value is the real input.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pdf, pageIndex, box]);
  return <span className={`pdf-crop ${state}`}>
    <canvas ref={canvas} role="img" aria-label={label} />
    {state === 'failed' && <small>原文区域无法显示，请在左侧原文中查看</small>}
  </span>;
}
