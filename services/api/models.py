"""Native Gemini adapter with transactional, project-scoped quota accounting."""
import json
import os
import ssl
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv

from . import store
from .store import ROOT, db, event, one, rows, uid

load_dotenv(ROOT / '.env', override=False)
PACIFIC = ZoneInfo('America/Los_Angeles')
CORE = os.getenv('GEMINI_CORE_MODEL', 'gemini-4-hydrogen')
BATCH = os.getenv('GEMINI_BATCH_MODEL', 'gemini-3.5-flash-lite')
EMBED = os.getenv('GEMINI_EMBEDDING_MODEL', 'gemini-embedding-001')
BASE = 'https://generativelanguage.googleapis.com/v1beta'

class ModelError(Exception):
    pass

class QuotaRefusal(ModelError):
    """A local refusal. Only project/transient refusals permit another route."""
    def __init__(self, message, *, scope, code):
        super().__init__(message)
        self.scope = scope
        self.code = code

class SentRequestError(ModelError):
    """A sent request must remain accounted for and must not be retried here."""
    def __init__(self, message, *, outcome, quota_id, http_status=None):
        super().__init__(message)
        self.outcome = outcome
        self.quota_id = quota_id
        self.http_status = http_status

PROFILE_LIMITS = {'smoke': 'HYDROGEN_SMOKE_LIMIT',
                  'evaluation': 'HYDROGEN_EVALUATION_LIMIT',
                  'judging': 'HYDROGEN_JUDGING_LIMIT'}

def _budget_number(name, default=None, minimum=0):
    raw = os.getenv(name, str(default) if default is not None else '')
    # Never echo the supplied value: operator configuration can contain secrets.
    if not raw.isascii() or not raw.isdecimal() or len(raw) > 10:
        raise QuotaRefusal(f'{name} 需要操作员配置显式整数预算', scope='global', code='budget_configuration')
    value = int(raw)
    if value < minimum or value > 2147483647:
        raise QuotaRefusal(f'{name} 预算超出允许范围', scope='global', code='budget_configuration')
    return value

def budget_policy():
    """Only server configuration selects a profile; no request payload can grant budget.

    Selecting an explicitly funded profile starts it; exhaustion or deselection
    stops it. Counters are lifetime totals, never reset by restarts or day changes.
    RT_SMOKE_MODE=false alone no longer authorizes an unbounded core budget.
    """
    profile = os.getenv('RT_BUDGET_PROFILE', 'smoke')
    if profile not in PROFILE_LIMITS:
        raise QuotaRefusal('未知预算配置；允许 smoke/evaluation/judging', scope='global', code='budget_configuration')
    return {'profile': profile,
            'limit': _budget_number(PROFILE_LIMITS[profile], 4 if profile == 'smoke' else None,
                                    0 if profile == 'smoke' else 1),
            'workflow_limit': _budget_number('HYDROGEN_WORKFLOW_LIMIT', 2, 1),
            'workspace_limit': _budget_number('HYDROGEN_SESSION_LIMIT', 2),
            'runtime_soft_rpd': _budget_number('HYDROGEN_RUNTIME_SOFT_RPD', 16)}

def _profile_used(c, profile):
    # Untagged historical rows stay smoke. No UPDATE/backfill of the quota ledger.
    return c.execute('''SELECT COUNT(*) FROM quota q LEFT JOIN quota_context x ON x.quota_id=q.id
                        WHERE q.model=? AND COALESCE(x.profile,'smoke')=?''', (CORE, profile)).fetchone()[0]

def _workflow_context(c, run_id, configured_limit):
    prior = c.execute('''SELECT COALESCE(x.profile,'smoke') profile,
                               MIN(COALESCE(x.workflow_limit,2)) workflow_limit
                        FROM quota q LEFT JOIN quota_context x ON x.quota_id=q.id
                        WHERE q.run_id=? GROUP BY COALESCE(x.profile,'smoke')
                        ORDER BY MIN(q.started),MIN(q.rowid) LIMIT 1''', (run_id,)).fetchone()
    return prior, min(configured_limit, prior['workflow_limit']) if prior else configured_limit

