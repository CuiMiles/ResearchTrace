# 研证 ResearchTrace — Final Refactor & Optimization Plan

Date: 2026-11-16 · Baseline commit: `11d4cb3` · Scope: whole product (frontend, backend, AI core, deployment, submission materials)

This is the single plan to execute from now until submission. It replaces the task ordering in
`START_HERE.md` §"当前接手重点" and `CODEX_UPGRADE_TASK.md`; it does **not** replace their constraints
(`AGENTS.md` still governs: real evidence, no fabricated results, no hard-coded answers, keys only on the server,
PASS/FAIL/BLOCKED/NOT RUN reporting).

No plan can guarantee first place. This one is built to maximise the score on the official rubric
(AI 35 / product + engineering 30 / innovation 15 / UX 10 / practicality 10) in the time that is left.

---

## 0. The constraint that shapes everything

`CODEX_TASK.md` §1.1 records the submission deadline as **2026-11-18**. Today is 11-16. There are roughly
**two working days**, and the last half-day belongs to the video, the PDF and the platform submission — not to code.

Consequences:

1. Work is ordered by *points per hour*, not by elegance. Every task below carries a priority (P0/P1/P2) and a cut rule.
2. Deploy to the public server on the **first evening**, not the last. Everything after that is an update to a live site.
3. The frontend is rebuilt **route by route inside the existing Vite app**; the current UI stays reachable until each new page passes its check. The build must never be red.
4. Feature freeze is **Day 2, 10:00**. After that only bug fixes, recording and writing.

First human action: open the contest personal centre and confirm the exact deadline hour (§10).

---

## 1. Where the project actually stands

Checked in this session on a clean checkout (Python 3.13, Node 22, no provider keys, zero model calls):

| Check | Result |
|---|---|
| `pytest tests/unit tests/integration` | **477 passed, 7 skipped**, 38.6 s |
| `npm ci && npm run build` (typecheck + Vite) | passes; main chunk **1.07 MB** (321 KB gzip), no code splitting beyond graph/diagram |
| App started locally (API + 2 worker pools), 9 contest PDFs uploaded through the browser | all 9 parsed; no page errors on the page tour (a just-uploaded document logs 404s for pages that are not parsed yet) |

Evidence: `evidence/refactor-plan/` (test log + four screenshots).

### 1.1 What is strong — keep, do not rewrite

- Immutable PDF version / parse-snapshot / block identity with page + bbox; citations survive re-parsing and new versions.
- Durable SQLite job system: idempotency keys, cancel/resume, checkpoints, per-run OS locks, two worker pools.
- Claim-level evidence validation (empty quote, 8→80 number mismatch, free-text bypass are rejected) and one bounded revision cycle.
- Security: SSRF with DNS pinning, workspace isolation, chart rendering without arbitrary code, strict Mermaid.
- Retrieval generations: chunk→span mapping, model fingerprint, atomic activation, local embed/rerank provider interface.
- Real test culture: 477 automated tests and an honest evidence trail.

This foundation is better than most contest entries. The problem is that almost none of it is *visible* to a judge
in eight minutes, and several things a judge will try first do not work well.

### 1.2 What loses points today

**A. A judge cannot actually use the AI (blocks 35 + 30 + 10 points)**

| Finding | Where |
|---|---|
| Core model budget is 2 calls per workspace per day and 4 lifetime in the default profile | `models.py` `budget_policy`, `.env.example` |
| Only one provider (Gemini native, needs a proxy from mainland servers); no OpenAI-compatible or local LLM route | `models.py` |
| No streaming: the answer appears only when the whole run finishes | `jobs.qa`, `app.py` events |
| No conversation: every question is a stand-alone run; the official follow-up "其中 Adam…（接上文省略了论文名字）" cannot resolve "其中" | `Reader.tsx` `ask()`, `/qa/runs` |
| Multi-paper QA exists only as a "compare" form, not as chat | `Research.tsx` `ComparePage` |
| The planner agent and the router are **off by default** (`RT_AGENT_PLANNING=false`, `RT_DECISION_ENABLED=false`); default path is a fixed retrieve→generate→validate pipeline | `jobs.py:138`, `research_agent.py` |
| Official question 1 (sixth author + affiliation) is recorded FAIL/partial | `docs/UPGRADE_STATUS_20261116.md` |
| Feature flags that select the real behaviour are not in `.env.example` | `RT_EMBED_PROVIDER`, `RT_BUDGET_PROFILE`, `RT_ENABLE_RERANK`, … |

**B. Document intelligence is shallower than the storage model suggests**

Observed on the 9 uploaded contest PDFs with the default (native) parser:

- Titles wrong on 2 of 9: LoRA became **"RA: -R"**, ViT became **"16 16"**.
- `metadata.author` empty on 8 of 9; authors, affiliations and e-mails are flattened into one paragraph block (this is why the sixth-author question fails).
- No abstract field, no publication year → the graph shows "年份未知" for every node.
- Licence boilerplate ("Provided proper attribution is provided…") is typed as three headings; the outline is a flat list with no levels (GPT-3 has 91 entries).
- Tables, figures and equations are typed as blocks but have no UI; MinerU / PaddleOCR-VL exist only as a manual re-parse inside a collapsed settings box.
- GROBID metadata and the layout-preserving PDF export are side-cars that are not wired into the product.

**C. Coverage gaps against the six required modules**

