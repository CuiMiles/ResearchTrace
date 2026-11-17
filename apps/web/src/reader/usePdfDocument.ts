import { useEffect, useState } from 'react';
import { getDocument, GlobalWorkerOptions, PDFWorker, type PDFDocumentProxy } from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import { endpoint, errorMessage } from '../api';

GlobalWorkerOptions.workerSrc = workerUrl;

export interface PdfDocumentState {
  id: string;
  pdf: PDFDocumentProxy | null;
  error: string;
  loading: boolean;
  /** Share of the file received so far (0..1), when the size is known. */
  progress?: number;
}

const MAX_BYTES = 50 * 1024 * 1024;

/**
 * Loads one version's original PDF once and shares it between the page viewer
 * and the bilingual pane (figure/table/formula crops come from the same file).
 */
export function usePdfDocument(versionId: string): PdfDocumentState {
  const [state, setState] = useState<PdfDocumentState>({ id: versionId, pdf: null, error: '', loading: true });
  useEffect(() => {
    let live = true;
    let task: ReturnType<typeof getDocument> | undefined;
    const abort = new AbortController();
    // Start the worker now so its script downloads alongside the PDF instead of
    // after it; on a slow link that is the difference between one wait and two.
    // An explicitly passed worker is ours to destroy (PDF.js leaves it alone).
    const worker = new PDFWorker();
    // Destroying a worker that is still starting rejects its own ready promise;
    // that is our cancellation, not a failure (getDocument observes it otherwise).
    worker.promise.catch(() => {});
    setState({ id: versionId, pdf: null, error: '', loading: true });
    // Fetch under our AbortController before handing owned bytes to PDF.js.
    // This avoids v4's outstanding network-reader/worker teardown race during
    // rapid navigation, without swallowing unrelated global promise failures.
    void (async () => {
      const response = await fetch(endpoint(`/documents/${versionId}/file`), { credentials: 'same-origin', signal: abort.signal });
      if (!response.ok) throw new Error(`原文载入失败（${response.status}）`);
      const data = await readWithProgress(response, fraction => {
        if (live) setState(previous => (previous.id === versionId && previous.loading ? { ...previous, progress: fraction } : previous));
      });
      if (!live) return;
      task = getDocument({ data, worker, isEvalSupported: false });
      const pdf = await task.promise;
      if (live) setState({ id: versionId, pdf, error: '', loading: false });
    })().catch(e => {
      if (live) setState({ id: versionId, pdf: null, error: errorMessage(e), loading: false });
    });
    return () => {
      live = false;
      abort.abort();
      // Both task.promise (above) and destroy() are observed. Never suppress
      // window-level errors; only cancellation of this owned resource is quiet.
      const loading = task;
      void (loading ? loading.destroy() : Promise.resolve())
        .catch(() => {})
        .finally(() => worker.destroy());
    };
  }, [versionId]);
  return state;
}

/** Reads the body in chunks so the reader can show how much has arrived. */
async function readWithProgress(response: Response, onProgress: (fraction: number) => void): Promise<ArrayBuffer> {
  const declared = Number(response.headers.get('content-length') || 0);
  if (declared > MAX_BYTES) throw new Error('原文超过阅读器的 50 MiB 文件限制');
  if (!response.body || !declared) {
    const whole = await response.arrayBuffer();
    if (whole.byteLength > MAX_BYTES) throw new Error('原文超过阅读器的 50 MiB 文件限制');
    return whole;
  }
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let received = 0;
  let reported = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    received += value.byteLength;
    if (received > MAX_BYTES) {
      void reader.cancel();
      throw new Error('原文超过阅读器的 50 MiB 文件限制');
    }
    chunks.push(value);
    const fraction = Math.min(1, received / declared);
    if (fraction - reported >= 0.02 || fraction === 1) {
      reported = fraction;
      onProgress(fraction);
    }
  }
  const bytes = new Uint8Array(received);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return bytes.buffer;
}