def _global_budget(c, model, run_id, run, policy, now):
    prior, workflow_limit = _workflow_context(c, run_id, policy['workflow_limit'])
    if prior and prior['profile'] != policy['profile']:
        raise QuotaRefusal('工作流预算配置已固定；切换配置不能追加调用', scope='global', code='workflow_profile')
    if model == CORE:
        if _profile_used(c, policy['profile']) >= policy['limit']:
            message = ('Hydrogen 显式冒烟预算已用尽；管理员需配置后续预算' if policy['profile'] == 'smoke'
                       else 'Hydrogen 当前配置的显式总预算已用尽')
            raise QuotaRefusal(message, scope='global', code='profile_budget')
        if run_id:
            used = c.execute('SELECT COUNT(*) FROM quota WHERE model=? AND run_id=?', (CORE, run_id)).fetchone()[0]
            if used >= workflow_limit:
                raise QuotaRefusal('本工作流 Hydrogen 总调用上限已用尽', scope='global', code='workflow_budget')
        if run:
            used = c.execute('''SELECT COUNT(*) FROM quota q JOIN runs r ON r.id=q.run_id
                                WHERE q.model=? AND r.workspace=? AND q.day=?''',
                             (CORE, run['workspace'], quota_day(now))).fetchone()[0]
            if used >= policy['workspace_limit']:
                raise QuotaRefusal('本工作区 Hydrogen 日预算已用尽', scope='global', code='workspace_budget')
    return workflow_limit

def quota_day(now=None):
    return datetime.fromtimestamp(time.time() if now is None else now, PACIFIC).date().isoformat()

def reset_at(now=None):
    dt = datetime.fromtimestamp(time.time() if now is None else now, PACIFIC)
    return datetime.combine(dt.date()+timedelta(days=1),datetime.min.time(),PACIFIC).timestamp()

def credentials():
    first = os.getenv('GEMINI_PROJECT_1','').strip()
    second = os.getenv('GEMINI_PROJECT_2','').strip()
    # A missing project ID cannot manufacture an independent quota group.
    shared = first or second or 'gemini-shared'
    choices=[(first or shared,os.getenv('GEMINI_API_KEY','')),
             (second or shared,os.getenv('GEMINI_API_KEY2',''))]
    # Operator selection changes credentials, never the project accounting group.
    return choices[::-1] if os.getenv('RT_PREFERRED_CREDENTIAL','1')=='2' else choices

def limits(model):
    try:
        overrides=json.loads(os.getenv('RT_MODEL_PROJECT_LIMITS','{}'))
        entry=overrides.get(model)
        if entry is not None:
            if not isinstance(entry,list) or len(entry)!=3 or any(type(v) is not int or v<1 for v in entry):
                raise ValueError
            return tuple(entry)
    except (ValueError,TypeError,AttributeError):
        raise QuotaRefusal('项目模型额度配置无效',scope='global',code='budget_configuration') from None
    if model == CORE:
        return (5,250000,20)
    if 'embedding' in model:
        return (100,30000,1000)
    if model == 'gemini-decision-1':
        # Provider free tier recorded 2026-11-16: 200 RPM, 50K input TPM, 10K RPD.
        return (200,50000,10000)
    if 'flash' in model and 'lite' not in model:
        # Team quota snapshot: the non-lite Flash tier shares Hydrogen's limits.
        return (5,250000,20)
    return (15,250000,500)


def accounting_projects(project):
    """Operator aliases retain earlier ledger rows under the same real project."""
    try:
        aliases=json.loads(os.getenv('RT_LEGACY_PROJECT_MAP','{}'))
        if not isinstance(aliases,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in aliases.items()):raise ValueError
    except ValueError:raise QuotaRefusal('历史项目映射无效',scope='global',code='budget_configuration') from None
    return tuple(dict.fromkeys([project]+[k for k,v in aliases.items() if v==project]))