| Module | Works | Missing or weak |
|---|---|---|
| 1.1 Library & parsing | CRUD, batch of 20, SHA + arXiv identity, version linking, scan + 541-page book | no "which version do you keep?" dialog (only a passive notice); structured metadata (B above) |
| 1.2 QA | hybrid retrieval, claims with located quotes, validation | everything in A |
| 1.3 Reading & translation | PDF.js page view, block-aligned bilingual view with sync scroll, both directions, md/html export | one page at a time, **no text layer** (so no select-to-translate / hover), citation jump only from the text view not from the PDF, flat outline |
| 1.4 Download & recommend | arXiv + Crossref search/import, watch queries with scheduler, like/dislike | **no reference batch download, no importance filter**; ranking is word overlap with a template "reason"; code link is a regex on the abstract; no daily/weekly digest view |
| 1.5 Graph & survey | real reference edges, PageRank, Cytoscape view, Future-Work audit pipeline | no explicit cornerstone/peripheral classification, **no survey feature** (only a generic prompt), Future-Work live loop is NOT RUN |
| 1.6 Writing | CSV → line/bar/radar/3D + computed caption + reproducible script, Mermaid editor | **no idea→outline generator, no diagram generation** (manual editor only), no table output, zh→en only via the reader on an uploaded PDF |

**D. Engineering quality as a reviewer of the repository will see it**

- Frontend source is effectively minified by hand: `App.tsx` is 18.5 KB in 38 lines (longest line 4,393 characters); `styles.css` is 55 KB in 68 lines; no comments. The contest explicitly asks for commented code.
- No router (no URLs, back button, deep links), no data layer (three endpoints polled every 3 s from the root component), no lint, no formatter, no frontend tests, types written by hand instead of generated from `openapi.json`.
- Backend: one `app.py` holding 62 routes; lines up to 1,039 characters in `jobs.py`; configuration read by scattered `os.getenv` calls; Ruff runs only four syntax rules; no formatter or type check.
- No CI. Docker Compose has never been executed, runs a single worker without pools and has no HTTPS front.
- Repository: 726 tracked files, ~187 MB, hundreds of evidence files and six overlapping status documents; `README.md` reads as a development log.

**E. UI**

Consistent but generic admin styling. The reader spends four columns on chrome and gives the paper ~640 px;
the batch-import panel pushes the page header down; run results show raw `key：value` step dumps and JSON;
the translate toolbar is visibly broken; admin/acceptance tooling sits in the judge's main navigation.

**F. Submission materials**: public HTTPS site, 5–8 min 1080p video, ≤30-page PDF, team info in README — none exist yet.

---

## 2. How the score is won

Judges will (1) watch the video, (2) open the site and type the official example questions, (3) skim the PDF, (4) glance at the repository. Plan accordingly:

| Rubric | Lever | Section |
|---|---|---|
| AI depth 35 | Visible, real multi-agent run; document card with structured authors/sections/tables; hybrid RAG with a measured ablation table; local models actually serving requests | §4, §5.1 |
| Product + engineering 30 | All six modules reachable and working; readable, modular code; CI badge; one-command deploy | §5.2, §5.4 |
| Innovation 15 | Three signature mechanisms, each demonstrable in under a minute (§3.2) | §3 |
| UX 10 | New information architecture, streaming answers, evidence peek, reader that feels like a reader | §5.3 |
| Practicality 10 | The nine official questions answered correctly on the public site, on a PDF the judge uploads | §9 |

Rule of thumb for every hour: *would a judge see this in the video or hit it in the first five minutes on the site?* If not, it is P2.

---

## 3. Name and positioning

### 3.1 Decision: keep the name, sharpen the line

Keep **研证 ResearchTrace**. The name is short, reads as 研究 + 证据 (and echoes 验证), and already runs through the
repository, service units, evidence and documents; renaming costs hours and buys no rubric points.

Change the positioning line so it says *Agent* and says the differentiator:

- 中文：**研证 — 每个结论都能回到原文的科研智能体**
- English: **ResearchTrace — the evidence-first research agent**
- One sentence for the video and PDF: "别的助手给你答案，研证给你答案、出处和它自己核对过的结果。"

### 3.2 The three things a judge should remember

1. **Evidence lights.** Every sentence of an answer carries a status — 已核对支持 / 待复核 / 与原文矛盾 / 证据不足 — set by a verifier agent, and one click shows the cropped region of the original PDF. Demo: ask "为什么用了 80 张 GPU？" and watch the system correct the premise to 8 P100s.
2. **Version-aware notes.** Upload v7, take a note, upload v1 under a random filename: the system links them, recommends the newer one, shows the diff and flags which saved claims need re-checking. Old citations never move.
3. **Future-Work timeline.** Pick a Future-Work sentence from an old paper; agents search later literature, fetch full text, and return 已有直接证据 / 部分覆盖 / 当前范围证据不足 with dates and conditions — never "全球首次".

All three already have backend foundations. The work is to finish them and make them obvious.

---

## 4. Target architecture

### 4.1 Runtime topology

```
Browser ── HTTPS ──> Caddy (ECS 2c/2G)
                       ├─ static web (Vite build)
                       └─ FastAPI  ── SQLite WAL + files
                            ├─ worker-interactive (chat, agents, translation)
                            └─ worker-documents  (parse, index)
                                     │ authenticated tunnel
                       GPU host (3090s): embed + rerank service · local LLM (OpenAI-compatible) · MinerU/PaddleOCR parser
                       Cloud LLM: OpenAI-compatible endpoint (Bailian) and/or Gemini native
```

The ECS never needs a GPU. If the tunnel is down the site still reads, searches by keyword and answers through the cloud model, and says so.

### 4.2 Model layer — `services/api/llm/`

Replace the single Gemini module with a small provider interface; keep the quota ledger unchanged underneath.

