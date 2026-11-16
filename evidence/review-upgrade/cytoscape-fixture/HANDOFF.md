# Cytoscape isolated handoff

Worktree: /tmp/researchtrace-cytoscape-20261116
Branch: upgrade/cytoscape-20261116
Commit: b45d600368db699aedbb9f6def5ca56b09f46f34
Status: clean; only the five authorized source/package paths are committed.

Cytoscape 3.35.0 is exact-pinned (MIT, bundled types). NetworkX and GraphEdge are unchanged.
Default: highest local PageRank node plus real incoming/outgoing one-hop neighbors.
Publication metadata drives the time filter; missing/conflicting years stay explicitly uncertain.
Directed BFS uses the full valid real edge set, including edges outside the visible one-hop graph.
Edge details preserve the original reference and exact version/page/block callback.
Missing locators never invent block IDs; metadata-only edges link to their supplied source.
PNG export uses capped blob-promise output. Native node/edge lists and canvas shortcuts support keyboards.

## Validation

PASS: npm run build in this worktree with Node 22.16.0. See build.log.
PASS: 27 FIXTURE ONLY browser checks, zero page errors or unexpected requests. See report.json.
PASS: 1280x800, 1440x900, 1920x1080, 390x844 overflow checks and screenshots.
PASS: source hashes in report.json match the committed source.

Three synthetic input paths: title/year filtering with unknowns; 3-hop directed path across a hidden intermediate node; canvas edge click to exact evidence callback and PNG download.

NOT RUN: real authenticated Graph API and Reader navigation end-to-end. Fixture evidence callbacks passed; this does not prove Reader highlighting.
NOT RUN: real scholarly corpus acceptance or live model tests.
Limitation: nodes without publication-year metadata remain unknown; conflicting version years remain uncertain.
Limitation: Vite warns about the main application chunk exceeding 500 kB (about 1.54 MB, 474 kB gzip).
Actual API/model calls: 0. Remote GPU use: 0. No .env or user access codes used.

## Reproduce the component checks

The fixture server has no real API proxy and uses an empty env directory.
Start in one terminal:

```sh
/home/cui/projects/competition/传智杯2026/.tools/node-v22.16.0-linux-x64/bin/node /tmp/researchtrace-cytoscape-fixture-20261116/server.mjs
```

Then in another:

```sh
LD_LIBRARY_PATH=/home/cui/projects/competition/传智杯2026/.tools/browser-libs/root/usr/lib/x86_64-linux-gnu /home/cui/projects/competition/传智杯2026/.venv/bin/python /tmp/researchtrace-cytoscape-fixture-20261116/check.py
```

Fixture URL: http://127.0.0.1:19046/__graph_fixture__
The server was stopped after validation; test scripts, screenshots, logs and PNG remain here outside the source worktree.
Main-agent integration: cherry-pick the commit, then validate against authorized real metadata and Reader/API separately.