def reserve(project,model,tokens,run_id,now=None,request_units=1):
    now = time.time() if now is None else now
    rpm,tpm,rpd=limits(model)
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if type(request_units) is not int or not 0<=request_units<=32:raise ValueError('Invalid provider request units')
        run = None
        if run_id:
            run=c.execute('SELECT workspace,status FROM runs WHERE id=?',(run_id,)).fetchone()
            if not run:
                raise QuotaRefusal('任务不存在；没有发出新的模型请求', scope='global', code='invalid_run')
            if run['status']=='cancelled':
                raise QuotaRefusal('任务已取消；没有发出新的模型请求', scope='global', code='cancelled')
        policy = budget_policy()
        try:
            daily_caps=json.loads(os.getenv('RT_MODEL_DAILY_LIMITS','{}'))
            if not isinstance(daily_caps,dict) or any(type(cap) is not int or cap<1 for cap in daily_caps.values()):
                raise ValueError
        except (ValueError,TypeError):
            raise QuotaRefusal('模型当日总预算配置无效',scope='global',code='budget_configuration') from None
        cap=daily_caps.get(model)
        if cap is not None:
            used=c.execute('SELECT COALESCE(SUM(COALESCE(u.units,1)),0) FROM quota q LEFT JOIN quota_request_units u ON u.quota_id=q.id WHERE q.model=? AND q.day=?',(model,quota_day(now))).fetchone()[0]
            if used+request_units>cap:
                raise QuotaRefusal('该模型当日授权总调用数已用尽，失败与未知请求也计入',scope='global',code='model_daily')
        if model=='gemini-decision-1' and run_id:
            decision_limit=int(os.getenv('RT_DECISION_WORKFLOW_LIMIT','3'))
            if not 1<=decision_limit<=10:raise QuotaRefusal('Decision工作流预算无效',scope='global',code='budget_configuration')
            used=c.execute('SELECT count(*) FROM quota WHERE model=? AND run_id=?',(model,run_id)).fetchone()[0]
            if used>=decision_limit:raise QuotaRefusal('Decision工作流调用预算已用尽',scope='global',code='decision_workflow')
        # Caps across ALL generation models, so a downgrade chain cannot loop or
        # let one workspace drain the high-volume tier. Embeddings are bounded
        # separately by their project window and batch sizes.
        if run_id and 'embedding' not in model:
            run_cap = _budget_number('RT_WORKFLOW_MODEL_CALLS', 60, 1)
            used = c.execute("SELECT COUNT(*) FROM quota WHERE run_id=? AND model NOT LIKE '%embedding%'", (run_id,)).fetchone()[0]
            if used >= run_cap:
                raise QuotaRefusal('本任务的模型调用总上限已用尽', scope='global', code='workflow_calls')
            workspace_cap = _budget_number('RT_WORKSPACE_DAILY_CALLS', 600, 1)
            used = c.execute('''SELECT COUNT(*) FROM quota q JOIN runs r ON r.id=q.run_id
                                WHERE r.workspace=? AND q.day=? AND q.model NOT LIKE '%embedding%' ''',
                             (run['workspace'], quota_day(now))).fetchone()[0]
            if used >= workspace_cap:
                raise QuotaRefusal('本工作区今日模型调用总上限已用尽', scope='global', code='workspace_calls')
        # Global/workspace/workflow guards precede every project-specific check.
        workflow_limit = _global_budget(c, model, run_id, run, policy, now)
        if type(tokens) is not int or tokens < 0 or tokens > min(tpm,96000):
            raise QuotaRefusal('上下文超过本次请求安全预算；请缩小范围', scope='global', code='context_budget')
        groups=accounting_projects(project);marks=','.join('?' for _ in groups)
        minute=c.execute('SELECT COALESCE(SUM(COALESCE(u.units,1)),0),COALESCE(SUM(q.input_tokens),0) FROM quota q LEFT JOIN quota_request_units u ON u.quota_id=q.id WHERE q.project IN ('+marks+') AND q.model=? AND q.started>?',(*groups,model,now-60)).fetchone()
        daily=c.execute('SELECT COALESCE(SUM(COALESCE(u.units,1)),0) FROM quota q LEFT JOIN quota_request_units u ON u.quota_id=q.id WHERE q.project IN ('+marks+') AND q.model=? AND q.day=?',(*groups,model,quota_day(now))).fetchone()[0]
        active=c.execute("SELECT COUNT(*) FROM quota WHERE project IN ("+marks+") AND model=? AND status='reserved' AND started>?",(*groups,model,now-300)).fetchone()[0]
        if daily+request_units>rpd:
            raise QuotaRefusal('项目日额度已用尽；太平洋时间午夜复位', scope='project', code='project_daily')
        if model == CORE and (policy['profile'] != 'smoke' or os.getenv('RT_SMOKE_MODE','true') != 'true'):
            if daily >= policy['runtime_soft_rpd']:
                raise QuotaRefusal('Hydrogen 常规项目日软预算已用尽；保留关键演示额度，不自动继续', scope='project', code='project_soft_daily')
        if active >= 1 or minute[0]+request_units>rpm or minute[1]+tokens>tpm:
            raise QuotaRefusal('项目分钟额度/并发预算不足，请稍后恢复任务', scope='transient', code='project_window')
        qid=uid()
        c.execute('INSERT INTO quota(id,project,model,day,run_id,started,input_tokens,status) VALUES(?,?,?,?,?,?,?,?)',(qid,project,model,quota_day(now),run_id,now,tokens,'reserved'))
        c.execute('INSERT INTO quota_context(quota_id,profile,workflow_limit) VALUES(?,?,?)',
                  (qid,policy['profile'],workflow_limit))
        c.execute('INSERT INTO quota_request_units VALUES(?,?,?)',(qid,request_units,'request_body'))
        return qid