```
LLMProvider.generate(messages, *, json_schema=None, stream=False) -> text | iterator of deltas
  ├─ GeminiNativeProvider        (existing code, moved)
  ├─ OpenAICompatProvider        (Bailian/DashScope, DeepSeek, any /v1/chat/completions)
  └─ the same OpenAICompatProvider pointed at the local vLLM server
```

Roles map to tiers in configuration, not in code:

| Role | Default tier | Fallback |
|---|---|---|
| router, query rewriter, verifier, selection translate | **local LLM** | cloud small |
| synthesiser, survey, outline, Future-Work judge | cloud large | cloud small with a visible "降级" label |
| batch translation, metadata extraction | cloud small | local LLM |
| embedding, rerank | **local** (existing service) | keyword + LLM query translation |

The UI always shows the model that actually answered. Budgets become a named profile (`judging`) with explicit numbers set by the operator (§10); failed and unknown calls keep counting.

### 4.3 Agent layer — `services/api/agents/`

One explicit, bounded state machine on top of the existing durable run and tool registry. No new framework.

```
Router ─┬─ fast path (simple fact) ───────────────► Retriever ► Synthesiser ► Verifier ► Publisher
        └─ full path ► Planner ► [tools in parallel where independent] ► Synthesiser ► Verifier
                           ▲                                                   │ gaps / contradictions
                           └──────────── one re-plan, one re-retrieval ◄──────┘
```

| Agent | Input → output | Model tier |
|---|---|---|
| Router | question + scope → intent (`fact`, `metadata`, `compare`, `survey`, `future_work`, `write`, `translate`, `chart`) and path | local |
| Planner | intent + tool schemas + observations → ≤5 actions per round, ≤2 rounds, ≤10 tool steps | cloud small |
| Retriever | sub-queries → evidence pack (hybrid + rerank, per-document quota, neighbour/table context) | local embed + rerank |
| Specialists (tools) | `get_document_card`, `lookup_references`, `lookup_tables`, `compare_versions`, `build_citation_graph`, `search_papers`, `fetch_document`, `compute_csv_stats`, `render_chart` | deterministic |
| Synthesiser | evidence pack → claims + answer segments (existing JSON contract), streamed | cloud large |
| Verifier | each claim + its quotes → supported / contradicted / insufficient / not_checked, plus the existing deterministic number/unit rules | local |
| Publisher | verified claims → note artifact, bibliography, exports | deterministic |

Every transition emits a typed event (`agent_started`, `tool_call`, `tool_result`, `delta`, `claim_verified`, `agent_finished`)
with role, model, local/cloud tag, duration and tokens. The frontend timeline renders these; there is no hidden chain of thought to fake.

### 4.4 Retrieval pipeline (what "advanced RAG" means here)

```
question (+ last 3 turns)
  → rewrite: resolve references to earlier turns, add English search terms for Chinese questions
  → route:   metadata / references / tables questions go to structured stores first
  → recall:  BM25 (symmetric tokeniser) ∥ dense (local model, chunk → span) ∥ per-document quota for multi-paper
  → fuse:    RRF → rerank top 50 → 8–12 evidence blocks + neighbours, table header/footnote kept
  → answer:  claims bound to block id + verbatim quote
  → verify:  deterministic rules, then verifier agent; one corrective re-retrieval if gaps
```

Most of this exists. New: conversation-aware rewrite, structured routing, the verifier on by default, and an ablation table that proves each stage earns its place.

### 4.5 Document intelligence pipeline

```
upload → SHA + identity → native parse (fast, readable in seconds)
       → DocCard builder:
            title / authors[order, affiliation, e-mail] / abstract / year / venue
              source 1: arXiv or Crossref record when an identifier is found (authoritative)
              source 2: LLM extraction from page-1 blocks, every field must appear in the page text
            outline tree: PDF bookmarks → numbered headings ("3.2.2" = level 3) → font-size clusters
            assets: tables, figures, equations, references, appendix boundary — each with page + bbox
       → quality gate per page: scan / table-heavy / formula-heavy pages are queued for MinerU or PaddleOCR-VL when the parser host is reachable
       → index: sparse immediately, dense generation in the background, atomic activation
```

Each DocCard field stores its source (`arxiv_api`, `pdf_frontmatter_llm`, `user_edit`) and the block it came from, so the sixth-author answer can cite the author block.

---

## 5. Work packages

Priorities: **P0** = must ship; **P1** = ships unless we are behind at the checkpoint; **P2** = only if everything else is green.

### 5.0 Unblockers — first evening (all P0)

| ID | Task | Done when |
|---|---|---|
| U1 | `OpenAICompatProvider` + provider registry + role→tier config; move Gemini code behind the same interface; document every flag in `.env.example` | a chat answer is produced through the OpenAI-compatible endpoint with the ledger recording the call; unit tests cover routing, refusal and unknown-outcome accounting |
| U2 | `judging` budget profile with explicit operator numbers; per-workspace daily limit sized for a judge session | a fresh reviewer workspace can ask 20 questions in a row; the ledger is intact; paid fallback still off |
| U3 | Fix title extraction (reject fragments shorter than 3 words or mostly non-letters; prefer PDF metadata / arXiv record; small-caps and maths-in-title cases) | LoRA and ViT titles are correct; regression test with both PDFs |
| U4 | DocCard v1: identifier → arXiv/Crossref record; otherwise LLM extraction of page 1 with substring validation | `GET /documents/{id}/card` returns ordered authors with affiliations for Transformer v7, BERT, GPT-1; year present for every arXiv paper |
| U5 | Turn the agent path on by default with the fast path for simple facts; add `get_document_card` and `lookup_references` tools | official questions 1 and 5 answered correctly with a citation to the author block / reference entry |
| U6 | Public deployment skeleton: Compose (api, two workers, Caddy with automatic HTTPS), reviewer accounts, tunnel to GPU host | the current app is reachable at `https://<subdomain>` from a phone network; `/readyz` distinguishes database, workers, index, cloud model, local models |

