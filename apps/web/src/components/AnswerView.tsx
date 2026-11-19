/**
 * Renders a validated answer the way a chat reply reads: the answer prose first,
 * with small numbered citations after each checked claim. Everything else —
 * per-claim review, the numbered sources, the public execution record and the
 * exports — stays folded behind a row of icon buttons under the answer.
 *
 * The prose is exactly the validated claim text (the server already replaced
 * any free model prose with the claims); this view never rewrites it.
 */
import { Fragment, useMemo, useState, type ReactNode } from 'react';
import { Check, Copy, ExternalLink, FileDown, Quote, ShieldCheck, TriangleAlert, Workflow, X } from '../icons';
import { date, endpoint, parseObject } from '../api';
import type { Claim, Evidence, Result, Run } from '../types';
import { ErrorBox, Markdown } from '../ui';

type State = 'supported' | 'review' | 'contradicted' | 'insufficient';
type Panel = 'checks' | 'sources' | 'process' | 'export' | null;

const STATE_LABEL: Record<State, string> = {
  supported: '已核对支持',
  review: '已定位，待复核',
  contradicted: '与原文矛盾',
  insufficient: '证据不足',
};

const REVIEWER: Record<string, string> = {
  gemini_decision_1: 'Decision 1 复核',
  independent_model_critic: '模型复核',
  literal_source_quote: '逐字原文',
  location_and_numeric_rules_only: '位置与数值规则',
};

const KIND_LABEL: Record<string, string> = {
  inference: '推断',
  suggestion: '建议',
  research_suggestion: '建议',
  calculation: '计算',
};

export function claimState(claim: Claim): State {
  if (claim.type === 'insufficient' || claim.type === 'insufficient_evidence') return 'insufficient';
  const status = claim.review?.status;
  if (status === 'supported') return 'supported';
  if (status === 'contradicted') return 'contradicted';
  if (status === 'insufficient') return 'insufficient';
  return 'review';
}

interface Source {
  n: number;
  evidence: Evidence;
}

/** One number per distinct quoted passage, in reading order. */
function numberSources(claims: Claim[]) {
  const sources: Source[] = [];
  const byKey = new Map<string, number>();
  const perClaim = claims.map((claim) =>
    (claim.evidence ?? []).map((evidence) => {
      const k = `${evidence.version_id}|${evidence.block_id}|${evidence.quote}`;
      let n = byKey.get(k);
      if (n === undefined) {
        n = sources.length + 1;
        byKey.set(k, n);
        sources.push({ n, evidence });
      }
      return n;
    }),
  );
  return { sources, perClaim };
}

interface Section {
  key: string;
  title?: string;
  paragraphs: number[][];
}

/** Paragraphs of claim indexes: from sections, then answer segments, else one claim each. */
function layout(result: Result, claims: Claim[]): Section[] {
  const index = new Map(claims.map((c, i) => [c.id ?? String(i), i]));
  const pick = (ids: string[]) => ids.map((id) => index.get(id)).filter((i): i is number => i !== undefined);
  const used = new Set<number>();
  const take = (ids: string[]) => {
    const list = pick(ids).filter((i) => !used.has(i));
    list.forEach((i) => used.add(i));
    return list;
  };
  const sections = Array.isArray(result.sections)
    ? (result.sections as { key?: string; title?: string; claim_ids?: string[] }[])
    : [];
  const out: Section[] = [];
  if (sections.length) {
    sections.forEach((s, k) => {
      const ids = take(s.claim_ids ?? []);
      if (ids.length) out.push({ key: s.key ?? String(k), title: s.title, paragraphs: ids.map((i) => [i]) });
    });
  } else if (Array.isArray(result.answer_segments) && result.answer_segments.length) {
    const paragraphs = result.answer_segments.map((s) => take(s.claim_ids ?? [])).filter((p) => p.length);
    if (paragraphs.length) out.push({ key: 'answer', paragraphs });
  }
  const rest = claims.map((_, i) => i).filter((i) => !used.has(i));
  if (rest.length) {
    if (out.length) out[out.length - 1].paragraphs.push(...rest.map((i) => [i]));
    else out.push({ key: 'answer', paragraphs: rest.map((i) => [i]) });
  }
  return out;
}

async function copyText(value: string) {
  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch {
    return false;
  }
}

