/**
 * Guest mode: the entrance on the login page, the notice shown on entry (and
 * again when the day's AI calls run out), and the top-bar chip with the calls
 * left. All numbers come from the server; nothing here grants or counts quota.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { api, errorMessage } from '../../api';
import { ArrowRight, Info, TriangleAlert, X } from '../../icons';
import type { Session } from '../../types';
import { Busy, ErrorBox } from '../../ui';
import './guest.css';

export interface GuestEntrance {
  enabled: boolean;
  models?: string[];
  embedding_model?: string;
  daily_calls?: number;
  hours?: number;
  max_documents?: number;
}

export interface GuestStatus {
  guest: boolean;
  models: string[];
  embedding_model: string;
  daily_calls: number;
  used_calls: number;
  remaining_calls: number;
  global_remaining_calls: number;
  expires: number;
  seeded_documents: number;
  max_documents: number;
}

const NOTICE_KEY = 'rt-guest-notice';

function remember(value: string) {
  try {
    sessionStorage.setItem(NOTICE_KEY, value);
  } catch {
    /* private mode: the notice may simply show again */
  }
}

function recalled() {
  try {
    return sessionStorage.getItem(NOTICE_KEY) ?? '';
  } catch {
    return '';
  }
}

/** Login-page button; resolves to a guest session. */
export function GuestEntry({ onLogin }: { onLogin: (s: Session) => void }) {
  const [entrance, setEntrance] = useState<GuestEntrance | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    let live = true;
    api<GuestEntrance>('/auth/guest')
      .then((e) => live && setEntrance(e))
      .catch(() => live && setEntrance({ enabled: false }));
    return () => {
      live = false;
    };
  }, []);
  if (!entrance?.enabled) return null;
  async function enter() {
    setBusy(true);
    setError('');
    try {
      const session = await api<Session>('/auth/guest', {});
      remember('');
      onLogin(session);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="guest-entry">
      <div className="guest-divider">
        <span>或</span>
      </div>
      <button type="button" className="secondary-button guest-button" onClick={() => void enter()} disabled={busy}>
        {busy ? <Busy>正在准备游客空间</Busy> : <>以游客身份体验<ArrowRight size={16} /></>}
      </button>
      <p className="guest-hint">无需访问码 · 轻量模型 · 每日 {entrance.daily_calls ?? '有限'} 次 AI 调用</p>
      {error && <ErrorBox error={error} />}
    </div>
  );
}

/** Top-bar chip plus the notice dialog; renders nothing for non-guests. */
export function GuestBanner({ role, runs, onSignIn }: { role: string; runs: number; onSignIn: () => void }) {
  const [status, setStatus] = useState<GuestStatus | null>(null);
  const [open, setOpen] = useState<'welcome' | 'empty' | 'info' | null>(null);
  const guest = role === 'guest';
  const load = useCallback(async () => {
    try {
      const next = await api<GuestStatus>('/guest/status');
      if (!next.guest) return;
      setStatus(next);
      const seen = recalled();
      if (!seen) setOpen('welcome');
      else if (next.remaining_calls === 0 && seen !== 'empty') setOpen('empty');
    } catch {
      /* the chip simply stays hidden */
    }
  }, []);
  useEffect(() => {
    if (guest) void load();
  }, [guest, runs, load]);
  const dialog = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (open) dialog.current?.querySelector<HTMLButtonElement>('button.primary-button')?.focus();
  }, [open]);
  if (!guest || !status) return null;
  const low = status.remaining_calls <= Math.max(1, Math.floor(status.daily_calls / 5));
  const close = () => {
    remember(status.remaining_calls === 0 ? 'empty' : 'seen');
    setOpen(null);
  };
  const hoursLeft = Math.max(0, Math.round((status.expires - Date.now() / 1000) / 3600));
  return (
    <>
      <button
        className={`guest-chip ${low ? 'low' : ''}`}
        onClick={() => setOpen('info')}
        title="游客模式说明与剩余额度"
      >
        {low ? <TriangleAlert size={13} /> : <Info size={13} />}
        游客模式 · 剩余 {status.remaining_calls} 次
      </button>
      {open && createPortal(
        <div className="guest-backdrop" role="presentation" onClick={close}>
          <div
            className="guest-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="guest-dialog-title"
            ref={dialog}
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => e.key === 'Escape' && close()}
          >
            <button className="icon-button guest-close" aria-label="关闭" onClick={close}>
              <X size={16} />
            </button>
            {open === 'empty' ? (
              <>
                <h2 id="guest-dialog-title">今日游客额度已用完</h2>
                <p>
                  本游客空间今天的 AI 调用次数已用完（失败和超时的请求同样计数）。阅读原文、查看已有回答与原文定位仍可继续使用；
                  新的问答、翻译和写作请明天再试，或使用评审访问码登录。
                </p>
              </>
            ) : (
              <>
                <h2 id="guest-dialog-title">你正在使用游客模式</h2>
                <p>为控制公共额度，游客模式使用轻量配置，回答质量、速度和稳定性会低于评审模式。</p>
              </>
            )}
            <dl className="guest-facts">
              <div>
                <dt>生成模型</dt>
                <dd>{status.models.join(' → ')}<small>评审模式使用更强的分析与复核模型</small></dd>
              </div>
              <div>
                <dt>语义检索</dt>
                <dd>{status.embedding_model} + 关键词<small>不使用本地 GPU 向量检索与重排</small></dd>
              </div>
              <div>
                <dt>今日额度</dt>
                <dd>
                  剩余 {status.remaining_calls} / {status.daily_calls} 次 AI 调用
                  <small>全体游客另有共享上限，今日共享剩余 {status.global_remaining_calls} 次</small>
                </dd>
              </div>
              <div>
                <dt>游客空间</dt>
                <dd>
                  独立空间，约 {hoursLeft} 小时后自动清除
                  <small>
                    {status.seeded_documents ? `预置 ${status.seeded_documents} 篇示例论文；` : ''}可再上传 {status.max_documents} 篇（仅关键词索引）
                  </small>
                </dd>
              </div>
            </dl>
            <p className="guest-small">参考文献批量下载、定时追踪与索引管理仅在评审模式提供。</p>
            <div className="guest-actions">
              <button className="secondary-button" onClick={onSignIn}>
                使用评审访问码
              </button>
              <button className="primary-button" onClick={close}>
                {open === 'empty' ? '知道了' : '开始体验'}
              </button>
            </div>
          </div>
        </div>,
        // Outside the sticky top bar, whose stacking context would clip a fixed overlay.
        document.body,
      )}
    </>
  );
}
