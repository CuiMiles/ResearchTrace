import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api, date, errorMessage } from './api';
import { Busy, ErrorBox } from './ui';

interface ReviewerAccount {
  id: string;
  workspace: string;
  label: string;
  created: number;
  expires: number;
  revoked: boolean;
  last_login: number | null;
  status: 'active' | 'expired' | 'revoked';
}

interface IssuedReviewer extends ReviewerAccount {
  access_code: string;
}
interface WorkspaceChoice {id:string;name:string;documents:number;ready_documents:number}

export function ReviewAccounts({ role }: { role: string }) {
  // Unmount the admin view on role changes, clearing its one-time secret state.
  return role === 'admin' ? <AdminReviewAccounts /> : null;
}

function AdminReviewAccounts() {
  const [accounts, setAccounts] = useState<ReviewerAccount[]>([]);
  const [label, setLabel] = useState('');
  const [days, setDays] = useState('7');
  const [workspace,setWorkspace]=useState('');
  const [copySeed,setCopySeed]=useState(true);
  const [workspaces,setWorkspaces]=useState<WorkspaceChoice[]>([]);
  const [issued, setIssued] = useState<IssuedReviewer | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const mounted = useRef(false);
  const listVersion = useRef(0);

  async function load() {
    const version = ++listVersion.current;
    setLoading(true);
    setError('');
    try {
      const [result,choices] = await Promise.all([api<ReviewerAccount[]>('/admin/reviewers'),api<WorkspaceChoice[]>('/admin/reviewer-workspaces?include_bound=true')]);
      if (mounted.current && version === listVersion.current) {setAccounts(result);setWorkspaces(choices);}
    } catch (e) {
      if (mounted.current && version === listVersion.current) setError(errorMessage(e));
    } finally {
      if (mounted.current && version === listVersion.current) setLoading(false);
    }
  }

  useEffect(() => {
    mounted.current = true;
    void load();
    return () => { mounted.current = false; listVersion.current += 1; };
  }, []);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const lifetime = Number(days);
    if (!label.trim() || label.trim().length > 120 || !Number.isInteger(lifetime) || lifetime < 1 || lifetime > 90) {
      setError('请填写评审名称和 1–90 天的整数有效期。');
      return;
    }
    if (busy || issued) return;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const result = await api<IssuedReviewer>('/admin/reviewers', { label: label.trim(), days: lifetime,...(workspace?{[copySeed?'seed_workspace_id':'workspace_id']:workspace}:{}) });
      if (!mounted.current) return;
      // Keep the code only in this temporary state, never in the metadata list.
      const { access_code, ...metadata } = result;
      listVersion.current += 1;
      setLoading(false);
      setAccounts(current => [metadata, ...current.filter(item => item.id !== metadata.id)]);
      setIssued({ ...metadata, access_code });
      setWorkspaces(current=>current.filter(item=>item.id!==metadata.workspace));setWorkspace('');
      setLabel('');
    } catch (e) {
      if (mounted.current) setError(errorMessage(e));
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  async function revoke(account: ReviewerAccount) {
    if (busy) return;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const result = await api<ReviewerAccount>(`/admin/reviewers/${encodeURIComponent(account.id)}/revoke`, {});
      if (!mounted.current) return;
      listVersion.current += 1;
      setLoading(false);
      setAccounts(current => current.map(item => item.id === result.id ? result : item));
      if (issued?.id === result.id) setIssued(null);
      setNotice(`已撤销「${account.label}」的访问码及评审会话。`);
    } catch (e) {
      if (mounted.current) setError(errorMessage(e));
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  return <section aria-labelledby="reviewer-accounts-heading">
    <div className="section-heading">
      <h2 id="reviewer-accounts-heading">评审访问码</h2>
      <button className="secondary-button" type="button" disabled={loading || busy} onClick={() => void load()}>
        {loading ? <Busy /> : '刷新评审列表'}
      </button>
    </div>
    <p className="muted">评审访问码固定绑定一个研究空间。可创建空白空间供新输入测试，也可明确选择已有演示资料；换浏览器后仍返回该空间。</p>
    {error && <ErrorBox error={error} onClose={() => setError('')} />}
    {notice && <p role="status">{notice}</p>}
    <form onSubmit={event => void create(event)}>
      <div className="field-pair">
        <label>评审名称<input required maxLength={120} value={label} disabled={busy}
          onChange={event => setLabel(event.target.value)} autoComplete="off" placeholder="便于管理员辨认的名称" /></label>
        <label>有效天数<input type="number" min={1} max={90} step={1} required value={days} disabled={busy}
          onChange={event => setDays(event.target.value)} /></label>
      </div>
      <label>研究资料空间<select aria-label="研究资料空间" value={workspace} disabled={busy} onChange={event=>setWorkspace(event.target.value)}>
        <option value="">新建空白评审空间</option>
        {workspaces.filter(item=>copySeed||!accounts.some(a=>a.workspace===item.id)).map(item=><option key={item.id} value={item.id}>{item.name} · {item.ready_documents}/{item.documents} 篇已解析 · {item.id.slice(0,8)}</option>)}
      </select></label>
      {workspace&&<><label><input type="checkbox" checked={copySeed} onChange={e=>setCopySeed(e.target.checked)}/>复制为独立评审资料（沿用现有向量，不重新计费）</label><p className="info-note">{copySeed?'复制文献与完整索引到新空间；不复制历史回答、私有笔记或调用账本。':'此访问码将能读取并操作选定空间中的现有文献与研究记录。'}</p></>}
      <button className="primary-button" type="submit" disabled={busy || !!issued || !label.trim()}>
        {busy ? <Busy /> : '创建独立评审访问码'}
      </button>
    </form>
    {issued && <div className="provider-policy" role="status">
      <h3>「{issued.label}」的访问码仅本次显示</h3>
      <p>请通过私密渠道交给对应评审。关闭此提示或离开页面后，无法再次查看。</p>
      <label>新评审访问码<input readOnly value={issued.access_code} autoComplete="off" spellCheck={false}
        onFocus={event => event.currentTarget.select()} /></label>
      <p>有效期至 {date(issued.expires)}。在登录页输入此访问码即可进入固定研究空间。</p>
      <button className="secondary-button" type="button" onClick={() => setIssued(null)}>已保存，隐藏访问码</button>
    </div>}
    <div className="data-table-wrap">
      <table>
        <thead><tr><th>评审名称</th><th>状态</th><th>创建时间</th><th>有效期至</th><th>最近登录</th><th>操作</th></tr></thead>
        <tbody>{accounts.map(account => {
          const status = account.revoked ? 'revoked' : account.expires <= Date.now() / 1000 ? 'expired' : account.status;
          return <tr key={account.id}>
            <td>{account.label}</td>
            <td>{{ active: '可访问', expired: '已过期', revoked: '已撤销' }[status]}</td>
            <td>{date(account.created)}</td><td>{date(account.expires)}</td>
            <td>{account.last_login ? date(account.last_login) : '尚未登录'}</td>
            <td><button className="small-button" type="button" disabled={busy || account.revoked}
              aria-label={`撤销 ${account.label}`} onClick={() => void revoke(account)}>
              {account.revoked ? '已撤销' : '撤销访问'}
            </button></td>
          </tr>;
        })}</tbody>
      </table>
      {!accounts.length && <p className="muted padded">{loading ? '正在读取评审列表…' : '尚未创建独立评审访问码。'}</p>}
    </div>
  </section>;
}