def client():
    """HTTP client for the model provider.

    Proxy and CA bundle come only from operator configuration (never from the
    request or inherited shell variables). RT_CA_BUNDLE is for networks whose
    egress proxy re-signs TLS; certificate verification is never disabled.
    """
    bundle = os.getenv('RT_CA_BUNDLE')
    verify = ssl.create_default_context(cafile=bundle) if bundle else True
    return httpx.Client(proxy=os.getenv('GEMINI_PROXY') or None, verify=verify,
                        timeout=httpx.Timeout(150, connect=15), trust_env=False)

def _choose(model):
    seen=set()
    keys=set()
    for project,key in credentials():
        project = project.strip() or 'gemini-shared'
        if not key or project in seen or key in keys:
            continue
        seen.add(project)
        keys.add(key)
        state=one('SELECT * FROM provider_state WHERE project=? AND model=?',(project,model))
        if state and state['status']=='disabled':
            continue
        yield project,key

def _local_refusal(exc):
    if isinstance(exc, QuotaRefusal):
        return exc
    # Compatibility for old adapters/fixtures; this is only called around reserve,
    # never around a sent request. Unknown ModelError messages fail closed.
    text = str(exc)
    for prefix, scope, code in [('项目日额度', 'project', 'project_daily'),
                                ('project daily quota exhausted', 'project', 'project_daily'),
                                ('项目分钟额度', 'transient', 'project_window')]:
        if text.startswith(prefix):
            return QuotaRefusal(text, scope=scope, code=code)
    return None

