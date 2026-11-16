/**
 * Renders a validated answer as claim lines. Each line carries its review
 * status (supported / needs review / contradicted / insufficient), its kind
 * when it is not a plain source fact, and numbered evidence chips. A chip
 * opens the exact quote with version and page and can jump to the PDF region.
 */
import { useState } from 'react';
import { ExternalLink, FileDown, Quote } from '../icons';
import { date, endpoint, parseObject } from '../api';
import type { Claim, Evidence, Result, Run } from '../types';
import { ErrorBox, Markdown } from '../ui';

type State = 'supported' | 'review' | 'contradicted' | 'insufficient';

const STATE_LABEL: Record<State, string> = {
  supported: '已核对支持',
  review: '已定位，待复核',
  contradicted: '与原文矛盾',
  insufficient: '证据不足',
};

const KIND_LABEL: Record<string, string> = {
  inference: '模型推断',
  suggestion: '研究建议',
  research_suggestion: '研究建议',
  calculation: '确定性计算',
};

export function claimState(claim: Claim): State {
  if (claim.type === 'insufficient' || claim.type === 'insufficient_evidence') return 'insufficient';
  const status = claim.review?.status;
  if (status === 'supported') return 'supported';
  if (status === 'contradicted') return 'contradicted';
  if (status === 'insufficient') return 'insufficient';
  return 'review';
}

function EvidenceChip({
  evidence,
  label,
  onEvidence,
  versionLabel,
}: {
  evidence: Evidence;
  label: string;
  onEvidence: (e: Evidence) => void;
  versionLabel: (versionId: string) => string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        className="evidence-chip"
        aria-expanded={open}
        title={evidence.quote}
        onClick={() => setOpen(!open)}
      >
        <Quote size={11} />
        {label} · 第 {evidence.page_index + 1} 页
      </button>
      {open && (
        <div className="evidence-peek" role="region" aria-label={`证据 ${label}`}>
          <blockquote>{evidence.quote}</blockquote>
          <footer>
            <span>
              {versionLabel(evidence.version_id)} · 物理页 {evidence.page_index + 1} · 逐字匹配原文
            </span>
            <button className="small-button" onClick={() => onEvidence(evidence)}>
              <ExternalLink size={13} />
              在原文中定位
            </button>
          </footer>
        </div>
      )}
    </>
  );
}

export function AnswerView({
  run,
  onEvidence,
  versionLabel = () => '原文',
}: {
  run: Run;
  onEvidence: (e: Evidence) => void;
  versionLabel?: (versionId: string) => string;
}) {
  const result = parseObject<Result>(run.result, {}) ?? {};
  const claims = (result.claims ?? []) as Claim[];
  const counts = claims.reduce<Record<State, number>>(
    (acc, claim) => ({ ...acc, [claimState(claim)]: acc[claimState(claim)] + 1 }),
    { supported: 0, review: 0, contradicted: 0, insufficient: 0 },
  );
  const downgraded = Array.isArray(result.model_downgraded_from) && result.model_downgraded_from.length > 0;
  const allChecked = claims.length > 0 && counts.review === 0;
  return (
    <div className="answer-view">
      {run.error && <ErrorBox error={run.error} />}
      {claims.length > 0 ? (
        <div className="claim-lines">
          {claims.map((claim, i) => {
            const state = claimState(claim);
            return (
              <div className={`claim-line ${state}`} key={claim.id ?? i}>
                <span className="claim-dot" aria-hidden />
                <div>
                  <p>{claim.text}</p>
                  <div className="claim-foot">
                    <span className="claim-status">{STATE_LABEL[state]}</span>
                    {KIND_LABEL[claim.type] && <span className="claim-kind inference">{KIND_LABEL[claim.type]}</span>}
                    {(claim.evidence ?? []).map((evidence, j) => (
                      <EvidenceChip
                        key={j}
                        evidence={evidence}
                        label={`${i + 1}.${j + 1}`}
                        onEvidence={onEvidence}
                        versionLabel={versionLabel}
                      />
                    ))}
                  </div>
                  {claim.review?.reason && state !== 'supported' && (
                    <p className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                      复核说明：{claim.review.reason}
                    </p>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        result.answer && (
          <div className="answer-text">
            <Markdown>{String(result.answer)}</Markdown>
          </div>
        )
      )}
      {claims.length > 0 && (
        <div className="answer-meta">
          {result.model && (
            <span className={`model-tag ${downgraded ? 'downgraded' : ''}`}>
              {downgraded ? '已降级 · ' : ''}
              {String(result.model)}
            </span>
          )}
          <span>
            {counts.supported > 0 && `${counts.supported} 条已核对支持`}
            {counts.review > 0 && ` · ${counts.review} 条待复核`}
            {counts.contradicted > 0 && ` · ${counts.contradicted} 条矛盾`}
            {counts.insufficient > 0 && ` · ${counts.insufficient} 条证据不足`}
          </span>
          <span>{date(run.updated || run.created)}</span>
        </div>
      )}
      {!allChecked && result.publication_notice && claims.length > 0 && (
        <p className="info-note">{String(result.publication_notice)}</p>
      )}
      {result.artifact_id && (
        <div className="export-row">
          {[
            ['md', 'Markdown'],
            ['html', 'HTML'],
            ['bib', 'BibTeX'],
          ].map(([format, label]) => (
            <a
              key={format}
              className="small-button"
              href={endpoint(`/artifacts/${result.artifact_id}/export?format=${format}`)}
              download
            >
              <FileDown size={13} />
              {label}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
