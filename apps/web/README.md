# ResearchTrace web workbench

React + TypeScript + Vite. Runtime data comes from the authenticated FastAPI API;
there are no embedded paper answers, synthetic graph edges or simulated streams.

```sh
npm ci
npm run typecheck
npm run build
npm run dev
```

Development listens on `127.0.0.1:18971` and proxies `/api` to `127.0.0.1:18970`.
Production is `dist/`, served by FastAPI. Node 20.19+ / 22 is recommended.
No provider secret is read by Vite. Login uses a server access code and HttpOnly
workspace cookie. Do not put a provider key into a `VITE_` variable.

The reader renders one PDF.js page at a time. All citation boxes are zero-based
physical-page, normalized crop-relative coordinates. Extra UI rotations transform
the overlay rather than changing the source evidence. A page label is separately
shown when available. Paragraph translation is aligned by block IDs; sync scrolls
to corresponding blocks with a loop guard. Long-document text searches use the
server FTS endpoint, not only the first loaded blocks.

Mermaid runs with `securityLevel: strict`, HTML labels disabled, and DOMPurify SVG
cleanup. Script/link/config-override syntax is rejected before render. The build
copies the pinned official prebuilt Mermaid ES modules under `public/vendor` so
Vite does not compile every diagram renderer from source. These generated assets
are ignored by Git and recreated by `npm run build` / `npm run dev`; no CDN is used.
Lucide icons import specific modules to keep the icon catalog out of the build.

Browser checks should cover 1440×900, 1280×800 and a narrow mobile viewport, and
should inspect real PDF highlighting, model output provenance, chart downloads,
Mermaid update/export, explicit errors and persistent run history.
