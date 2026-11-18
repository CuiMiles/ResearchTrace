/**
 * Parse results of one document: title, ordered authors with affiliations,
 * dates, abstract, structure and asset counts. Every field shows its source;
 * author entries link back to the title-page block they came from.
 */
import { useEffect, useState } from 'react';
import { ExternalLink, RefreshCw } from '../icons';
import { api, errorMessage, key } from '../api';
import type { Evidence } from '../types';
import { Badge, Busy, Empty, ErrorBox } from '../ui';

interface Author {
  position: number;
  name: string;
  affiliations: string[];
  emails?: string[];
  source: string;
  block_id?: string | null;
}
interface OutlineEntry {
  title: string;
  level: number;
  page_index: number;
  block_id?: string | null;
}
interface Field<T> {
  value: T;
  source: string;
  block_id?: string | null;
}
export interface DocumentCardData {
  status: 'ready' | 'missing';
  version_id: string;
  parse_id?: string;
  title?: Field<string>;
  authors?: Author[];
  year?: Field<number>;
  first_submitted?: Field<string>;
  venue?: Field<string>;
  doi?: string;
  abstract?: { text: string; source: string; block_ids: string[] };
  outline?: OutlineEntry[];
  appendix_start_page?: number | null;
  assets?: Record<string, number>;
  code_links?: string[];
  notes?: string[];
  author_extraction?: { model: string; dropped_unverified: string[] };
}

const SOURCE: Record<string, string> = {
  arxiv_api: 'arXiv 记录',
  crossref_api: 'Crossref 记录',
  pdf_metadata: 'PDF 元数据',
  pdf_layout: '首页版面',
  pdf_title_page: '首页原文',
  'arxiv+pdf_title_page': 'arXiv 顺序 + 首页单位',
  arxiv: 'arXiv 记录',
  arxiv_identifier: 'arXiv 编号',
  arxiv_first_submission: 'arXiv 首次提交',
  pdf_venue_line: '首页会议信息',
  pdf_first_page: '首页',
  pdf_abstract_section: '摘要原文',
  crossref_issued: 'Crossref',
  filename_or_previous: '文件名',
};

const ASSETS: [string, string][] = [
  ['headings', '标题'],
  ['tables', '表格'],
  ['figures', '图'],
  ['equations', '公式'],
  ['captions', '图表说明'],
  ['references', '参考文献'],
];

export function DocumentCard({
  versionId,
  onEvidence,
}: {
  versionId: string;
  onEvidence?: (e: Evidence) => void;
}) {
  const [card, setCard] = useState<DocumentCardData | null>(null);
  const [error, setError] = useState('');
  const [building, setBuilding] = useState(false);

  async function load() {
    try {
      setCard(await api<DocumentCardData>(`/documents/${versionId}/card`));
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  useEffect(() => {
    setCard(null);
    void load();
  }, [versionId]);

  async function rebuild() {
    setBuilding(true);
    setError('');
    try {
      const run = await api<{ id: string }>(`/documents/${versionId}/card`, { idempotency_key: key() });
      for (let i = 0; i < 60; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        const state = await api<{ status: string; error?: string }>(`/runs/${run.id}`);
        if (!['queued', 'running'].includes(state.status)) {
          if (state.error) setError(state.error);
          break;
        }
      }
      await load();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBuilding(false);
    }
  }

  const locate = (blockId: string | null | undefined, page = 0, quote = '') =>
    blockId && onEvidence
      ? onEvidence({ block_id: blockId, version_id: versionId, page_index: page, bbox: [], quote, status: '文献卡片字段来源' })
      : undefined;

  if (error && !card) return <ErrorBox error={error} />;
  if (!card) return <Busy>载入解析结果</Busy>;
  if (card.status === 'missing') {
    return (
      <Empty title="还没有文献卡片">
        
        <button className="primary-button" disabled={building} onClick={() => void rebuild()}>
          {building ? <Busy>生成中</Busy> : '生成文献卡片'}
        </button>
      </Empty>
    );
  }
  return (
    <div className="doc-card">
      {error && <ErrorBox error={error} onClose={() => setError('')} />}
      <div>
        <h2 className="doc-card-title">{card.title?.value}</h2>
        <div className="doc-card-meta" style={{ marginTop: 8 }}>
          {card.year && <Badge>{card.year.value}</Badge>}
          {card.venue && <Badge>{card.venue.value}</Badge>}
          {card.first_submitted && <Badge>首次提交 {card.first_submitted.value}</Badge>}
          {card.doi && <Badge>DOI {card.doi}</Badge>}
          <span className="source-tag">标题来源：{SOURCE[card.title?.source ?? ''] ?? card.title?.source}</span>
        </div>
      </div>

      <section>
        <h3>作者（按论文顺序）</h3>
        {card.authors?.length ? (
          <ol className="author-list">
            {card.authors.map((author) => (
              <li key={author.position}>
                <b>{author.position}</b>
                <div>
                  <strong>{author.name}</strong>
                  <small>{author.affiliations.length ? author.affiliations.join('；') : '首页未标注单位'}</small>
                  {author.emails?.length ? <small>{author.emails.join('，')}</small> : null}
                  <span className="source-tag">
                    {SOURCE[author.source] ?? author.source}
                    {author.block_id && onEvidence && (
                      <button className="text-button" style={{ fontSize: 11 }} onClick={() => locate(author.block_id, 0, author.name)}>
                        <ExternalLink size={11} />
                        原文
                      </button>
                    )}
                  </span>
                </div>
              </li>
            ))}
          </ol>
        ) : (
          <p className="muted">未能可靠识别作者。</p>
        )}
        {card.author_extraction?.dropped_unverified?.length ? (
          <p className="muted" style={{ fontSize: 12, marginTop: 6 }}>
            模型给出但原文中找不到、因此未采用的内容：{card.author_extraction.dropped_unverified.slice(0, 6).join('；')}
          </p>
        ) : null}
      </section>

      {card.abstract && (
        <section>
          <h3>摘要</h3>
          <p className="abstract-text">{card.abstract.text}</p>
        </section>
      )}

      {card.assets && (
        <section>
          <h3>结构化解析</h3>
          <div className="asset-grid">
            {ASSETS.map(([field, label]) => (
              <div key={field}>
                <b>{card.assets?.[field] ?? 0}</b>
                <span>{label}</span>
              </div>
            ))}
            <div>
              <b>{card.outline?.length ?? 0}</b>
              <span>目录条目</span>
            </div>
            <div>
              <b>{card.appendix_start_page != null ? `p.${card.appendix_start_page + 1}` : '—'}</b>
              <span>附录起始</span>
            </div>
          </div>
        </section>
      )}

      {card.code_links?.length ? (
        <section>
          <h3>代码线索</h3>
          {card.code_links.map((link) => (
            <a key={link} href={link} target="_blank" rel="noopener noreferrer">
              {link}
            </a>
          ))}
        </section>
      ) : null}

      <div className="export-row">
        <button className="small-button" disabled={building} onClick={() => void rebuild()}>
          {building ? <Busy>重新生成中</Busy> : <><RefreshCw size={13} />重新生成卡片</>}
        </button>
        {card.notes?.map((note) => (
          <span className="muted" style={{ fontSize: 12 }} key={note}>
            {note}
          </span>
        ))}
      </div>
    </div>
  );
}