def request(model,method,body,run_id,estimate):
    mode=os.getenv('RT_PROVIDER_MODE','all')
    if mode not in ('all','embedding_only','generation_only','disabled'):
        raise QuotaRefusal('供应商运行用途配置无效',scope='global',code='budget_configuration')
    embedding=model==EMBED
    if mode=='disabled' or (mode=='embedding_only' and not embedding) or (mode=='generation_only' and embedding):
        raise QuotaRefusal('该用途由另一运行环境统一计账，本机未发送请求',scope='global',code='purpose_disabled')
    # Conservative 1 token per UTF-8 byte reserve; correct with actual usage.
    # Retry only unsent local reservations; no sent retries or paid fallback.
    qid=None
    for attempt in range(15):
        refused = []
        for project,key in _choose(model):
            try:
                units=len(body.get('requests',[])) if method=='batchEmbedContents' else 0 if method=='countTokens' else 1
                qid=reserve(project,model,estimate,run_id,request_units=units) if units!=1 else reserve(project,model,estimate,run_id)
                break
            except ModelError as exc:
                local = _local_refusal(exc)
                if local is None or local.scope == 'global':
                    raise
                refused.append(local)
                if run_id:
                    event(run_id,'quota_route_refused',{'project':project,'model':model,'scope':local.scope,'code':local.code})
        if qid is not None:
            break
        if not refused:
            raise QuotaRefusal('模型未配置或已停用；无可用免费路由', scope='global', code='no_route')
        transient = next((exc for exc in refused if exc.scope == 'transient'), None)
        if transient is None or attempt == 14:
            raise transient or refused[-1]
        if run_id and attempt==0:
            event(run_id,'quota_wait',{'model':model,'scope':'transient','message':'等待项目分钟窗口；尚未发送请求，不消耗请求次数'})
        time.sleep(5)
    if run_id:
        event(run_id,'model_request',{'model':model,'project':project,'quota_id':qid,'reserved_input_tokens':estimate,'method':method,
                                      'core_calls':workflow_budget(run_id)})
    result=None
    status='unknown'
    detail=''
    usage={}
    try:
        endpoint=f'{BASE}/models/{model}:{method}'
        if method=='createDecision':
            if model!='gemini-decision-1' or body.get('model')!=model:raise ValueError('Decision模型与请求不一致')
            endpoint=BASE+'/decisions'
        with client() as c:
            response=c.post(endpoint,headers={'x-goog-api-key':key},json=body)
        if response.status_code!=200:
            error={}
            try:
                payload=response.json()
                error=payload.get('error',{}) if isinstance(payload,dict) else {}
                if not isinstance(error,dict):
                    error={}
                category=error.get('status')
                if category not in ('INVALID_ARGUMENT','UNAUTHENTICATED','PERMISSION_DENIED','NOT_FOUND',
                                     'RESOURCE_EXHAUSTED','FAILED_PRECONDITION','ABORTED','OUT_OF_RANGE',
                                     'UNIMPLEMENTED','INTERNAL','UNAVAILABLE','DATA_LOSS','DEADLINE_EXCEEDED'):
                    category='HTTP_ERROR'
                message=error.get('message','')
            except ValueError:
                category='INVALID_RESPONSE'
                message=''
            if (isinstance(message,str) and 'FreeTierOnly' in message) or response.status_code in (401,403,404):
                status='disabled'
            else:
                status='failed'
            # Only controlled categories exposed, never raw upstream URL/body/headers.
            detail=f'HTTP {response.status_code} {category}'
            if response.status_code==429:
                # Retain machine-readable quota diagnostics without upstream
                # messages, signed URLs, keys or arbitrary response text.
                import re
                diagnostics=[]
                for item in error.get('details',[]) if isinstance(error.get('details',[]),list) else []:
                    if not isinstance(item,dict):continue
                    delay=item.get('retryDelay')
                    if isinstance(delay,str) and re.fullmatch(r'\d+(?:\.\d+)?s',delay):diagnostics.append({'retry_delay':delay})
                    for v in item.get('violations',[]) if isinstance(item.get('violations',[]),list) else []:
                        if not isinstance(v,dict):continue
                        entry={}
                        for field in ('quotaMetric','quotaId','quotaValue'):
                            value=str(v.get(field,''))
                            if re.fullmatch(r'[A-Za-z0-9_./:-]{1,200}',value):entry[field]=value
                        if entry:diagnostics.append(entry)
                if diagnostics:
                    usage['quota_diagnostics']=diagnostics
                    if run_id:event(run_id,'provider_quota_exhausted',{'model':model,'diagnostics':diagnostics})
            raise SentRequestError(f'{model} {detail}；请求已记账，无自动付费兜底', outcome=status, quota_id=qid,
                                   http_status=response.status_code)
        result=response.json()
        if not isinstance(result,dict):
            raise ValueError('response must be an object')
        usage=result.get('usageMetadata',{})
        if method=='createDecision':
            actual=result.get('usage',{})
            if not isinstance(actual,dict) or type(actual.get('total_input_tokens')) is not int or actual.get('total_output_tokens')!=0:
                raise ValueError('Decision返回用量缺失或不符合零输出约定')
            usage={'promptTokenCount':actual['total_input_tokens'],'candidatesTokenCount':0,'native_decision_usage':actual}
        if not isinstance(usage,dict):
            usage={}
            raise ValueError('usage must be an object')
        trace_dir=store.DATA/'traces';trace_dir.mkdir(exist_ok=True,mode=0o700)
        trace_path=trace_dir/(qid+'.json')
        trace_path.write_text(json.dumps({'model_requested':model,'quota_id':qid,'received_at':time.time(),'response':result},ensure_ascii=False))
        trace_path.chmod(0o600)
        result['_quota_id']=qid
        status='ok'
        return result,project
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ProxyError, httpx.UnsupportedProtocol) as error:
        # The connection (or proxy tunnel) was never established: nothing was sent.
        status='failed'
        detail='连接未建立，请求未发送（'+type(error).__name__+'）'
        if run_id:event(run_id,'provider_connect_failed',{'model':model,'quota_id':qid,'error_type':type(error).__name__})
        raise SentRequestError(detail, outcome='failed', quota_id=qid) from None
    except httpx.HTTPError as error:
        if run_id:event(run_id,'provider_transport_unknown',{'model':model,'quota_id':qid,'error_type':type(error).__name__,'automatic_retry':False})
        detail='网络超时或传输失败；上游消耗未知，保留预留账目'
        raise SentRequestError(detail, outcome='unknown', quota_id=qid) from None
    except ValueError:
        status='failed'
        detail='上游 JSON 无效'
        raise SentRequestError(detail, outcome='failed', quota_id=qid) from None
    finally:
        with db() as c:
            c.execute('UPDATE quota SET status=?,input_tokens=?,output_tokens=?,usage=? WHERE id=?',(status,_usage_count(usage,'promptTokenCount',estimate),_usage_count(usage,'candidatesTokenCount')+_usage_count(usage,'thoughtsTokenCount'),json.dumps(usage),qid))
            c.execute('INSERT OR REPLACE INTO provider_state VALUES(?,?,?,?,?)',(project,model,status,detail,time.time()))

