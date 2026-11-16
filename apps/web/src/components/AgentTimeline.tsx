/**
 * Public execution timeline. Each persisted run event is turned into one
 * readable line (who did what, with which model or tool). Raw event data stays
 * one click away; nothing here invents steps or hidden reasoning.
 */
import { useEffect, useState } from 'react';
import {
  AlertCircle,
  Bot,
  CheckCircle2,
  ChevronDown,
  Clock3,
  Database,
  ListChecks,
  ScanSearch,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
  Wand2,
  Workflow,
} from '../icons';
import { parseObject } from '../api';
import type { Step } from '../types';

type Tone = 'agent' | 'model' | 'warn' | 'ok' | 'bad' | 'plain';
interface Line {
  icon: typeof Bot;
  tone: Tone;
  title: string;
  detail?: string;
}

const TOOL_LABELS: Record<string, string> = {
  retrieve_evidence: '检索原文证据',
  compare_versions: '比较版本差异',
  build_citation_graph: '构建引用图谱',
  search_papers: '检索学术数据源',
  resolve_reference: '解析参考文献',
  fetch_document: '获取全文',
  parse_document: '解析文档',
  audit_research_question: '核查研究问题',
  compute_csv_stats: '计算 CSV 统计',
  render_chart: '绘制图表',
  save_artifact: '保存研究笔记',
};

const REASONS: Record<string, string> = {
  model_daily: '当日额度已用完',
  project_daily: '项目日额度已用完',
  project_soft_daily: '保留演示额度',
  project_window: '分钟窗口已满',
  profile_budget: '预算已用完',
  workspace_budget: '本工作区今日预算已用完',
  workflow_budget: '本任务预算已用完',
  provider_failed: '上游返回错误',
  provider_disabled: '上游拒绝访问',
  unusable_output: '输出不完整',
  no_route: '未配置',
};

function text(value: unknown): string {
  if (value === undefined || value === null) return '';
  return typeof value === 'string' ? value : JSON.stringify(value);
}

export function describeStep(step: Step): Line {
  const d = parseObject<Record<string, unknown>>(step.data, {});
  switch (step.event) {
    case 'queued':
      return { icon: Clock3, tone: 'plain', title: '任务已保存，等待执行' };
    case 'started':
      return { icon: Workflow, tone: 'plain', title: '开始执行' };
    case 'plan':
      return { icon: Workflow, tone: 'agent', title: '制定执行计划', detail: text(d.description) };
    case 'query_rewritten':
      return {
        icon: Wand2,
        tone: 'agent',
        title: '改写为英文检索查询',
        detail: Array.isArray(d.queries) ? d.queries.join(' · ') : '',
      };
    case 'tool_started':
      return { icon: Bot, tone: 'agent', title: `调用工具：${TOOL_LABELS[text(d.tool)] ?? text(d.tool)}` };
    case 'tool_finished':
      return {
        icon: d.status === 'PASS' ? CheckCircle2 : AlertCircle,
        tone: d.status === 'PASS' ? 'ok' : 'warn',
        title: `${TOOL_LABELS[text(d.tool)] ?? text(d.tool)}完成`,
        detail: text(d.summary).slice(0, 160),
      };
    case 'retrieved': {
      const dense = Number(d.dense_candidates ?? 0);
      return {
        icon: Database,
        tone: 'agent',
        title: `找到 ${text(d.evidence_blocks)} 段原文证据`,
        detail: `关键词候选 ${text(d.sparse_candidates)}${dense ? ` · 语义候选 ${dense}` : ''} · ${
          d.mode === 'hybrid' ? '混合检索' : '关键词检索'
        }`,
      };
    }
    case 'model_request':
      return { icon: Sparkles, tone: 'model', title: `请求模型 ${text(d.model)}` };
    case 'model_downgraded':
      return {
        icon: TriangleAlert,
        tone: 'warn',
        title: `模型降级：${text(d.from)} → ${text(d.to)}`,
        detail: REASONS[text(d.reason)] ?? text(d.reason),
      };
    case 'provider_overload_retry':
      return { icon: TriangleAlert, tone: 'warn', title: `上游繁忙，${text(d.wait_seconds)} 秒后重试一次` };
    case 'provider_connect_failed':
      return { icon: TriangleAlert, tone: 'warn', title: '连接模型服务失败（请求未发送）' };
    case 'validating':
      return { icon: ListChecks, tone: 'agent', title: '核验引文、版本、数值与正文绑定' };
    case 'answer_gap_detected':
      return {
        icon: ScanSearch,
        tone: 'warn',
        title: d.validation_rejected ? '初稿未通过核验，补充检索' : `发现 ${text(d.issues)} 处证据缺口，补充检索`,
      };
    case 'answer_gap_retrieved':
      return { icon: Database, tone: 'agent', title: `补充检索到 ${text(d.new_blocks)} 段新证据` };
    case 'answer_revising':
      return { icon: Wand2, tone: 'agent', title: '依据补充证据修订一次' };
    case 'answer_revision_checked':
      return {
        icon: d.status === 'PASS' ? CheckCircle2 : AlertCircle,
        tone: d.status === 'PASS' ? 'ok' : 'warn',
        title: d.status === 'PASS' ? '修订稿通过核验' : '修订稿仍有待复核内容',
      };
    case 'evidence_review':
      return { icon: ShieldCheck, tone: 'model', title: `独立复核 ${text(d.claims)} 条主张` };
    case 'decision_review':
      return { icon: ShieldCheck, tone: 'model', title: `Gemini Decision 1 复核 ${text(d.claims)} 条主张` };
    case 'decision_review_unavailable':
      return {
        icon: TriangleAlert,
        tone: 'warn',
        title: d.automatic_fallback ? 'Decision 1 不可用，改由生成模型复核' : 'Decision 1 不可用，主张保留为待复核',
      };
    case 'quota_route_refused':
      return { icon: TriangleAlert, tone: 'warn', title: `${text(d.model)} 额度不足，尝试下一路由`, detail: REASONS[text(d.code)] ?? text(d.code) };
    case 'evidence_review_unavailable':
      return { icon: TriangleAlert, tone: 'warn', title: '独立复核暂不可用，主张保留为待复核' };
    case 'agent_planning':
      return { icon: Workflow, tone: 'agent', title: `规划第 ${text(d.round)} 轮` };
    case 'agent_plan':
      return { icon: Workflow, tone: 'agent', title: `计划：${text(d.summary)}`, detail: `${text(d.actions)} 个工具步骤` };
    case 'agent_observed':
      return { icon: Bot, tone: 'agent', title: `收到 ${text(d.tools_completed)} 个工具结果` };
    case 'document_card':
      return { icon: ListChecks, tone: 'ok', title: '生成文献卡片', detail: `作者 ${text(d.authors)} 位` };
    case 'completed':
      return { icon: CheckCircle2, tone: 'ok', title: '完成' };
    case 'partial':
      return { icon: AlertCircle, tone: 'warn', title: '部分完成：有待复核或证据不足的内容' };
    case 'failed':
      return { icon: AlertCircle, tone: 'bad', title: '执行失败', detail: text(d.error) };
    case 'cancelled':
      return { icon: AlertCircle, tone: 'plain', title: '已取消' };
    default:
      return { icon: Clock3, tone: 'plain', title: step.event };
  }
}

