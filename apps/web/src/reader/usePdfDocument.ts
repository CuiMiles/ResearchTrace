import { useEffect, useState } from 'react';
import { getDocument, GlobalWorkerOptions, type PDFDocumentProxy } from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import { endpoint, errorMessage } from '../api';

GlobalWorkerOptions.workerSrc = workerUrl;

export interface PdfDocumentState {
  id: string;
  pdf: PDFDocumentProxy | null;
  error: string;
  loading: boolean;
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
    setState({ id: versionId, pdf: null, error: '', loading: true });
    // Fetch under our AbortController before handing owned bytes to PDF.js.
    // This avoids v4's outstanding network-reader/worker teardown race during
    // rapid navigation, without swallowing unrelated global promise failures.
    void (async () => {
      const response = await fetch(endpoint(`/documents/${versionId}/file`), { credentials: 'same-origin', signal: abort.signal });
      if (!response.ok) throw new Error(`原文载入失败（${response.status}）`);
      const data = await response.arrayBuffer();
      if (!live) return;
      if (data.byteLength > MAX_BYTES) throw new Error('原文超过阅读器的 50 MiB 文件限制');
      task = getDocument({ data, isEvalSupported: false });
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
      if (task) void task.destroy().catch(() => {});
    };
  }, [versionId]);
  return state;
}
