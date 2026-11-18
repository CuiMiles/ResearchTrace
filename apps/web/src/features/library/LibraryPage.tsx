/**
 * Library: every imported version with parse and index coverage, batch
 * import progress, multi-select actions and the document card drawer.
 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  BookOpen,
  ChevronDown,
  FileText,
  GitCompareArrows,
  ListTree,
  MessagesSquare,
  Search,
  UploadCloud,
  X,
} from '../../icons';
import { api, date, errorMessage } from '../../api';
import { useWorkspace } from '../../app/workspace';
import { DocumentCard } from '../../components/DocumentCard';
import type { Version } from '../../types';
import { Badge, Empty } from '../../ui';
import { UploadBatchPanel } from '../../UploadBatchPanel';

export function LibraryPage() {
  const ws = useWorkspace();
  const navigate = useNavigate();
  const [filter, setFilter] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [cardFor, setCardFor] = useState<Version | null>(null);
  const [hiddenBatch, setHiddenBatch] = useState<string | null>(() => {
    try {
      return localStorage.getItem('rt-hidden-batch');
    } catch {
      return null;
    }
  });
  const needle = filter.trim().toLowerCase();
  const shown = ws.versions.filter(
    (v) => !needle || [v.title, v.filename, v.label, JSON.stringify(v.metadata)].join(' ').toLowerCase().includes(needle),
  );
  const toggle = (id: string) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));

  return (
    <div className="page-content">
      <div className="page-heading">
        <div>
          <h1>文献库</h1>
          
        </div>
        <button className="primary-button" disabled={ws.uploading} onClick={ws.openUpload}>
          <UploadCloud size={16} />
          导入 PDF
        </button>
      </div>

      {ws.batchId && ws.batchId !== hiddenBatch && (
        <div className="batch-panel-wrap">
          <button
            className="icon-button batch-dismiss"
            aria-label="收起导入记录"
            title="收起导入记录"
            onClick={() => {
              setHiddenBatch(ws.batchId);
              try {
                localStorage.setItem('rt-hidden-batch', ws.batchId ?? '');
              } catch {
                /* per-viewer convenience only */
              }
            }}
          >
            <X size={15} />
          </button>
          <UploadBatchPanel batchId={ws.batchId} />
        </div>
      )}

      <div className="library-toolbar">
        <label className="search-field">
          <Search size={15} />
          <input
            aria-label="筛选文献"
            placeholder="筛选"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </label>
        <span className="muted" style={{ fontSize: 13 }}>
          {shown.length} / {ws.versions.length} 篇
        </span>
      </div>

      {selected.length > 0 && (
        <div className="selection-bar">
          <span>已选 {selected.length} 篇</span>
          <button
            className="small-button"
            onClick={() => navigate('/chat', { state: { versionIds: selected } })}
          >
            <MessagesSquare size={13} />
            提问
          </button>
          <button className="small-button" onClick={() => navigate('/compare')}>
            <GitCompareArrows size={13} />
            比较
          </button>
          <button className="icon-button" aria-label="清除选择" onClick={() => setSelected([])}>
            <X size={15} />
          </button>
        </div>
      )}

      {!ws.versions.length ? (
        <button className="upload-empty" style={{ width: '100%' }} onClick={ws.openUpload}>
          <UploadCloud size={36} strokeWidth={1.25} />
          <h3>导入论文</h3>
          
          
        </button>
      ) : !shown.length ? (
        <Empty title="没有匹配"></Empty>
      ) : (
        <div className="card document-table">
          <div className="document-table-head">
            <span />
            <span>文献</span>
            <span>状态</span>
            <span>时间</span>
            <span />
          </div>
          {shown.map((v) => (
            <DocumentRow
              key={v.id}
              version={v}
              checked={selected.includes(v.id)}
              onToggle={() => toggle(v.id)}
              onOpen={() => ws.openDocument(v.id)}
              onCard={() => setCardFor(v)}
            />
          ))}
        </div>
      )}

      {cardFor && (
        <div className="drawer-backdrop" onClick={() => setCardFor(null)}>
          <aside className="side-drawer wide" onClick={(e) => e.stopPropagation()} aria-label="论文概览">
            <div className="section-heading">
              <h2>
                <ListTree size={17} />
                论文概览
              </h2>
              <div className="run-actions">
                <button className="small-button" onClick={() => ws.openDocument(cardFor.id)}>
                  <BookOpen size={13} />
                  打开阅读
                </button>
                <button className="icon-button" aria-label="关闭" onClick={() => setCardFor(null)}>
                  <X size={17} />
                </button>
              </div>
            </div>
            <DocumentCard versionId={cardFor.id} onEvidence={(e) => void ws.openEvidence(e)} />
          </aside>
        </div>
      )}
    </div>
  );
}