### 5.1 AI core

| ID | P | Task | Done when |
|---|---|---|---|
| A1 | P0 | Conversation threads: `threads` + `messages` tables; question rewrite uses the last turns; scope (one paper / selected papers / whole library) stored per thread | the official follow-up "其中 Adam 优化器的 β1 和 β2…" works without naming the paper |
| A2 | P0 | Streaming: provider deltas → incremental JSON parser → `delta` events per answer segment over the existing SSE channel; reconnect resumes from event id without a second model call | first text visible in under ~3 s after generation starts; reload mid-answer continues |
| A3 | P0 | Agent state machine and typed events (§4.3); verifier on by default; one re-plan, one corrective retrieval | a run trace shows ≥4 distinct roles with real inputs/outputs; a planted wrong premise (80 GPUs) is corrected; an unanswerable question returns 证据不足 |
| A4 | P0 | Multi-paper comparison: per-paper sub-queries, comparison matrix output (rows = papers, columns = asked attributes, every filled cell cites a block, empty cell says 未找到) | official multi-paper questions 1–4 produce a matrix with citations from each paper involved |
| A5 | P1 | Local LLM on the GPU host behind the OpenAI-compatible adapter for router / verifier / selection-translate | the model topology page shows requests served locally with latency; cloud fallback verified by stopping the server |
| A6 | P1 | Table and formula evidence: quality gate queues MinerU for table/formula pages; `lookup_tables` returns header + row + footnote; UI renders table HTML and LaTeX | the BLEU question cites the table block; evidence peek shows the table region |
| A7 | P1 | Finish dense index for all 39 contest PDFs and activate; nightly-safe rebuild command | coverage N/N shown in the admin page; cross-lingual question retrieves on the extended set |
| A8 | P0 | Evaluation run and report: retrieval ablation (BM25 / +dense / +rerank / +rewrite) on the 80-question set; answer check on the nine official questions + 8 unanswerable/false-premise ones | `docs/EVALUATION.md` has a table with numerators and denominators, model fingerprints, and the failures listed |
| A9 | P1 | Future-Work loop executed live end to end (search → fetch → child parse → date/condition comparison) with the three outcome classes | one real run id per outcome class recorded in the test report |
| A10 | P2 | GROBID header/reference side-car as a third DocCard source; layout-preserving bilingual PDF export | only if every P0/P1 gate is green |

### 5.2 Feature completion by module

| ID | P | Module | Task | Done when |
|---|---|---|---|---|
| F1 | P0 | 1.1 | Duplicate/version dialog on upload: "库中已有更新的 v7 — 保留库中版本（推荐）/ 两个都保留 / 用本次替换当前版本", with "查看差异"; nothing is physically deleted | upload v7 then renamed v1 → dialog appears; each choice has an API test |
| F2 | P0 | 1.1 | "解析结果" tab in the reader: DocCard (editable), section tree, galleries of tables / figures / equations / references with jump-to-page | a judge can see every granularity item listed in the task statement on one screen |
| F3 | P0 | 1.3 | Reader v2 (§5.3.4): continuous scroll, text layer, in-PDF citation links with back stack, hierarchical outline | "3.2.2 Multi-Head Attention" reachable from the tree; click `[1]` in the PDF → reference entry → back to the exact position |
| F4 | P0 | 1.3 | Select-to-translate / explain / ask from the PDF text layer; whole-paper translation progress bar; rendered HTML bilingual export | selecting a sentence shows a translation popover in ≤2 s (cached afterwards) |
| F5 | P0 | 1.4 | References panel: importance score per reference (in-text mention count, sections where cited, citation-context function classified as 方法依赖 / 实证比较 / 背景) → "下载全部" or "下载最重要的 N 篇" as one batch | on Transformer v7 the batch resolves and imports the open-access references it can find and reports the ones it cannot, with reasons |
| F6 | P0 | 1.4 | Recommendations: daily/weekly digest built from watch results; reason written by the model from the candidate abstract and the user's library ("在 X 的基础上提出…"); code availability checked from links in the abstract/comments (and the repository's existence when the network allows); like/dislike changes the next ranking | digest page shows ≥5 real candidates with reasons, code badge and feedback that visibly reorders |
| F7 | P1 | 1.4 | Item-based collaborative signal across reviewer workspaces (co-liked papers), clearly labelled as such | two accounts with overlapping likes change each other's ranking in a test |
| F8 | P0 | 1.5 | Graph v2: publication year from DocCard, layered-by-year and force layouts, node size = PageRank, classes 基石 / 桥梁 / 边缘衍生 from PageRank + in/out-degree + betweenness with the rule shown, edge click → reference entry in the PDF | 20-paper upload produces a readable graph; the classification explains itself |
| F9 | P0 | 1.5 | "生成领域综述" on the graph page: agent run using graph roles + per-paper evidence → 研究问题 / 方法脉络 / 差异 / 局限 / 待研究点, every fact cited; export md/html/bib | a survey for the 20-paper set with ≥1 citation per paragraph, saved as an artifact |
| F10 | P0 | 1.6 | Idea → paper skeleton: Abstract / Introduction / Related Work / References; references only from verified records (library + live arXiv/Crossref search), each with DOI/arXiv link; unverified statements marked 待填写 | every reference in the output resolves to a stored verified record; an automatic check fails the run otherwise |
| F11 | P0 | 1.6 | Diagram generation: from an idea or a selected paper → Mermaid **and** Graphviz DOT (rendered client-side, sanitised), TikZ and Matplotlib as downloadable source | generated diagram for the Transformer paper renders, is editable and exports SVG |
| F12 | P1 | 1.6 | CSV: model proposes a PlotSpec from the column profile (still validated and rendered by the fixed template); add a publication-style table (booktabs LaTeX + HTML) | two different CSVs give different suggested charts and a table; captions still computed by code |
| F13 | P0 | 1.6 | Chinese → English: paste-text box and "整篇翻译" for a Chinese PDF in the writing studio, with protected formulas/citations | a Chinese abstract returns academic English with numbers and symbols intact |