function SourceQuote({
  source,
  versionLabel,
  onEvidence,
  onClose,
}: {
  source: Source;
  versionLabel: (versionId: string) => string;
  onEvidence: (e: Evidence) => void;
  onClose?: () => void;
}) {
  const e = source.evidence;
  return (
    <div className="source-item" role="group" aria-label={`来源 ${source.n}`}>
      <span className="source-n">{source.n}</span>
      <div>
        <blockquote>{e.quote}</blockquote>
        <footer>
          <span>
            {versionLabel(e.version_id)} · 第 {e.page_index + 1} 页
          </span>
          <button className="small-button" onClick={() => onEvidence(e)}>
            <ExternalLink size={13} />
            在原文中定位
          </button>
          {onClose && (
            <button className="icon-button" aria-label="收起来源" onClick={onClose}>
              <X size={13} />
            </button>
          )}
        </footer>
      </div>
    </div>
  );
}

export function AnswerView({
  run,
  onEvidence,
  versionLabel = () => '原文',
  process,
}: {
  run: Run;
  onEvidence: (e: Evidence) => void;
  versionLabel?: (versionId: string) => string;
  /** Folded execution record supplied by the run host: label and content. */
  process?: { label: string; content: ReactNode };
}) {
  const result = parseObject<Result>(run.result, {}) ?? {};
  const claims = (result.claims ?? []) as Claim[];
  const [panel, setPanel] = useState<Panel>(null);
  const [peek, setPeek] = useState<number | null>(null);
  const [copied, setCopied] = useState(false);
  const { sources, perClaim } = useMemo(() => numberSources(claims), [run.result]);
  const sections = useMemo(() => layout(result, claims), [run.result]);
  const counts = claims.reduce<Record<State, number>>(
    (acc, claim) => ({ ...acc, [claimState(claim)]: acc[claimState(claim)] + 1 }),
    { supported: 0, review: 0, contradicted: 0, insufficient: 0 },
  );
  const downgraded = Array.isArray(result.model_downgraded_from) && result.model_downgraded_from.length > 0;
  const toggle = (next: Panel) => setPanel((p) => (p === next ? null : next));
  const peekSource = peek === null ? null : sources.find((s) => s.n === peek) ?? null;

  const plain = () => {
    const body = sections
      .map((s) =>
        [s.title ? `## ${s.title}` : '', ...s.paragraphs.map((p) => p.map((i) => claims[i].text + perClaim[i].map((n) => `[${n}]`).join('')).join(' '))]
          .filter(Boolean)
          .join('\n\n'),
      )
      .join('\n\n');
    const refs = sources.map((s) => `[${s.n}] ${versionLabel(s.evidence.version_id)}，第 ${s.evidence.page_index + 1} 页：${s.evidence.quote}`);
    return claims.length ? [body, refs.length ? '来源\n' + refs.join('\n') : ''].filter(Boolean).join('\n\n') : String(result.answer ?? '');
  };

  const hasBody = claims.length > 0 || Boolean(result.answer);
  const issues = counts.review + counts.contradicted + counts.insufficient;

  return (
    <div className="answer-view">
      {run.error && <ErrorBox error={run.error} />}
      {hasBody && (
        <div className="answer-body">
          {claims.length > 0
            ? sections.map((section) => (
                <Fragment key={section.key}>
                  {section.title && <h3 className="answer-section">{section.title}</h3>}
                  {section.paragraphs.map((paragraph, k) => {
                    const peekHere = peekSource && paragraph.some((i) => perClaim[i].includes(peekSource.n));
                    return (
                      <Fragment key={k}>
                        <p>
                          {paragraph.map((i) => {
                            const claim = claims[i];
                            const state = claimState(claim);
                            return (
                              <span key={i} className={`answer-claim ${state}`} title={state === 'supported' ? undefined : STATE_LABEL[state]}>
                                {claim.text.slice(0, -2)}
                                {/* The last characters, tag and numbers never wrap apart. */}
                                <span className="claim-end">
                                {claim.text.slice(-2)}
                                {KIND_LABEL[claim.type] && <em className="claim-tag">{KIND_LABEL[claim.type]}</em>}
                                {perClaim[i].map((n) => (
                                  <button
                                    key={n}
                                    className={`cite-mark ${peek === n ? 'active' : ''}`}
                                    aria-label={`查看来源 ${n}`}
                                    aria-expanded={peek === n}
                                    title={sources[n - 1].evidence.quote.slice(0, 160)}
                                    onClick={() => setPeek(peek === n ? null : n)}
                                  >
                                    {n}
                                  </button>
                                ))}
                                </span>{' '}
                              </span>
                            );
                          })}
                        </p>
                        {peekHere && (
                          <div className="evidence-peek">
                            <SourceQuote source={peekSource} versionLabel={versionLabel} onEvidence={onEvidence} onClose={() => setPeek(null)} />
                          </div>
                        )}
                      </Fragment>
                    );
                  })}
                </Fragment>
              ))
            : <Markdown>{String(result.answer)}</Markdown>}
        </div>
      )}

      {(hasBody || process || result.artifact_id) && (
        <div className="answer-tools" role="toolbar" aria-label="回答工具">
          {claims.length > 0 && (
            <button
              className={`tool-button ${issues ? 'review' : 'ok'}`}
              aria-expanded={panel === 'checks'}
              onClick={() => toggle('checks')}
              title="逐条核对状态"
            >
              {issues ? <TriangleAlert size={14} /> : <ShieldCheck size={14} />}
              {issues ? `${counts.supported}/${claims.length} 已核对` : `${counts.supported} 条已核对`}
            </button>
          )}
          {sources.length > 0 && (
            <button className="tool-button" aria-expanded={panel === 'sources'} onClick={() => toggle('sources')} title="引用的原文段落">
              <Quote size={14} />
              来源 {sources.length}
            </button>
          )}
          {process && (
            <button className="tool-button" aria-expanded={panel === 'process'} onClick={() => toggle('process')} title="公开执行记录与检索范围">
              <Workflow size={14} />
              {process.label}
            </button>
          )}
          <span className="tool-spacer" />
          {hasBody && (
            <button
              className="tool-button icon-only"
              aria-label="复制回答"
              title="复制回答与来源"
              onClick={() => void copyText(plain()).then((ok) => {
                if (!ok) return;
                setCopied(true);
                window.setTimeout(() => setCopied(false), 1400);
              })}
            >
              {copied ? <Check size={14} /> : <Copy size={14} />}
            </button>
          )}
          {result.artifact_id && (
            <button className="tool-button icon-only" aria-label="导出" title="导出 Markdown / HTML / BibTeX" aria-expanded={panel === 'export'} onClick={() => toggle('export')}>
              <FileDown size={14} />
            </button>
          )}
        </div>
      )}

      {panel === 'checks' && (
        <div className="answer-panel" aria-label="核对详情">
          {claims.map((claim, i) => {
            const state = claimState(claim);
            return (
              <div className={`check-row ${state}`} key={claim.id ?? i}>
                <span className="claim-dot" aria-hidden />
                <div>
                  <p>{claim.text}</p>
                  <small>
                    <b>{STATE_LABEL[state]}</b>
                    {REVIEWER[claim.review?.method ?? ''] && ` · ${REVIEWER[claim.review?.method ?? '']}`}
                    {KIND_LABEL[claim.type] && ` · 模型${KIND_LABEL[claim.type]}`}
                    {perClaim[i].length > 0 && ` · 来源 ${perClaim[i].join('、')}`}
                  </small>
                  {claim.review?.reason && state !== 'supported' && <small className="check-reason">复核说明：{claim.review.reason}</small>}
                </div>
              </div>
            );
          })}
          <p className="answer-panel-foot">
            {result.model && (
              <span className={`model-tag ${downgraded ? 'downgraded' : ''}`}>
                {downgraded ? '已降级 · ' : ''}
                {String(result.model)}
              </span>
            )}
            <span>{date(run.updated || run.created)}</span>
            {result.publication_notice && <span>{String(result.publication_notice)}</span>}
          </p>
        </div>
      )}

      {panel === 'sources' && (
        <div className="answer-panel sources" aria-label="来源">
          {sources.map((source) => (
            <SourceQuote key={source.n} source={source} versionLabel={versionLabel} onEvidence={onEvidence} />
          ))}
        </div>
      )}

      {panel === 'process' && process && <div className="answer-panel" aria-label="执行过程">{process.content}</div>}

      {panel === 'export' && result.artifact_id && (
        <div className="answer-panel export-row" aria-label="导出">
          {[
            ['md', 'Markdown'],
            ['html', 'HTML'],
            ['bib', 'BibTeX'],
          ].map(([format, label]) => (
            <a key={format} className="small-button" href={endpoint(`/artifacts/${result.artifact_id}/export?format=${format}`)} download>
              <FileDown size={13} />
              {label}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