function DocumentRow({
  version: v,
  checked,
  onToggle,
  onOpen,
  onCard,
}: {
  version: Version;
  checked: boolean;
  onToggle: () => void;
  onOpen: () => void;
  onCard: () => void;
}) {
  const progress = v.page_count ? Math.round((v.parsed_pages / v.page_count) * 100) : 0;
  const parsing = !v.page_count || v.parsed_pages < v.page_count;
  const notice = v.metadata.version_notice ? String(v.metadata.version_notice) : '';
  const year = v.metadata.year ? String(v.metadata.year) : '';
  return (
    <article className="document-row">
      <input type="checkbox" aria-label={`选择 ${v.title}`} checked={checked} onChange={onToggle} />
      <button className="document-title" onClick={onOpen}>
        <div className="pdf-icon">
          <FileText size={20} />
        </div>
        <div>
          <strong>{v.title}</strong>
          <small>
            <Badge>{v.label}</Badge>
            {year && <span>{year}</span>}
            <span className="truncate">{v.filename}</span>
          </small>
          {notice && <em>{notice}</em>}
        </div>
      </button>
      <div className="document-status">
        <Badge status={v.status} />
        {parsing ? (
          <>
            <div className="progress-line" aria-label={`解析 ${progress}%`}>
              <i style={{ width: `${progress}%` }} />
            </div>
            <span>
              正在解析 {v.parsed_pages}/{v.page_count || '?'} 页
            </span>
          </>
        ) : (
          v.page_count > 0 && <span>{v.page_count} 页</span>
        )}
      </div>
      <time>{date(v.created)}</time>
      <div className="document-actions">
        <button className="small-button" onClick={onCard} disabled={v.status !== 'ready'}>
          概览
        </button>
        <DocumentMenu version={v} />
      </div>
    </article>
  );
}

function DocumentMenu({ version }: { version: Version }) {
  const ws = useWorkspace();
  const [open, setOpen] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [title, setTitle] = useState(version.title);
  const [confirm, setConfirm] = useState(false);
  async function rename() {
    try {
      await api(`/documents/${version.id}`, { title }, 'PATCH');
      setRenaming(false);
      setOpen(false);
      await ws.refresh();
    } catch (e) {
      ws.setError(errorMessage(e));
    }
  }
  async function remove() {
    try {
      await api(`/documents/${version.id}`, undefined, 'DELETE');
      setOpen(false);
      await ws.refresh();
    } catch (e) {
      ws.setError(errorMessage(e));
    }
  }
  return (
    <div className="document-menu">
      <button
        className="icon-button"
        aria-label={`管理文献：${version.title}`}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <ChevronDown size={16} />
      </button>
      {open && (
        <div className="popover">
          <button onClick={() => ws.openDocument(version.id)}>打开阅读</button>
          {renaming ? (
            <>
              <input aria-label="文献新标题" value={title} onChange={(e) => setTitle(e.target.value)} />
              <button onClick={() => void rename()}>保存标题</button>
            </>
          ) : (
            <button onClick={() => setRenaming(true)}>重命名</button>
          )}
          {confirm ? (
            <>
              <p>不再参与检索</p>
              <button className="danger-text" onClick={() => void remove()}>
                确认删除
              </button>
              <button onClick={() => setConfirm(false)}>保留</button>
            </>
          ) : (
            <button className="danger-text" onClick={() => setConfirm(true)}>
              删除此版本
            </button>
          )}
        </div>
      )}
    </div>
  );
}