### 5.3 Frontend refactor

#### 5.3.1 Stack (stay on React + TypeScript + Vite)

Add: React Router, TanStack Query (server state, replaces the 3-second root polling), Zustand (small UI state),
Tailwind CSS + Radix primitives (shadcn-style components copied into the repository), `react-resizable-panels`,
TanStack Virtual, `cmdk`, a toast library, `openapi-typescript` (types generated from `packages/contracts/openapi.json`),
ESLint + Prettier, Vitest, Playwright Test, a Graphviz WASM renderer, a Cytoscape layered/force layout extension.
Keep: `pdfjs-dist`, Cytoscape, Mermaid, KaTeX, react-markdown, DOMPurify, lucide.
All assets self-hosted (no CDN, no web-font service — the site must work from mainland networks and under the current CSP).

#### 5.3.2 Source layout

```
apps/web/src/
  app/            router, providers, AppShell, error boundary
  api/            client.ts, schema.d.ts (generated), sse.ts, queries/{documents,chat,runs,discover,graph,studio,admin}.ts
  components/ui/  button, dialog, tabs, tooltip, popover, badge, skeleton, …
  components/     EvidenceChip, EvidencePeek, ClaimLine, AgentTimeline, StatusPill, FileDropzone, EmptyState, ModelTag
  features/
    home/  library/  reader/  chat/  discover/  insights/  studio/  admin/
  lib/            bbox.ts, format.ts, storage.ts, i18n strings
  styles/         tokens.css, globals.css
```

Rules: one component per file, no line over 100 characters (Prettier), a header comment on every feature module
explaining what it owns, no hand-written API types.

#### 5.3.3 Design system

- **Tone**: a quiet reading room, not an admin console. Paper-white canvas, ink text, one brand colour, and colour reserved for *evidence state*.
- **Tokens** (light; provide a dark set too): canvas `#F7F6F2`, surface `#FFFFFF`, ink `#1B2333`, muted `#5B6474`, line `#E5E2DB`, brand `#2F55B5`; evidence — supported `#0E8F7E`, needs-review `#B7791F`, contradicted `#C2413B`, insufficient `#7A8496`; agent accent `#6B5BD2`.
- **Type**: system CJK sans for UI (PingFang / HarmonyOS / Microsoft YaHei) with a self-hosted Latin sans; a Latin serif for paper titles and the bilingual text column; 14 px base, 1.6 line height in reading columns; tabular numbers in tables.
- **Layout**: 4 px spacing grid, 8 px radius, borders instead of shadows except for popovers; content max-width 1200 px outside the reader.
- **Motion**: 150–200 ms, only for state changes (evidence light turning on, panel resize, highlight pulse); respects reduced-motion.
- **States**: every data view has skeleton, empty, error, partial and ready variants — taken from the existing state matrix, not removed.
- **Accessibility**: visible focus, full keyboard path for upload → ask → open evidence, contrast ≥ 4.5:1.

#### 5.3.4 Information architecture and page specifications

Navigation shrinks from nine entries to six; admin tooling leaves the main rail.

| Route | Name | What the judge sees |
|---|---|---|
| `/` | 工作台 | One command bar ("问一个问题，或把论文拖进来"), three start paths, recent threads, today's recommendations, index status in one line |
| `/library` | 文献库 | Table/card toggle, search, tags, status chips; upload opens a right-side import drawer with per-file progress (not a panel that displaces the page); version dialog (F1); multi-select → 问答 / 比较 / 综述 / 图谱 |
| `/read/:versionId` | 阅读器 | Three resizable panes, global rail collapsed to icons. Left: tabs 目录 (tree) / 参考文献 / 搜索 / 解析结果. Centre: continuous PDF with text layer, or 双语对照; toolbar with page, zoom, mode. Right: copilot tabs 问答 / 翻译 / 笔记. Selection toolbar: 翻译 · 解释 · 提问 · 复制引用. Parser/snapshot controls move into a "解析设置" dialog |
| `/chat` and `/chat/:threadId` | 问答 | Thread list, scope chips (papers in scope), streaming answer with claim lights, collapsible agent timeline, evidence drawer on the right that opens the PDF region; comparison answers render as a matrix |
| `/discover` | 发现 | Tabs: 检索下载 / 参考文献下载 / 追踪 / 推荐 (日 · 周). Candidate cards with source, year, reason, code badge, import state, like/dislike |
| `/insights` | 图谱与综述 | Graph canvas (layout switch, year slider, role legend), right inspector (node metrics, edges with reference text), buttons 生成综述 and Future Work 核查; Future-Work result as a timeline + condition matrix |
| `/studio` | 写作工坊 | Tabs: 论文框架 / 结构图 / 数据图表 / 中译英 / 我的产物 |
| `/settings` (avatar menu) | 系统 | Model topology (local vs cloud, live latency), budget ledger, readiness, reviewer accounts, acceptance board (admin only) |

Reader v2 implementation notes:

