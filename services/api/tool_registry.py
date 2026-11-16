"""Schema checked, workspace scoped Agent tools with a durable <=10-call budget.

No model/provider calls are authorized here. Audit plans stay BLOCKED: the four
Hydrogen smoke requests are consumed, and jobs.audit has no per-child request
budget enforcement. QA integration must preserve the `tool_registry` namespace
when subsequently saving its own checkpoint (jobs.checkpoint currently replaces
its input). Tool content is untrusted data, never shell, paths or instructions.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
import io
import json
import math
import os
import re
import time
from typing import Annotated, Callable, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from . import charts, documents, research, retrieval, snapshots, store

SafeID = Annotated[str, StringConstraints(pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$')]
BlockID = Annotated[str, StringConstraints(pattern=r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}$')]
Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
MAX_ARGS = 256 * 1024
MAX_RESULT = 192 * 1024
AUDIT_BLOCKER = ('This tool has provider_budget=0: a parent tool plan does not authorize child model calls. '
                 'Start an independently budgeted audit through the authenticated ideas/audits workflow. '
                 'Original smoke ledger remains preserved; evaluation/judging budgets are separate.')


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False, frozen=True)


class ToolContext(StrictModel):
    """Construct in trusted application code; never deserialize model output here."""
    workspace: SafeID
    run_id: SafeID = Field(validation_alias=AliasChoices('run_id', 'runid'))
    budget: int = Field(default=10, ge=0, le=10)
    provider_budget: Literal[0] = 0
    call_id: SafeID | None = None


class SearchPapers(StrictModel):
    query: Question
    sources: list[Literal['arxiv', 'crossref']] = Field(default_factory=lambda: ['arxiv', 'crossref'], min_length=1, max_length=2)
    limit: int = Field(default=5, ge=1, le=10)


class ResolveReference(StrictModel):
    reference_id: BlockID


class FetchDocument(StrictModel):
    # No URL input. The only download route is a verified arXiv search candidate.
    search_artifact_id: SafeID
    paper_index: int = Field(ge=0, le=9)


class ParseDocument(StrictModel):
    version_id: SafeID
    engine: Literal['native', 'paddleocr', 'paddleocr_vl', 'mineru'] = 'native'
    device: Literal['cpu', 'gpu'] = 'cpu'


class RetrieveEvidence(StrictModel):
    version_ids: list[SafeID] = Field(min_length=1, max_length=10)
    question: Question
    limit: int = Field(default=8, ge=1, le=20)
    queries: list[str] = Field(default_factory=list, max_length=4)


class CompareVersions(StrictModel):
    left: SafeID
    right: SafeID


class BuildCitationGraph(StrictModel):
    pass


class AuditResearchQuestion(StrictModel):
    version_id: SafeID
    block_id: BlockID
    question: Question


class ComputeCSVStats(StrictModel):
    csv_text: str = Field(min_length=1, max_length=131072)
    filename: str = Field(default='dataset.csv', pattern=r'^[A-Za-z0-9_-]{1,80}\.csv$')


class RenderChart(StrictModel):
    dataset_artifact_id: SafeID
    spec: charts.PlotSpec


class SaveArtifact(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=24000)
    version_ids: list[SafeID] = Field(default_factory=list, max_length=10)
    block_ids: list[BlockID] = Field(default_factory=list, max_length=24)
    artifact_ids: list[SafeID] = Field(default_factory=list, max_length=10)


class ToolError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _check(ctx):
    run = store.one('SELECT id,workspace,status FROM runs WHERE id=?', (ctx.run_id,))
    if not run or run['workspace'] != ctx.workspace:
        raise ToolError('scope_denied', 'Run does not belong to this workspace')
    if run['status'] == 'cancelled':
        cancel_tool_children(ctx)
        raise ToolError('cancelled', 'Parent run cancelled; no further tools may start')
    if run['status'] not in ('queued', 'running'):
        raise ToolError('run_not_active', 'Parent run is not active')
    return run


def cancel_tool_children(ctx: ToolContext):
    """Main cancellation may call this to stop only this registry's own children.

    Setting durable child status lets the existing worker/parser cancellation
    path release resources; this function never claims an in-flight subprocess
    has already exited.
    """
    with store.db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        parent = conn.execute('SELECT checkpoint,workspace,status FROM runs WHERE id=?', (ctx.run_id,)).fetchone()
        if not parent or parent['workspace'] != ctx.workspace:
            raise ToolError('scope_denied', 'Run does not belong to this workspace')
        if parent['status'] != 'cancelled':
            return []
        state = json.loads(parent['checkpoint'] or '{}').get('tool_registry', {})
        children = state.get('child_run_ids', [])[:10]
        for child in children:
            conn.execute("UPDATE runs SET status='cancelled',updated=? WHERE id=? AND workspace=? AND json_extract(payload,'$.parent_run_id')=? AND status IN ('queued','running','blocked')",
                         (time.time(), child, ctx.workspace, ctx.run_id))
        return children


def _version(ctx, version_id):
    row = store.one('SELECT * FROM versions WHERE id=? AND workspace=? AND deleted=0', (version_id, ctx.workspace))
    if not row:
        raise ToolError('scope_denied', 'Version unavailable in this workspace')
    return row


def _artifact(ctx, aid, kind=None):
    row = store.one('SELECT * FROM artifacts WHERE id=? AND workspace=?', (aid, ctx.workspace))
    if not row or (kind and row['kind'] != kind):
        raise ToolError('scope_denied', 'Artifact unavailable or wrong kind')
    if len(row['payload'].encode()) > MAX_ARGS:
        raise ToolError('resource_limit', 'Artifact exceeds tool input bounds')
    return {**row, 'payload': json.loads(row['payload'])}


def _block(ctx, bid, vid=None):
    row = store.one('SELECT * FROM blocks WHERE id=? AND workspace=?', (bid, ctx.workspace))
    if not row or (vid is not None and row['version_id'] != vid):
        raise ToolError('scope_denied', 'Block unavailable in the requested version/workspace')
    _version(ctx, row['version_id'])
    return row


def _record_child(ctx, child_id, *, owned=True):
    """Only newly created children are cancellation targets, never shared jobs."""
    if not owned:
        return
    with store.db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT checkpoint,status FROM runs WHERE id=? AND workspace=?', (ctx.run_id, ctx.workspace)).fetchone()
        snap = json.loads(row['checkpoint'])
        state = snap['tool_registry']
        child = conn.execute('SELECT payload FROM runs WHERE id=? AND workspace=?', (child_id, ctx.workspace)).fetchone()
        if not child:
            raise ToolError('scope_denied', 'Nested job unavailable in this workspace')
        payload = json.loads(child['payload'])
        if payload.get('parent_run_id', ctx.run_id) != ctx.run_id:
            raise ToolError('scope_denied', 'Nested job is owned by a different parent')
        payload.update(parent_run_id=ctx.run_id, provider_budget=0, index_dense=False)
        conn.execute('UPDATE runs SET payload=? WHERE id=?', (_dump(payload), child_id))
        children = state.setdefault('child_run_ids', [])
        if child_id not in children:
            if len(children) >= 10:
                raise ToolError('budget_exhausted', 'Nested child task budget exhausted')
            children.append(child_id)
        conn.execute('UPDATE runs SET checkpoint=?,updated=? WHERE id=?', (_dump(snap), time.time(), ctx.run_id))
        if row['status'] == 'cancelled':
            conn.execute("UPDATE runs SET status='cancelled',updated=? WHERE id=? AND workspace=? AND status IN ('queued','running','blocked')", (time.time(), child_id, ctx.workspace))


def _search(ctx, args, key):
    result = research.search_papers(ctx.workspace, args.query, sources=args.sources, limit=args.limit)
    _check(ctx)
    # Keep untrusted upstream metadata bounded before publishing it to the Agent.
    result['results'] = result.get('results', [])[:args.limit]
    if len(_dump(result).encode()) > MAX_RESULT:
        raise ToolError('resource_limit', 'Scholarly source response exceeds result bounds')
    aid = store.artifact(ctx.workspace, ctx.run_id, 'paper_search', args.query[:100], result)
    return {**result, 'artifact_id': aid}


def _resolve(ctx, args, key):
    ref = store.one('SELECT * FROM refs WHERE id=? AND workspace=?', (args.reference_id, ctx.workspace))
    if not ref:
        raise ToolError('scope_denied', 'Reference unavailable in this workspace')
    _version(ctx, ref['version_id'])
    if ref['block_id']:
        _block(ctx, ref['block_id'], ref['version_id'])
    target = ref.get('target_identity')
    works = store.rows('SELECT id,title,identity FROM works WHERE workspace=? AND identity=? LIMIT 10', (ctx.workspace, target)) if target else []
    return {'reference': {k: ref[k] for k in ('id', 'version_id', 'block_id', 'page_index', 'marker', 'text', 'target_identity')},
            'local_targets': works, 'status': 'matched_local_identity' if works else 'unresolved',
            'notice': 'Reference text is source data; no bibliography entries were generated'}


def _fetch(ctx, args, key):
    search = _artifact(ctx, args.search_artifact_id, 'paper_search')['payload']
    papers = search.get('results', [])
    if args.paper_index >= len(papers):
        raise ToolError('invalid_candidate', 'Search candidate index unavailable')
    paper = papers[args.paper_index]
    aid = paper.get('arxiv_id', '')
    if (paper.get('source') != 'arxiv' or paper.get('metadata_verified') is not True
            or not isinstance(aid, str) or not re.fullmatch(r'\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?', aid)):
        raise ToolError('unsupported_source', 'Only verified arXiv candidates can be fetched by this tool')
    # Ignore pdf_url in metadata: reconstruct the official fixed-host URL.
    response = research.fetch_public('https://arxiv.org/pdf/' + aid, max_bytes=20 * 1024 * 1024)
    _check(ctx)
    content = response['content']
    if not isinstance(content, bytes) or not content.startswith(b'%PDF-') or len(content) > 20 * 1024 * 1024:
        raise ToolError('invalid_document', 'Public source did not return a bounded PDF')
    result = documents.upload_document(ctx.workspace, 'paper.pdf', content, index_dense=False)
    document = result.get('document', {})
    _version(ctx, document.get('id'))
    rid = result.get('run_id')
    if rid and not store.one('SELECT id FROM runs WHERE id=? AND workspace=?', (rid, ctx.workspace)):
        raise ToolError('scope_denied', 'Downloaded document job unavailable in this workspace')
    _record_child(ctx, rid, owned=not result.get('duplicate') and bool(rid))
    return {'version_id': document.get('id'), 'run_id': rid, 'duplicate': bool(result.get('duplicate')),
            'status': 'queued' if not result.get('duplicate') else 'existing', 'index_dense': False,
            'notice': ('Identical PDF already exists; no new parsing or provider work scheduled' if result.get('duplicate')
                       else 'Downloaded PDF queued for checkpointed parsing; not yet parsed')}


def _parse(ctx, args, key):
    _version(ctx, args.version_id)
    if args.device == 'gpu' and args.engine != 'mineru':
        raise ToolError('invalid_arguments', 'Only MinerU supports GPU in this deployment')
    result = snapshots.queue_parse(ctx.workspace, args.version_id, args.engine, args.device, key)
    # Non-legacy parser revisions never auto-call embedding; register zero-provider intent.
    _record_child(ctx, result['run_id'])
    return {**result, 'index_dense': False, 'provider_budget': 0, 'notice': 'Queued a new immutable parser revision; old evidence is retained'}


def _retrieve(ctx, args, key):
    vids = list(dict.fromkeys(args.version_ids))
    for vid in vids:
        _version(ctx, vid)
    queries=[q[:300] for q in args.queries if q.strip()]
    if os.getenv('RT_EMBED_PROVIDER')=='local':
        return retrieval.retrieve(ctx.workspace,vids,args.question,limit=args.limit,queries=queries)
    # Keyword lists only (question + rewrites, per-document quotas, neighbour context);
    # no cloud question embedding is sent from a tool call.
    result=retrieval.retrieve(ctx.workspace,vids,args.question,limit=args.limit,queries=queries,
                              allow_cloud_dense=False)
    result['notice']='本地关键词检索（含改写查询与逐篇配额）；未提交云端问题向量，不冒充语义召回'
    return result


def _compare(ctx, args, key):
    for vid in (args.left, args.right):
        _version(ctx, vid)
        bound = store.one('SELECT count(*) n,COALESCE(sum(length(text)),0) chars FROM current_blocks WHERE workspace=? AND version_id=?', (ctx.workspace, vid))
        if bound['n'] > 500 or bound['chars'] > 500000:
            raise ToolError('resource_limit', 'Comparison limited to 500 blocks / 500000 characters per version')
    result = documents.compare_versions(ctx.workspace, args.left, args.right)
    changes = result['changes'][:40]
    # Never imply an abbreviated diff contains all changed source text.
    for change in changes:
        for side in ('before', 'after'):
            block = change.get(side)
            if block and len(block['text']) > 1200:
                block['text'] = block['text'][:1200]
                block['text_truncated'] = True
    return {**result, 'changes': changes, 'changes_truncated': len(result['changes']) > 40}


def _graph(ctx, args, key):
    bound = store.one('SELECT count(*) n,COALESCE(sum(length(metadata)),0) chars FROM works WHERE workspace=?', (ctx.workspace,))
    refs = store.one('SELECT count(*) n,COALESCE(sum(length(text)),0) chars FROM refs WHERE workspace=?', (ctx.workspace,))
    if bound['n'] > 100 or bound['chars'] > 500000 or refs['n'] > 2000 or refs['chars'] > 500000:
        raise ToolError('resource_limit', 'Graph tool limited to 100 works, 2000 references and 500000 metadata characters')
    return research.build_graph(ctx.workspace)


def _audit(ctx, args, key):
    _version(ctx, args.version_id)
    _block(ctx, args.block_id, args.version_id)
    payload = {**args.model_dump(), 'provider_budget': 0, 'parent_run_id': ctx.run_id,
               'upstream_budget_required': True, 'budget_blocker': AUDIT_BLOCKER}
    # Never queue then mark blocked: a concurrent worker could pick it up first.
    with store.db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        existing = conn.execute('SELECT id,status FROM runs WHERE workspace=? AND idempotency=?', (ctx.workspace, key)).fetchone()
        if existing:
            rid = existing['id']
        else:
            rid = store.uid()
            now = time.time()
            conn.execute('INSERT INTO runs(id,workspace,kind,status,payload,error,idempotency,created,updated) VALUES(?,?,?,?,?,?,?,?,?)',
                         (rid, ctx.workspace, 'audit', 'blocked', _dump(payload), AUDIT_BLOCKER, key, now, now))
    _record_child(ctx, rid)
    return {'status': 'BLOCKED', 'run_id': rid, 'reason': AUDIT_BLOCKER, 'provider_requests': 0,
            'notice': 'Persistent audit plan only; no search, embedding or Hydrogen inference has run'}


def _csv(ctx, args, key):
    content = args.csv_text.encode('utf-8')
    if len(content) > 131072 or '\x00' in args.csv_text:
        raise ToolError('resource_limit', 'CSV limited to 128 KiB without NUL')
    text, encoding = charts._decode(content)
    reader = csv.DictReader(io.StringIO(text), strict=True)
    columns = reader.fieldnames
    if not columns or len(columns) > 32 or len(set(columns)) != len(columns) or any(not c or len(c) > 200 for c in columns):
        raise ToolError('invalid_csv', 'CSV requires 1..32 distinct bounded column names')
    records = []
    for row in reader:
        if None in row or any(v is None for v in row.values()):
            raise ToolError('invalid_csv', 'CSV row width differs from its header')
        records.append(row)
        if len(records) > 2000:
            raise ToolError('resource_limit', 'CSV limited to 2000 rows')
    if not records:
        raise ToolError('invalid_csv', 'CSV has no data rows')
    stats = {}
    for col in columns:
        values = [charts._num(row[col]) for row in records]
        numbers = [x for x in values if x is not None]
        missing = sum(not row[col].strip() for row in records)
        if numbers:
            total = math.fsum(numbers)
            if not math.isfinite(total):
                raise ToolError('invalid_csv', 'CSV statistics exceed finite numeric bounds')
            stats[col] = {'count': len(numbers), 'sum': total, 'mean': total / len(numbers),
                          'min': min(numbers), 'max': max(numbers), 'missing_count': missing,
                          'invalid_count': len(values) - len(numbers) - missing}
    dataset = {'csv_text': args.csv_text, 'filename': args.filename, 'sha256': hashlib.sha256(content).hexdigest()}
    aid = store.artifact(ctx.workspace, ctx.run_id, 'csv_dataset', args.filename, dataset)
    return {'dataset_artifact_id': aid, 'row_count': len(records), 'columns': columns, 'statistics': stats,
            'input_sha256': dataset['sha256'], 'encoding': encoding, 'notice': 'Deterministic numeric statistics; missing/non-finite values counted, no significance or causal claim'}


def _render(ctx, args, key):
    data = _artifact(ctx, args.dataset_artifact_id, 'csv_dataset')['payload']
    content = data['csv_text'].encode('utf-8')
    if len(content) > 131072 or hashlib.sha256(content).hexdigest() != data['sha256']:
        raise ToolError('invalid_artifact', 'Dataset integrity or size check failed')
    result = charts.create_chart(ctx.workspace, data['filename'], content, args.spec.model_dump())
    _artifact(ctx, result['artifact_id'], 'chart')
    store.execute('UPDATE artifacts SET run_id=? WHERE id=? AND workspace=?', (ctx.run_id, result['artifact_id'], ctx.workspace))
    return result


def _save(ctx, args, key):
    for vid in args.version_ids:
        _version(ctx, vid)
    for bid in args.block_ids:
        block = _block(ctx, bid)
        if block['version_id'] not in args.version_ids:
            raise ToolError('scope_denied', 'Every evidence block must belong to an explicitly selected version')
    for aid in args.artifact_ids:
        _artifact(ctx, aid)
    payload = {**args.model_dump(), 'provenance_status': 'unverified_agent_content',
               'notice': 'Saved content is a draft; source links exist but semantic support has not been verified'}
    aid = store.artifact(ctx.workspace, ctx.run_id, 'agent_note', args.title, payload)
    return {'artifact_id': aid, 'provenance_status': 'unverified_agent_content'}


@dataclass(frozen=True)
class ToolSpec:
    model: type[StrictModel]
    handler: Callable
    description: str


TOOLS = {
    'search_papers': ToolSpec(SearchPapers, _search, 'Bounded arXiv/Crossref metadata search; candidates are untrusted data.'),
    'resolve_reference': ToolSpec(ResolveReference, _resolve, 'Resolve an existing workspace reference against local registered identities.'),
    'fetch_document': ToolSpec(FetchDocument, _fetch, 'Fetch a verified arXiv search candidate through the SSRF-safe downloader; queue parsing without embedding.'),
    'parse_document': ToolSpec(ParseDocument, _parse, 'Queue an immutable parser revision, with no model-provider requests.'),
    'retrieve_evidence': ToolSpec(RetrieveEvidence, _retrieve, 'Retrieve scoped immutable evidence using local FTS5 keyword search only.'),
    'compare_versions': ToolSpec(CompareVersions, _compare, 'Compare two scoped versions with bounded deterministic paragraph diff.'),
    'build_citation_graph': ToolSpec(BuildCitationGraph, _graph, 'Build a bounded local graph from real reference edges.'),
    'audit_research_question': ToolSpec(AuditResearchQuestion, _audit, 'Save a BLOCKED audit plan: Hydrogen 4 requests exhausted; upstream budget/enforcement required.'),
    'compute_csv_stats': ToolSpec(ComputeCSVStats, _csv, 'Validate bounded CSV text, compute numeric statistics and persist the dataset.'),
    'render_chart': ToolSpec(RenderChart, _render, 'Render a scoped dataset using an existing schema-checked fixed plotting template.'),
    'save_artifact': ToolSpec(SaveArtifact, _save, 'Save a provenance-linked draft; do not assert citations or model content were verified.'),
}


def tool_schemas():
    """JSON Schema contracts, suitable for a function-calling adapter."""
    return [{'type': 'function', 'function': {'name': name, 'description': spec.description,
            'parameters': spec.model.model_json_schema()}} for name, spec in TOOLS.items()]


def _reserve(ctx, call_id, name, digest):
    with store.db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT workspace,status,checkpoint FROM runs WHERE id=?', (ctx.run_id,)).fetchone()
        if not row or row['workspace'] != ctx.workspace:
            raise ToolError('scope_denied', 'Run does not belong to this workspace')
        if row['status'] not in ('queued', 'running'):
            raise ToolError('cancelled' if row['status'] == 'cancelled' else 'run_not_active', 'Parent run is not active')
        snap = json.loads(row['checkpoint'] or '{}')
        if not isinstance(snap, dict):
            raise ToolError('invalid_checkpoint', 'Expected an object checkpoint')
        state = snap.setdefault('tool_registry', {'limit': ctx.budget, 'calls': [], 'child_run_ids': []})
        if not isinstance(state, dict) or not isinstance(state.get('limit'), int) or not isinstance(state.get('calls'), list):
            raise ToolError('invalid_checkpoint', 'Invalid tool budget checkpoint')
        state['limit'] = min(state['limit'], ctx.budget, 10)
        for call in state['calls']:
            if call['id'] == call_id:
                if call['name'] != name or call['digest'] != digest:
                    raise ToolError('idempotency_conflict', 'Tool call ID already used for different arguments')
                conn.execute('UPDATE runs SET checkpoint=?,updated=? WHERE id=?', (_dump(snap), time.time(), ctx.run_id))
                return call, True
        if len(state['calls']) >= state['limit']:
            raise ToolError('budget_exhausted', 'Durable tool call budget exhausted (maximum 10 including failed attempts)')
        record = {'id': call_id, 'name': name, 'digest': digest, 'status': 'RUNNING', 'started': time.time()}
        state['calls'].append(record)
        conn.execute('UPDATE runs SET checkpoint=?,updated=? WHERE id=?', (_dump(snap), time.time(), ctx.run_id))
        conn.execute('INSERT INTO steps(run_id,event,data,created) VALUES(?,?,?,?)',
                     (ctx.run_id, 'tool_started', _dump({'tool': name[:80], 'call_id': call_id, 'used': len(state['calls']), 'limit': state['limit']}), time.time()))
        return record, False


def _summary(name, status, result, code=None):
    detail = ''
    if code:
        detail = code
    elif name == 'search_papers':
        detail = f"{len(result.get('results', []))} metadata candidates; cached={bool(result.get('cached'))}"
    elif name == 'retrieve_evidence':
        detail = f"{len(result.get('blocks', []))} blocks; mode=keyword"
    elif name == 'compare_versions':
        counts = result.get('counts', {})
        detail = 'deterministic diff; ' + ', '.join(f'{key}={counts.get(key, 0)}' for key in ('added', 'deleted', 'modified', 'unchanged'))
        detail += '; truncated=' + str(bool(result.get('changes_truncated')))
    elif name == 'build_citation_graph':
        detail = f"{len(result.get('nodes', []))} nodes / {len(result.get('edges', []))} reference edges"
    elif name == 'compute_csv_stats':
        detail = f"{result.get('row_count', 0)} rows / {len(result.get('columns', []))} columns"
    elif name == 'audit_research_question':
        detail = 'blocked persistent plan; Hydrogen budget exhausted; no provider requests'
    elif result.get('run_id'):
        detail = 'child task ' + result['run_id'] + '; status=' + str(result.get('status', 'queued'))
    elif result.get('artifact_id'):
        detail = 'artifact ' + result['artifact_id']
    return f'{name[:80]}: {status}' + ('; ' + detail if detail else '')


def _finish(ctx, call_id, name, status, result, code=None):
    # Keep checkpoint small; complete results reside in a workspace-scoped artifact.
    with store.db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT checkpoint,status FROM runs WHERE id=? AND workspace=?', (ctx.run_id, ctx.workspace)).fetchone()
        snap = json.loads(row['checkpoint'])
        state = snap['tool_registry']
        if row['status'] == 'cancelled':
            status, code = 'BLOCKED', 'cancelled'
            result = {'reason': 'Parent cancelled; any completed side effects remain in its audit trail'}
            for child in state.get('child_run_ids', []):
                conn.execute("UPDATE runs SET status='cancelled',updated=? WHERE id=? AND workspace=? AND json_extract(payload,'$.parent_run_id')=? AND status IN ('queued','running','blocked')", (time.time(), child, ctx.workspace, ctx.run_id))
        envelope = {'tool': name[:80], 'call_id': call_id, 'status': status,
                    'summary': _summary(name, status, result, code),
                    'result': result, 'budget': {'used': len(state['calls']), 'limit': state['limit'], 'provider_requests': 0}}
        if code:
            envelope['code'] = code
        aid = store.uid()
        conn.execute('INSERT INTO artifacts VALUES(?,?,?,?,?,?,?)', (aid, ctx.workspace, ctx.run_id, 'agent_tool_result', name[:80], _dump(envelope), time.time()))
        for call in state['calls']:
            if call['id'] == call_id:
                call.update(status=status, result_artifact_id=aid, finished=time.time())
        conn.execute('UPDATE runs SET checkpoint=?,updated=? WHERE id=?', (_dump(snap), time.time(), ctx.run_id))
        conn.execute('INSERT INTO steps(run_id,event,data,created) VALUES(?,?,?,?)', (ctx.run_id, 'tool_finished',
                     _dump({'tool': name[:80], 'call_id': call_id, 'status': status, 'code': code, 'summary': envelope['summary'], 'result_artifact_id': aid}), time.time()))
        return {**envelope, 'tool_result_artifact_id': aid, 'replayed': False}


def execute_tool(ctx: ToolContext, name: str, args: dict) -> dict:
    """Execute one tool attempt. Stable ctx.call_id makes retries replay-safe.

    Failed/blocked calls consume the durable budget. RUNNING calls recovered after
    a crash are indeterminate and never automatically repeated. No URL, shell,
    path or provider-budget escape hatch exists in model-visible schemas.
    """
    if not isinstance(ctx, ToolContext):
        ctx = ToolContext.model_validate(ctx)
    call_id = ctx.call_id or store.uid()
    reserved = False
    try:
        _check(ctx)
        if not isinstance(name, str) or len(name) > 80 or not isinstance(args, dict):
            raise ToolError('invalid_arguments', 'Expected a registered tool name and JSON object')
        try:
            encoded = _dump(args).encode()
        except (ValueError, TypeError, RecursionError):
            raise ToolError('invalid_arguments', 'Arguments must be finite JSON data') from None
        if len(encoded) > MAX_ARGS:
            raise ToolError('resource_limit', 'Tool arguments exceed 256 KiB')
        record, replay = _reserve(ctx, call_id, name, hashlib.sha256(encoded).hexdigest())
        if replay:
            if record['status'] == 'RUNNING':
                raise ToolError('indeterminate_call', 'Prior call is in flight or interrupted; inspect its checkpoint, do not repeat side effects')
            aid = record['result_artifact_id']
            return {**_artifact(ctx, aid, 'agent_tool_result')['payload'], 'tool_result_artifact_id': aid, 'replayed': True}
        reserved = True
        spec = TOOLS.get(name)
        if not spec:
            raise ToolError('unknown_tool', 'Tool is not registered')
        try:
            parsed = spec.model.model_validate(args)
        except ValidationError:
            raise ToolError('invalid_arguments', 'Arguments failed the registered schema (extra fields are forbidden)') from None
        _check(ctx)
        result = spec.handler(ctx, parsed, f'tool:{ctx.run_id}:{call_id}')
        if len(_dump(result).encode()) > MAX_RESULT:
            raise ToolError('resource_limit', 'Tool result exceeds 192 KiB; completed side effects are retained for review')
        status = 'BLOCKED' if result.get('status') == 'BLOCKED' else 'PASS'
        return _finish(ctx, call_id, name, status, result)
    except Exception as exc:
        code = exc.code if isinstance(exc, ToolError) else 'tool_failed'
        # Never echo arbitrary upstream exception repr, request arguments or keys.
        message = str(exc) if isinstance(exc, ToolError) else 'Tool failed; no provider request was authorized'
        status = 'BLOCKED' if code in ('cancelled', 'budget_exhausted', 'indeterminate_call', 'run_not_active') else 'FAIL'
        if reserved:
            return _finish(ctx, call_id, name, status, {'reason': message}, code)
        return {'tool': name[:80] if isinstance(name, str) else 'invalid', 'call_id': call_id,
                'status': status, 'code': code, 'summary': message, 'result': {}, 'replayed': False}
