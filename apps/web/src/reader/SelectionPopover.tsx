import { useState } from 'react';
import { Check, Copy, Languages, MessageSquare, Sparkles, X } from '../icons';
import { Busy } from '../ui';

export interface SelectionTask {
  id: string;
  text: string;
  status: string;
  translation?: string;
  cached?: boolean;
  error?: string;
}

interface Props {
  text: string;
  task: SelectionTask | null;
  targetLanguage: 'zh-Hans' | 'en';
  canTranslate: boolean;
  canAsk: boolean;
  submitting: boolean;
  autoTranslate: boolean;
  onAutoTranslate: (on: boolean) => void;
  onTargetLanguage: (language: 'zh-Hans' | 'en') => void;
  onTranslate: () => void;
  onExplain: () => void;
  onAsk: () => void;
  onClose: () => void;
}

async function copy(text: string) {
  try { await navigator.clipboard.writeText(text); return true; } catch { return false; }
}

/** Floating actions next to selected PDF text (划词翻译 / 解释 / 提问). */
export function SelectionPopover(props: Props) {
  const { text, task, targetLanguage, canTranslate, canAsk, submitting } = props;
  const [copied, setCopied] = useState<'source' | 'translation' | ''>('');
  const flash = (which: 'source' | 'translation') => { setCopied(which); window.setTimeout(() => setCopied(''), 1400); };
  const running = task && ['queued', 'running', 'waiting_children', 'waiting_batch'].includes(task.status);
  return <div className="sp" role="region" aria-label="选段操作" onKeyDown={e => { if (e.key === 'Escape') props.onClose(); }}>
    <div className="sp-actions">
      <button className="sp-primary" aria-label="翻译选段" disabled={!canTranslate || submitting || Boolean(running)} onClick={props.onTranslate}
        title={canTranslate ? '翻译选中的文字' : '翻译服务暂未配置'}><Languages size={14} />翻译</button>
      <button aria-label="解释选段" disabled={!canAsk || submitting} onClick={props.onExplain} title="让 AI 结合原文解释"><Sparkles size={14} />解释</button>
      <button aria-label="就此提问" onClick={props.onAsk} title="带着这段文字向 AI 提问"><MessageSquare size={14} />提问</button>
      <button aria-label="复制选中文字" onClick={() => void copy(text).then(ok => ok && flash('source'))} title="复制原文">
        {copied === 'source' ? <Check size={14} /> : <Copy size={14} />}
      </button>
      <span className="sp-divider" />
      <button className="sp-lang" aria-label="切换翻译目标语言" title="切换翻译目标语言"
        onClick={() => props.onTargetLanguage(targetLanguage === 'zh-Hans' ? 'en' : 'zh-Hans')}>{targetLanguage === 'zh-Hans' ? '译为中文' : '译为英文'}</button>
      <button className="sp-close" aria-label="关闭选段操作" onClick={props.onClose}><X size={14} /></button>
    </div>
    {task && <div className="sp-result" aria-live="polite">
      {running ? <Busy>正在翻译…</Busy>
        : task.status === 'completed' && task.translation ? <>
          <p>{task.translation}</p>
          <div className="sp-meta">
            <span data-cache={task.cached ? 'hit' : 'miss'}>{task.cached ? '来自翻译缓存' : '翻译完成'}</span>
            <button onClick={() => void copy(task.translation!).then(ok => ok && flash('translation'))}>
              {copied === 'translation' ? <><Check size={12} />已复制</> : <><Copy size={12} />复制译文</>}
            </button>
          </div>
        </>
        : <p className="sp-error">{task.error || (task.status === 'cancelled' ? '翻译已取消。' : '这次没有翻译成功，请稍后再试。')}</p>}
    </div>}
    <label className="sp-auto"><input type="checkbox" checked={props.autoTranslate} disabled={!canTranslate}
      onChange={e => props.onAutoTranslate(e.target.checked)} />划词后自动翻译</label>
  </div>;
}