- Render pages lazily with TanStack Virtual; draw canvas + PDF.js text layer + overlay layer per page. Highlights are positioned from the existing normalised bbox (rotation maths already in `PdfReader.tsx` — keep it).
- Citation links: use the PDF's own link annotations (`page.getAnnotations()`; arXiv PDFs carry them) to jump to the destination and push the current position on a back stack; for PDFs without annotations (scans), detect `[n]` in the text layer and resolve through `/references`.
- Outline: `GET /documents/{id}/outline` returns a tree (§4.5); the user can still edit it.
- Bilingual view: keep the block-aligned sync algorithm and loop guard from `Reader.tsx`; render equations with KaTeX and tables as HTML when the parser provides them.

Answer rendering (replaces `RunResult` / raw step dumps):

- `ClaimLine`: sentence + status dot + numbered `EvidenceChip`s; hovering a chip opens `EvidencePeek` — a server-cropped image of the PDF region, the quote, version label, page, and the verifier's reason.
- `AgentTimeline`: one row per agent/tool event with role icon, short public description ("检索到 12 条证据", "发现数值与原文不一致，补充检索"), model tag (本地/云端), duration; collapsed by default once the answer is complete; raw JSON only behind "查看原始记录".

#### 5.3.5 Migration order (never a red build)

1. Tooling, tokens, `AppShell`, router, generated API types, query client — old pages mounted under the new shell.
2. Chat page + answer components (highest judge exposure), then Reader v2.
3. Library + import drawer + version dialog.
4. Insights, Discover, Studio.
5. Settings/admin; delete the old components and `styles.css`.

After each step: typecheck, build, Playwright smoke, screenshots at 1280 / 1440 / 1920.

### 5.4 Engineering quality

| ID | P | Task | Done when |
|---|---|---|---|
| E1 | P0 | Split `app.py` into routers (`auth`, `documents`, `reader`, `chat`, `runs`, `translate`, `discover`, `graph`, `studio`, `admin`); request/response schemas in `schemas/`; one `settings.py` (pydantic-settings) replaces scattered `os.getenv` | `app.py` only assembles routers and middleware; OpenAPI regenerated; all tests pass |
| E2 | P0 | Format and lint: `ruff format` + a real Ruff rule set (E, F, I, B, UP, SIM) for Python; Prettier + ESLint for the web; module docstrings and comments on non-obvious logic (the contest asks for commented code) | no line over 100 characters in `services/` and `apps/web/src/`; lint clean in CI |
| E3 | P0 | CI on GitHub Actions: backend tests + lint, web typecheck + lint + unit tests + build, Docker image build, Playwright smoke against the built image with no keys | green badge in the README |
| E4 | P0 | Compose: `api`, `worker-documents`, `worker-interactive`, `caddy`; health checks; named volume; `scripts/backup.sh`; a `gpu` profile/systemd units for the GPU host documented separately | `docker compose --profile lite up -d --build` works on a clean machine and is recorded in the test report |
| E5 | P1 | Frontend tests: Vitest for bbox maths, SSE reducer, incremental answer parser; Playwright: upload → ask → open evidence → export, version dialog, select-to-translate | run in CI |
| E6 | P1 | Performance: route-level code splitting (initial JS under ~350 KB gzip), PDF worker and graph loaded on demand, list virtualisation, SSE instead of polling for runs | Lighthouse-style check recorded; no 3-second polling from the root |
| E7 | P0 | Repository tidy without rewriting history: `README.md` rewritten (what it is, screenshots, architecture diagram, quick start, rubric map, team section to be filled by the team); status docs consolidated into `docs/STATUS.md`; process documents moved to `docs/process/`; evidence kept but indexed | a new reader understands and runs the project from the README alone |
| E8 | P1 | Type checking for the new/changed backend modules (pyright or mypy on `llm/`, `agents/`, `routers/`, `schemas/`) | part of CI |

Do **not**: change database, queue or framework; add Redis/Postgres/vector DB/LangGraph; rewrite git history; delete failing records.

### 5.5 Deployment and submission materials

| ID | P | Task | Done when |
|---|---|---|---|
| D1 | P0 | Public site on the ECS behind HTTPS on a new sub-domain; secure cookies; reviewer accounts (each gets an isolated workspace seeded with a read-only copy of the demo library and can upload its own files) | verified from a second network and a clean browser: login → upload → ask → open evidence → export |
| D2 | P0 | Judging readiness: budget profile set, GPU tunnel as a supervised service, automatic degradation tested by stopping the GPU service, nightly SQLite backup | readiness page green; degradation shows the correct label |
| D3 | P0 | Demo data: the 39 contest PDFs fully parsed and indexed in the seed workspace; one prepared CSV pair; watches created | seed script reproducible from `scripts/` |
| D4 | P0 | Video, 5–8 min, 1080p MP4, Mandarin narration + subtitles (§9.2 script) | file exists and plays; matches the deployed commit |
| D5 | P0 | Technical document ≤ 30 pages PDF: overview, requirements, architecture, AI design (agents, RAG, parsing, verification), implementation, evaluation tables, deployment, innovation, limitations | PDF exported and page-counted |
| D6 | P0 | Final repository state: tag `v1.0-submission`, README with site URL and test account instructions (no secrets), licence notes | secret scan clean (`scripts/audit_public_repository.py`) |

---

## 6. API contract additions

The main agent owns this contract and lands it (routes returning 501 are acceptable for a few hours) before lanes split.

