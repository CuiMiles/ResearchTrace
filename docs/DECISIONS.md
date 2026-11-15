# Decisions

2026-11-15: Follow requested React/TypeScript/Vite + FastAPI + SQLite/WAL + single durable worker. No GPU or training. No Sites hosting. Runtime isolated in `.venv`, port 18970 (checked unused); no existing services changed.

Backend owns schema and OpenAPI. Separate modules/directories for delegated implementation. Normalized crop-relative rotated bbox, zero-based physical pages; printed labels separately. Metadata and version identity are content derived. Uncertain labels stay uncertain. API secrets remain ignored `.env` mode 600. Reuse two previously configured Gemini credentials as explicitly authorized in this session; independence from prior user confirmation, not inferred from key count. Conservative shared quota group until independent project mapping can be verified.

Authentication uses access codes and HttpOnly opaque workspace session cookies; isolated workspaces by session. Local startup uses a locally stored access code, never provider credentials.

UI: pale blue-gray #F4F7FB canvas, white paper, midnight navy #172B4D text, teal #087F8C evidence markers, blue #315EBD action, amber #9A6700 uncertainty. Three-pane document workbench, quiet navigation, live evidence inspector; no fabricated dashboard statistics. System Chinese sans with serif document headings. The design search matched institutional colors but suggested a portfolio layout; that layout was rejected as unrelated to document work.