function clock(seconds: number) {
  return new Date(seconds * 1000).toLocaleTimeString('zh-CN', { hour12: false });
}

export function AgentTimeline({ steps, live }: { steps: Step[]; live: boolean }) {
  const [open, setOpen] = useState(live);
  const [raw, setRaw] = useState(false);
  // Expanded while the run works; folds away once the answer is ready.
  useEffect(() => setOpen(live), [live]);
  const visible = steps.filter((s) => !['heartbeat'].includes(s.event));
  const models = new Set(
    visible.filter((s) => s.event === 'model_request').map((s) => text(parseObject<Record<string, unknown>>(s.data, {}).model)),
  );
  const tools = visible.filter((s) => s.event === 'tool_finished').length;
  const duration = visible.length > 1 ? visible[visible.length - 1].created - visible[0].created : 0;
  const expanded = open;
  return (
    <section aria-label="公开执行记录">
      <button className="timeline-summary" aria-expanded={expanded} onClick={() => setOpen(!open)}>
        <Workflow size={15} />
        <span>
          {live ? '正在执行' : '执行记录'} · {visible.length} 步
          {models.size ? ` · 模型 ${models.size} 个` : ''}
          {tools ? ` · 工具 ${tools} 次` : ''}
          {duration > 0 ? ` · ${Math.round(duration)} 秒` : ''}
        </span>
        <ChevronDown size={15} className={expanded ? 'flipped' : ''} />
      </button>
      {expanded && (
        <div className="agent-timeline">
          {visible.map((step) => {
            const line = describeStep(step);
            const Icon = line.icon;
            return (
              <div className={`timeline-row ${line.tone}`} key={step.id}>
                <span className="timeline-icon">
                  <Icon size={13} />
                </span>
                <div>
                  <strong>{line.title}</strong>
                  {line.detail && <p>{line.detail}</p>}
                </div>
                <time>{clock(step.created)}</time>
              </div>
            );
          })}
          <button className="text-button" onClick={() => setRaw(!raw)}>
            {raw ? '隐藏原始事件' : '查看原始事件'}
          </button>
          {raw && (
            <pre className="code-block">
              {JSON.stringify(
                visible.map((s) => ({ event: s.event, data: parseObject(s.data, {}) })),
                null,
                2,
              )}
            </pre>
          )}
        </div>
      )}
    </section>
  );
}
