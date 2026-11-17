/**
 * Workspace state shared by every page: the session, model capability, the
 * document list, recent runs, uploads and evidence navigation.
 *
 * Server data is polled while the tab is visible; nothing here is cached
 * across workspaces, and every request goes through the authenticated API.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, errorMessage, parseObject } from '../api';
import type { ModelCapability } from '../ModelConfig';
import type { Block, Evidence, Run, Session, Version } from '../types';
import { VersionChoice } from '../components/VersionChoice';
import { activeRun } from '../RunPanel';
import { startPolling, type Poller } from './poll';

interface UploadResult {
  documents: Version[];
  runs: { id: string }[];
  batch_id?: string;
}

export interface Workspace {
  session: Session;
  capability: ModelCapability | null;
  versions: Version[];
  runs: Run[];
  loaded: boolean;
  batchId: string | null;
  uploading: boolean;
  highlight: Evidence | null;
  error: string;
  notice: string;
  setError: (message: string) => void;
  setNotice: (message: string) => void;
  refresh: () => Promise<void>;
  upload: (files: FileList | File[] | null) => Promise<UploadResult | null>;
  openUpload: () => void;
  openEvidence: (evidence: Evidence) => Promise<void>;
  openDocument: (versionId: string) => void;
  logout: () => Promise<void>;
}

const WorkspaceContext = createContext<Workspace | null>(null);

export function useWorkspace(): Workspace {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error('useWorkspace must be used inside WorkspaceProvider');
  return value;
}

export function WorkspaceProvider({
  session,
  onLogout,
  children,
}: {
  session: Session;
  onLogout: () => void;
  children: ReactNode;
}) {
  const navigate = useNavigate();
  const [capability, setCapability] = useState<ModelCapability | null>(null);
  const [versions, setVersions] = useState<Version[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [batchId, setBatchId] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [highlight, setHighlight] = useState<Evidence | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const fileInput = useRef<HTMLInputElement>(null);
  const choiceStorage = `rt-version-choices:${session.workspace}`;
  const [versionChoiceIds, setVersionChoiceIds] = useState<string[]>(() => {
    try {
      const saved: unknown = JSON.parse(sessionStorage.getItem(choiceStorage) || '[]');
      return Array.isArray(saved) ? saved.filter((id): id is string => typeof id === 'string').slice(-100) : [];
    } catch { return []; }
  });
  useEffect(() => {
    try { sessionStorage.setItem(choiceStorage, JSON.stringify(versionChoiceIds)); } catch { /* optional UI persistence */ }
  }, [choiceStorage, versionChoiceIds]);
  const dismissVersionChoice = useCallback((id: string) => {
    setVersionChoiceIds((current) => current.filter((candidate) => candidate !== id));
  }, []);

  // Returns whether anything is still running, so the poller can pick its pace.
  const load = useCallback(async (): Promise<boolean> => {
    try {
      const [docs, recent, batches] = await Promise.all([
        api<Version[]>('/documents'),
        api<Run[]>('/runs?summary=true'),
        api<{ id: string }[]>('/batches'),
      ]);
      setBatchId((current) => current ?? batches[0]?.id ?? null);
      setVersions(docs.map((d) => ({ ...d, metadata: parseObject(d.metadata, {}) })));
      setRuns(
        recent.map((r) => ({
          ...r,
          payload: parseObject(r.payload, {}),
          result: parseObject(r.result, null),
        })),
      );
      setLoaded(true);
      return recent.some(activeRun) || docs.some((d) => d.status === 'queued' || d.status === 'parsing');
    } catch (e) {
      setError(errorMessage(e));
      return false;
    }
  }, []);
  const poller = useRef<Poller | null>(null);
  const refresh = useCallback(async () => { if (await load()) poller.current?.soon(4000); }, [load]);

  useEffect(() => {
    void api<ModelCapability>('/capabilities')
      .then(setCapability)
      .catch((e) => setError(errorMessage(e)));
    // Fast while something is running, slow when idle; never overlapping.
    const stop = startPolling(async () => ((await load()) ? 4000 : 20000));
    poller.current = stop;
    return () => { poller.current = null; stop(); };
  }, [session.workspace, load]);

  const upload = useCallback(
    async (files: FileList | File[] | null) => {
      if (!files?.length) return null;
      setUploading(true);
      setError('');
      const form = new FormData();
      Array.from(files).forEach((f) => form.append('files', f));
      try {
        const result = await api<UploadResult>('/documents', form);
        if (result.batch_id) setBatchId(result.batch_id);
        setVersionChoiceIds((current) => Array.from(new Set([...current,
          ...result.documents.filter((document) => !document.duplicate).map((document) => document.id)])));
        await refresh();
        const first = result.documents[0];
        if (first && files.length === 1 && !result.batch_id) {
          setNotice(
            first.duplicate
              ? '内容相同的文件已在库中，已打开已有版本。'
              : 'PDF 已保存，正在逐页解析；现在就可以阅读原文。',
          );
        }
        return result;
      } catch (e) {
        setError(errorMessage(e));
        return null;
      } finally {
        setUploading(false);
        if (fileInput.current) fileInput.current.value = '';
      }
    },
    [refresh],
  );

  const openDocument = useCallback(
    (versionId: string) => {
      setHighlight(null);
      navigate(`/read/${versionId}`);
    },
    [navigate],
  );

  const openEvidence = useCallback(
    async (evidence: Evidence) => {
      let target = evidence;
      // Older answers may lack a box; look the block up in its own snapshot.
      if (!target.bbox || target.bbox.length !== 4) {
        try {
          const query = target.parse_id ? `?parse_id=${encodeURIComponent(target.parse_id)}` : '';
          const page = await api<{ blocks: Block[] }>(
            `/documents/${target.version_id}/pages/${target.page_index}${query}`,
          );
          const block = page.blocks.find((b) => b.id === target.block_id);
          if (block) {
            target = {
              ...target,
              bbox: parseObject(block.bbox, []),
              parse_id: block.parse_id ?? target.parse_id,
            };
          }
        } catch (e) {
          setError(errorMessage(e));
        }
      }
      setHighlight(target);
      navigate(`/read/${target.version_id}`);
    },
    [navigate],
  );

  const logout = useCallback(async () => {
    try {
      await api('/auth/logout', {});
    } finally {
      onLogout();
    }
  }, [onLogout]);

  const value = useMemo<Workspace>(
    () => ({
      session,
      capability,
      versions,
      runs,
      loaded,
      batchId,
      uploading,
      highlight,
      error,
      notice,
      setError,
      setNotice,
      refresh,
      upload,
      openUpload: () => fileInput.current?.click(),
      openEvidence,
      openDocument,
      logout,
    }),
    [session, capability, versions, runs, loaded, batchId, uploading, highlight, error, notice,
      refresh, upload, openEvidence, openDocument, logout],
  );

  return (
    <WorkspaceContext.Provider value={value}>
      <input
        type="file"
        accept="application/pdf,.pdf"
        multiple
        hidden
        ref={fileInput}
        data-testid="pdf-upload"
        onChange={(e) => void upload(e.target.files)}
      />
      {children}
      <VersionChoice pendingIds={versionChoiceIds} versions={versions}
        onDismiss={dismissVersionChoice} onResolved={refresh} />
    </WorkspaceContext.Provider>
  );
}