def _usage_count(usage, key, default=0):
    value = usage.get(key, default)
    return value if type(value) is int and 0 <= value <= 2147483647 else default

def workflow_budget(run_id):
    """Sanitized progress for an already authorized run; counts reservations too."""
    policy = budget_policy()
    with db() as c:
        prior, limit = _workflow_context(c, run_id, policy['workflow_limit'])
        used = c.execute('SELECT COUNT(*) FROM quota WHERE model=? AND run_id=?', (CORE,run_id)).fetchone()[0]
    return {'profile':prior['profile'] if prior else policy['profile'],
            'estimated_core_calls':1,'limit':limit,'used':used,'remaining':max(0,limit-used)}

ROLE_ENV = {'deep': 'RT_MODEL_DEEP', 'answer': 'RT_MODEL_ANSWER', 'light': 'RT_MODEL_LIGHT',
            'verify': 'RT_MODEL_VERIFY'}
# Local refusals after which trying the next model of a role chain is legitimate.
# Run-wide caps, cancellation and configuration errors are never bypassed.
_DOWNGRADE_CODES = {'profile_budget', 'workspace_budget', 'workflow_budget', 'model_daily',
                    'project_daily', 'project_soft_daily', 'project_window', 'no_route'}


def role_chain(role):
    """Ordered model ids for a role, from operator configuration.

    deep   – cross-paper synthesis, surveys, audits (default: the core model)
    answer – single-paper answers (default: the deep chain)
    light  – routing, planning, extraction, translation (default: the batch model)
    verify – independent claim review (default: the deep chain, as before)
    Without configuration every chain has exactly the legacy single model.
    """
    if role not in ROLE_ENV:
        raise ValueError('未知模型角色')
    raw = os.getenv(ROLE_ENV[role], '')
    if not raw and role in ('answer', 'verify'):
        raw = os.getenv(ROLE_ENV['deep'], '')
    chain = [m.strip() for m in raw.split(',') if m.strip()]
    if not all(m.isascii() and len(m) <= 80 and m.replace('-', '').replace('.', '').replace('_', '').isalnum() for m in chain):
        raise QuotaRefusal('模型角色配置无效', scope='global', code='budget_configuration')
    return list(dict.fromkeys(chain)) or [BATCH if role == 'light' else CORE]