```
# chat
POST   /api/v1/chat/threads                      {title?, scope:{version_ids[] | "library"}}
GET    /api/v1/chat/threads
GET    /api/v1/chat/threads/{id}                 messages with run ids and results
POST   /api/v1/chat/threads/{id}/messages        {content, idempotency_key} -> {run_id}
GET    /api/v1/runs/{id}/events                  + event types: agent_started, tool_call, tool_result, delta, claim_verified, agent_finished

# documents
GET    /api/v1/documents/{id}/card               structured metadata with per-field source + block id
PATCH  /api/v1/documents/{id}/card               user corrections
GET    /api/v1/documents/{id}/outline            tree: [{title, level, page_index, block_id, children[]}]
GET    /api/v1/documents/{id}/assets?type=table|figure|equation|reference
GET    /api/v1/documents/{id}/pages/{p}/crop?bbox=x0,y0,x1,y1&scale=2     PNG of a region (evidence peek)
POST   /api/v1/documents/{id}/version-decision   {action: keep_existing | keep_both | make_current}

# reading
POST   /api/v1/translations/selection            {version_id, text, block_id?, target_language} -> {text, model, cached}

# discover
GET    /api/v1/documents/{id}/references/importance
POST   /api/v1/references/import                 {version_id, mode: all | top, top_k?} -> {batch_id}
GET    /api/v1/recommendations?period=day|week
POST   /api/v1/recommendations/refresh

# insights
POST   /api/v1/graphs                            nodes gain year, role, metrics{pagerank, indegree, outdegree, betweenness}
POST   /api/v1/graphs/survey                     {version_ids[]?} -> {run_id}

# studio
POST   /api/v1/writing/outline                   {idea, version_ids[]?, search: bool} -> {run_id}
POST   /api/v1/writing/diagram                   {source: idea | version_id, formats:[mermaid,dot,tikz,matplotlib]} -> {run_id}
POST   /api/v1/writing/translate                 {text, source_language, target_language} -> {run_id}
POST   /api/v1/charts/suggest                    multipart CSV -> validated PlotSpec proposals
POST   /api/v1/charts                            + kind: table

# admin
GET    /api/v1/admin/topology                    models by role, local/cloud, last latency, fallbacks taken
```

Database migrations (idempotent, numbered 6+): `threads`, `messages`, `document_cards`, `reference_importance`,
`recommendations`, `version_decisions`; `works.metadata` gains `year`. No existing table is rewritten.

---

## 7. Schedule

Times are local. Each block ends with: tests green, build green, deployed to the public site, `HANDOFF.md` updated.

| Block | Window | Goals | Exit check |
|---|---|---|---|
| **B0** | Day 0 evening (≈5 h) | U1–U6; API contract §6 landed as stubs; frontend tooling + tokens + shell (step 1 of §5.3.5) | public URL serves the app; 20 questions in a row work; official Q1 and Q5 correct |
| **B1** | Day 1 morning (≈5 h) | A1, A2, A3; Chat page + answer components; E1 router split; E2 formatters | streaming multi-turn chat with claim lights on the public site |
| **B2** | Day 1 afternoon (≈5 h) | F3, F4 Reader v2; F1, F2; A4 comparison matrix; E3 CI | official single- and multi-paper questions all pass; reader citation round-trip works |
| **B3** | Day 1 evening (≈5 h) | F5, F6, F8, F9, F10, F11, F13; Library/Insights/Discover/Studio pages; A7 index; A5 local LLM | every module reachable from the new navigation with a working happy path |
| **Checkpoint** | Day 1 end | Apply the cut list (§8) to anything not started | — |
| **B4** | Day 2 morning until 10:00 | A6, A9, F12, E5, E6 as time allows; A8 evaluation run; E7 README; bug bash on the public site at 1280/1440/1920 | **feature freeze 10:00**; golden checklist §9.1 all PASS on the public site |
| **B5** | Day 2 10:00 → submission | D4 video, D5 PDF, D6 tag; second-network verification; submit with ≥3 h margin | submitted |

### Parallel lanes (use only if separate agents/worktrees are really available)

| Lane | Owns (exclusive write) | Packages |
|---|---|---|
| Main | `packages/contracts`, `services/api/store.py`, `schemas/`, `routers/` skeleton, integration, deploy | U2, U6, E1, E3, E4, D1–D3 |
| AI | `services/api/llm/`, `agents/`, `retrieval.py`, `evidence_validation.py`, `evals/` | U1, U5, A1–A9 |
| Docs-intel & features | `documents.py`, `research.py`, `charts.py`, new `cards.py`, `recommend.py`, `writing.py` | U3, U4, F1, F5–F13 (backend) |
| Web A | `apps/web/src/{app,api,components,features/chat,features/reader}` | shell, Chat, Reader v2 |
| Web B | `apps/web/src/features/{home,library,discover,insights,studio,admin}` | remaining pages |

Schema and contract changes go through the Main lane only. A lane that is blocked reports it; nobody fabricates a completion report.

---

## 8. Cut list

If behind at the Day 1 checkpoint, drop in this order (top first):

1. A10 GROBID side-car and layout-preserving PDF export
2. F7 collaborative filtering
3. F12 table output and chart suggestion (keep the existing chart flow)
4. TikZ/Matplotlib diagram source (keep Mermaid + DOT)
5. E8 type checking, E6 performance polish beyond code splitting
6. A6 MinerU quality gate (keep manual re-parse; answer table questions from native table blocks)
7. A5 local LLM (keep local embedding + rerank as the local-deployment evidence, state it precisely)
8. Dark mode

Never cut: U1–U6, A1–A4, A8, F1–F4, F9–F11, F13, E1–E4, E7, D1–D6. A feature that is not finished is hidden or labelled, never shown as a dead button.

---

## 9. Definition of done

