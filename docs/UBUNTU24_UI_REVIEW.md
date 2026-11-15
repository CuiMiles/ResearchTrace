# Ubuntu 24 Reader UI review

Date: 2026-11-15. Scope: `apps/web/**` and this report only. Existing dirty/untracked work retained; no backend edits, provider requests, or parser submissions by this UI task.

## Review and implementation

The Reader previously addressed pages, blocks, search and references only through the document version's default parse. Adding a snapshot selector alone would mix original citations with new parser output. The UI now carries a separate parse identity through all four read paths and through evidence navigation.

- `src/ParseControls.tsx`: native/PaddleOCR/MinerU and CPU/GPU selectors, immutable snapshot selector, actual server statuses/progress/errors, five-second refresh, duplicate-click guard, stable idempotency key for ambiguous submission retries. An accepted submission opens its real `run_id` in the existing task panel. Engines are choices, not declarations that dependencies/models/GPU are ready. Fetch failure disables submission with the real error.
- `src/Reader.tsx`: reads `parse_id` for pages, blocks, search and references; keeps an explicit snapshot selection when the list refreshes or the active snapshot changes; follows citation parse identity. Old page/block state is cleared while a new snapshot loads. Historical outline uses that snapshot's heading blocks, rather than current-version outline metadata. Until write APIs support parse identity, model submission, translation creation/export and outline edits are disabled while browsing historical snapshots. Existing translations are matched by immutable block ID.
- `src/App.tsx`: citation lookup requests the cited snapshot and matches exact block ID. Removed text-prefix substitution that could relocate evidence to another block. Reader remounts when document version changes to avoid a request using the previous document's parse ID.
- `src/api.ts`, `src/types.ts`, `src/styles.css`: optional parse identity, snapshot contract, compact scrollable controls that work in the mobile drawer. Other users' existing changes in these files were retained.
- `scripts/browser_runtime.py`: current-host discovery via `RT_BROWSER_EXECUTABLE`, installed Chromium, or Playwright's installed browser; no implicit downloads. Existing browser scripts use the helper, accept a base URL, and default to the current local API on port 18980. The broad audit previously waited for the first SVG text element, which is a hidden Mermaid edge placeholder; it now waits for actual `.node text`, preserving the requirement that node labels render. New broad-audit screenshots are stored in `validation/ubuntu24-browser/` to retain older evidence.
- `scripts/parse-reader-check.py`: read-only live browser audit, with all non-GET API requests blocked. No mock responses are used.

## Main-agent API coordination

Confirmed contract:

```text
GET /documents/{id}/parses
  -> [{id, version_id, engine, device, status, parsed_pages,
       page_count, active, error, created}]
POST /documents/{id}/parses
  {engine: native|paddleocr|mineru, device: cpu|gpu, idempotency_key}
  -> {id: run_id, run_id, status, parse_id}
GET /documents/{id}/pages/{page}?parse_id=...
GET /documents/{id}/blocks?parse_id=...
GET /documents/{id}/search?q=...&parse_id=...
GET /documents/{id}/references?parse_id=...
```

Only complete snapshots become active. Block/citation responses carry `parse_id`; old snapshots remain readable. Main agent owns parser readiness, authorization, quotas, GPU allocation, cancellation/resume and backend validation. Main agent was advised to enrich legacy stored citations from exact block identity, including citations already containing bbox; the client cannot reliably infer that identity from text alone.

## Environment and reproducible checks

Node: project-private Node v22.16.0 supplied by main agent. No package-lock changes. Old and new lock SHA256 both `3f9266220d46ecf25d64aab030d47f3420670d3313b1be527bd24847fbb15d89`.

An initial old-host dependency relay enabled early checks. A separate, clean remote relay directory then ran `npm ci --offline --no-audit --no-fund` against the unchanged manifests: 259 packages installed. This used the old host's working Node20.18.1 and npm10.9.2; npm warned `entities@9.0.0` wants Node>=20.19.0. Final builds run locally with Node22.16.0, satisfying that requirement. Fresh modules were transferred to local `apps/web/node_modules`; initial relay modules were retained under ignored `.browser-runtime/node_modules-initial-relay`.

Browser: relayed Chromium120.0.6099.28 (Playwright chromium1091), with Python Playwright supplied by main agent. This is an explicit older executable, not a claim to have installed the current matching Playwright browser. Missing NSS/NSPR/audio libraries were supplied privately by main agent and applied per command; no host system libraries changed.

```bash
export PATH="$PWD/.tools/node-v22.16.0-linux-x64/bin:$PATH"
npm --prefix apps/web run build

LD_LIBRARY_PATH="$PWD/.tools/browser-libs/root/usr/lib/x86_64-linux-gnu" \
RT_BROWSER_EXECUTABLE="$PWD/apps/web/.browser-runtime/chrome-linux/chrome" \
.venv/bin/python apps/web/scripts/parse-reader-check.py http://127.0.0.1:18980
```

| Check | Status | Evidence / limits |
|---|---|---|
| TypeScript and production build using fresh dependencies | PASS | `apps/web/validation/ubuntu24-ui-build.log`; existing large-bundle warning remains; index published last with old hashed assets retained |
| Python audit scripts compile | PASS | `python3 -m py_compile` for browser helper, existing three scripts and new Reader audit |
| Diff whitespace | PASS | `git diff --check -- apps/web docs/UBUNTU24_UI_REVIEW.md` |
| Live Reader read-only audit | PASS | `apps/web/validation/parse-reader-check.json`, ten checks; authenticated real documents/snapshots, scoped search, explicit snapshot preserved after refresh, GPU message, desktop/mobile overflow, no mutation or browser exception |
| Visual desktop/mobile review | PASS | `apps/web/validation/parse-reader-desktop.png`, `parse-reader-mobile.png`; inspected at1440x1000 and390x844; mobile reparse section scrolls within drawer |
| Broad existing browser audit | PASS | `apps/web/validation/ubuntu24-browser/browser-check.json` and `ubuntu24-browser-check.log`; nine checks, zero browser exceptions, no horizontal overflow at tested widths, editable Mermaid and malicious-link rejection |
| Standalone Mermaid configuration check | PASS | Actual output: native_text_count3, foreignObject_count0, labels_present true |
| Historical snapshot switch and historical action guards | NOT RUN | Audit dataset had one native active snapshot per inspected document; historical test branches did not execute |
| Real UI reparse POST, retry, task completion, PaddleOCR/MinerU readiness | NOT RUN | Kept this audit read-only; no readiness claim; main agent integration owns live parser validation |
| Model calls | NOT RUN | Zero provider/model calls made by this task |

## Three input paths for subsequent integration acceptance

1. Open an imported PDF → Reader → choose PaddleOCR/CPU → create parse snapshot → inspect real task/error → after completion switch between old and new snapshots and search both. This submits a real parse and was not run by this task.
2. Open a paper with a retained citation → follow evidence carrying the old `parse_id` → verify the selected old snapshot, physical page and exact block; switch back to the active snapshot. Needs a genuinely completed second snapshot.
3. Choose an unconfigured engine/device → submit once → verify the real blocked/error result, then retry the same unchanged request after restoring service; the UI preserves the idempotency key for an ambiguous POST failure. No canned success is shown.

Actual local application entry is `http://127.0.0.1:18980`; API startup/restart is owned by main agent. This is not a public deployment claim. Existing Hydrogen/provider budget remains untouched. Remaining checks require completed additional parser snapshots and real parser submissions, not additional model quota.