def generate(system,prompt,run_id,core=True,role=None,json_output=True,response_schema=None):
    """Generate with the first usable model of the role chain.

    A later model is tried only when the earlier one was refused locally for
    its own budget, or the provider returned a definite error response. A sent
    request whose outcome is unknown (timeout) is never repeated. Every attempt
    stays in the ledger, and the result names the model that actually answered
    plus the models that were skipped, so the UI can label a downgrade.
    """
    chain = role_chain(role or ('deep' if core else 'light'))
    skipped = []
    overloaded = None  # first model that answered 503 (overloaded): one delayed retry
    retried = False
    index = 0
    while index < len(chain):
        model = chain[index]
        last = index == len(chain) - 1
        try:
            options={'response_schema':response_schema} if response_schema else {}
            result = _generate_once(model, system, prompt, run_id, json_output=json_output,**options)
        except QuotaRefusal as exc:
            if last or exc.code not in _DOWNGRADE_CODES:
                raise
            reason = exc.code
        except SentRequestError as exc:
            if exc.outcome == 'unknown':
                raise
            if exc.http_status == 503 and overloaded is None:
                overloaded = index
            if last:
                # A definite overload answer is retried once, after a pause, on
                # the best overloaded model; the retry is a new counted request.
                if overloaded is not None and not retried and not (run_id and store.cancelled(run_id)):
                    retried = True
                    if run_id:
                        event(run_id, 'provider_overload_retry', {'model': chain[overloaded], 'wait_seconds': 4})
                    time.sleep(4)
                    index = overloaded
                    continue
                raise
            reason = 'provider_' + exc.outcome
        except ModelError:
            # Truncated or empty output: the provider answered, the call is counted.
            if last:
                raise
            reason = 'unusable_output'
        else:
            if skipped:
                result['downgraded_from'] = skipped
            return result
        skipped.append({'model': model, 'reason': reason})
        if run_id:
            event(run_id, 'model_downgraded', {'from': model, 'to': chain[index + 1], 'reason': reason})
        index += 1
    raise ModelError('没有可用模型')


def _generate_once(model, system, prompt, run_id, json_output=True,response_schema=None):
    core = model == CORE
    text_bytes=len((system+prompt).encode())
    config = {'maxOutputTokens': 16384 if core or (text_bytes > 20000) else 8192}
    if json_output:
        config['responseMimeType'] = 'application/json'
    if response_schema:
        config['responseSchema']=response_schema
    payload={'systemInstruction':{'parts':[{'text':system}]},'contents':[{'role':'user','parts':[{'text':prompt}]}],
             'generationConfig':config}
    data,project=request(model,'generateContent',payload,run_id,text_bytes+1024)
    candidates=data.get('candidates',[])
    if not candidates or candidates[0].get('finishReason')!='STOP':
        reason=candidates[0].get('finishReason','EMPTY') if candidates else 'EMPTY'
        with db() as c:
            c.execute("UPDATE quota SET status='failed_output' WHERE id=?",(data.get('_quota_id'),))
        raise ModelError(f'模型输出未完整结束（{reason}）；未发布为完成结果')
    text=''.join(p.get('text','') for p in candidates[0].get('content',{}).get('parts',[]) if not p.get('thought'))
    if not text:
        raise ModelError('模型未返回可用内容')
    return {'text':text,'model':data.get('modelVersion',model),'requested_model':model,'usage':data.get('usageMetadata',{}),'project':project}