### 9.1 Golden checklist — run on the public site, on a freshly uploaded PDF, recorded with run ids

Gold answers live only in `evals/` and the test report — never in prompts or code.

Single paper (upload `1706.03762v7.pdf` under a random filename, ask in Chinese, in one thread):

1. 第 6 作者是谁，在哪个机构？ → correct name and affiliation, citation opens the author block
2. 其中 Adam 的 β1、β2？ (no paper name — tests conversation context)
3. 训练 Base 模型用了多少个 GPU、什么型号？
4. Transformer (big) 英德 BLEU、当时最好成绩、提升多少？ → cites the results table
5. Layer Normalization 的参考文献完整作者和年份？ → cites the reference entry

Multi-paper (select the papers, one thread): BERT vs Transformer encoder; GPT-1/2/3 parameter counts; GPT-2 LayerNorm position; GPT-1→3 context window — each as a matrix with a citation per filled cell.

Honesty: "为什么用了 80 张 GPU？" → premise corrected; "训练花了多少美元？" → 证据不足.

Documents: v7 then renamed v1 → version dialog; `1706.03762v1_img.pdf` → searchable with highlights; the 541-page book → jump to a late chapter and ask about it.

Reading: outline tree to 3.2.2; `[1]` → reference → back; select a sentence → translation; whole paper translated and scrolled in sync both ways.

Discover: title → download → in library; references of one paper → "下载最重要的 N 篇"; weekly digest with reasons and code badges; dislike reorders.

Insights: 20 PDFs in one upload → graph with roles → generated survey with citations → one Future-Work check.

Studio: idea → skeleton with verifiable references; generated diagram edited and exported; CSV → chart + caption (+ table); Chinese abstract → English.

Failure handling: corrupt PDF rejected clearly; GPU service stopped → site still answers with a visible 降级 label.

### 9.2 Video script (7 minutes)

| Time | Content | Rubric |
|---|---|---|
| 0:00–0:30 | The problem (answers you cannot check) and the one-line pitch | — |
| 0:30–1:45 | Upload a new PDF → DocCard, tree, tables/formulas → ask Q1, Q2 (follow-up), Q4; streaming, evidence peek, premise correction | AI, UX |
| 1:45–2:30 | Agent timeline explained on a comparison question; local/cloud model tags | AI |
| 2:30–3:15 | Reader: citation round-trip, select-to-translate, bilingual sync | product, UX |
| 3:15–4:00 | Version story: v7 note → upload v1 → dialog, diff, claims to re-check | innovation |
| 4:00–5:00 | 20 PDFs → graph roles → survey → Future-Work timeline | AI, innovation |
| 5:00–5:45 | Discover: reference download by importance, weekly digest with code badges | practicality |
| 5:45–6:30 | Studio: idea → skeleton, diagram, CSV chart, zh→en | product |
| 6:30–7:00 | Architecture slide, evaluation table, one failure handled honestly, URL and account | engineering |

Record only from the deployed site. No pre-recorded answers presented as live.

### 9.3 Release gates

All of `RELEASE_GATES.md` section A and C, plus: CI green on the submitted commit; README runs from scratch;
evaluation table present with denominators; every visible button works or is hidden.

---

## 10. Actions only the team can take

1. **Confirm the exact submission deadline** (hour) in the contest personal centre.
2. **Choose the judging models and budget.** Recommended: an OpenAI-compatible cloud model reachable from the ECS without a proxy as the default synthesiser, Gemini kept as an optional deep-analysis tier if the proxy is reliable. Decide the daily call/token ceiling for the judging period and whether any paid usage is allowed — several Bailian models in the quota snapshot do not have "用完即停" enabled, so this is a cost decision. Put keys only in the server `.env`.
3. **GPU host during judging**: who keeps it up, on which cards, and the tunnel credentials. If it cannot be guaranteed, say so now — the plan then presents local embedding/rerank as "available when the lab host is online" and relies on cloud fallback.
4. **ECS + DNS**: SSH access, a sub-domain under the existing domain, ports 80/443 open. The existing main site is not touched.
5. **Team information** for the README and the PDF cover.
6. **Record the narration**, export the PDF, **submit on the platform**.
7. **Public repository check**: decide whether redistributing the 40 third-party PDFs (including the textbook) in a public repository is acceptable under their licences; the alternative is hashes + a download script.

---

## 11. Risks

| Risk | Mitigation |
|---|---|
| Frontend rebuild overruns | Route-by-route migration, old pages stay mounted; chat and reader first; cut list |
| Cloud model quality on citation JSON differs from Hydrogen | Keep the validator and one revision; run §9.1 against the chosen model on Day 0; keep the second provider configured |
| GPU host or tunnel fails during judging | Supervised tunnel, automatic keyword + query-translation fallback, visible label, tested in D2 |
| External scholarly APIs blocked or slow from the server | Per-source status in the UI, cached results labelled with their time, metadata-only import, never fabricated |
| Judges' usage exhausts the budget | Per-workspace daily limits, local tier for cheap roles, ledger page, operator can raise limits without redeploying |
| Refactor breaks the 477 tests | Routers split mechanically first with tests running after each move; no behaviour change in the same commit as a move |
| Time lost to polishing instead of shipping | Feature freeze at Day 2 10:00 is not negotiable |

---

## 12. Reporting

After every block: update `HANDOFF.md`, `docs/TEST_REPORT.md` (PASS / FAIL / BLOCKED / NOT RUN with evidence paths) and
`docs/DECISIONS.md` for any default chosen under ambiguity; commit per real stage. Final report lists the start
command and URL, three new-input demo paths, test evidence, failures and blocks, API usage, and remaining human actions.