def embed(texts,run_id,task='RETRIEVAL_DOCUMENT'):
    if not texts:
        return {'vectors':[],'model':EMBED,'dimension':0}
    if len(texts)>32:
        raise ModelError('embedding batch 超过32条')
    requests=[{'model':f'models/{EMBED}','content':{'parts':[{'text':t}]},'taskType':task,'outputDimensionality':768} for t in texts]
    data,_=request(EMBED,'batchEmbedContents',{'requests':requests},run_id,sum(len(t.encode()) for t in texts)+128)
    vectors=[x['values'] for x in data.get('embeddings',[])]
    if len(vectors)!=len(texts) or not vectors or any(len(x)!=len(vectors[0]) for x in vectors):
        raise ModelError('embedding 返回数量或维度不符')
    return {'vectors':vectors,'model':EMBED,'dimension':len(vectors[0])}

def provider_report():
    projects=list(dict.fromkeys(p for p,k in credentials() if k))
    active = os.getenv('RT_BUDGET_PROFILE','smoke')
    profiles=[]
    with db() as c:
        for profile, name in PROFILE_LIMITS.items():
            used=_profile_used(c,profile)
            try:
                cap=_budget_number(name,4 if profile=='smoke' else None,0 if profile=='smoke' else 1)
                error=None
            except QuotaRefusal as exc:
                cap=None
                error=exc.code
            profiles.append({'profile':profile,'active':profile==active,'configured':cap is not None,
                             'limit':cap,'used':used,'remaining':max(0,cap-used) if cap is not None else None,
                             'configuration_error':error})
        # Aggregate caps only. Do not expose other workspaces' run IDs or payloads.
        pinned=[dict(row) for row in c.execute('''SELECT profile,workflow_limit,COUNT(*) workflows FROM (
            SELECT COALESCE(x.profile,'smoke') profile,MIN(COALESCE(x.workflow_limit,2)) workflow_limit
            FROM quota q LEFT JOIN quota_context x ON x.quota_id=q.id WHERE q.run_id IS NOT NULL
            GROUP BY q.run_id) GROUP BY profile,workflow_limit''')]
    try:
        policy=budget_policy()
        config_error=None
    except QuotaRefusal as exc:
        policy=None
        config_error=exc.code
    return {'configured':bool(projects),'paid_fallback':False,'reset_at':reset_at(),'remaining_balance':'未知；下列是本应用本地账目，其他业务用量未知',
        'projects':projects,'models':[{'model':m,'rpm':limits(m)[0],'tpm':limits(m)[1],'rpd':limits(m)[2]} for m in ((CORE,BATCH,EMBED,'gemini-decision-1') if os.getenv('RT_DECISION_ENABLED')=='true' else (CORE,BATCH,EMBED))],
        'status':rows('SELECT * FROM provider_state'),'usage':rows('''SELECT q.project,q.model,q.day,COUNT(*) calls,
            SUM(COALESCE(u.units,1)) provider_request_units,
            SUM(CASE WHEN u.source='legacy_upper_bound' THEN 1 ELSE 0 END) conservative_legacy_attempts,
            SUM(q.input_tokens) input_tokens,SUM(q.output_tokens) output_tokens
            FROM quota q LEFT JOIN quota_request_units u ON u.quota_id=q.id GROUP BY q.project,q.model,q.day'''),
        'hydrogen_total_used':one('SELECT COUNT(*) n FROM quota WHERE model=?',(CORE,))['n'],
        'hydrogen_budget':policy['limit'] if policy else None,'mode':active if active in PROFILE_LIMITS else 'invalid',
        'profiles':profiles,'budget_configuration_error':config_error,
        'workflow_limit':policy['workflow_limit'] if policy else None,'workflow_pinned_caps':pinned,
        'runtime_soft_rpd':policy['runtime_soft_rpd'] if policy else None}
