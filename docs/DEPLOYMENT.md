# Deployment and recovery

Local operation is independent of existing web services. Current verified app address is `http://127.0.0.1:18980` (source default18970); the port and bind address are configured in `.env`. No existing nginx, proxy routing, DNS, ECS service or GPU process is changed by this project. Public HTTPS deployment is **NOT RUN** until an external request and authorized reviewer login are verified.

## Local launch

Use Ubuntu24/Linux/WSL with Python3.12 and Node22. In the migrated checkout, Python3 is3.12.3 and Node22.16.0 lives privately under `.tools`. No old-host absolute paths are required.

```bash
export PATH="$PWD/.tools/node-v22.16.0-linux-x64/bin:$PATH"
./scripts/dev.sh
curl --fail http://127.0.0.1:18980/healthz
```

The actual current local port is18980, because host-side18970 is occupied. Source defaults remain configurable; `.env` is authoritative. Large wheels, browser archives and models were downloaded on the source server and relayed, then installed into new local environments. With provisioned caches, core offline installation is `.venv/bin/pip install --no-index --find-links .tools/relay/core -r requirements.lock`; optional parsers use their separate pinned lockfiles. Do not copy a virtualenv or an old `.pth` across hosts. Small runtime Debian libraries are extracted privately under `.tools/ocr` / `.tools/browser-libs`, not installed over system libraries.

On first setup, fill server-only `.env` from `.env.example`, mode 600. Set distinct private reviewer/admin codes and provider keys. The UI uses the access code, never the provider key. No-key mode still supports PDF reading, local indexing and CSV plots; model actions must report configuration failure. `HYDROGEN_SMOKE_LIMIT=4` is a persistent development safety cap, not the evaluation allowance for an entire judging period.

When user systemd is available, dev.sh installs `researchtrace-api.service`, `researchtrace-worker.service`, and, when provisioned, the optional `researchtrace-parser.service`; existing units for another checkout are not overwritten. Inspect with:

```bash
systemctl --user status researchtrace-api.service researchtrace-worker.service
journalctl --user -u researchtrace-api.service -u researchtrace-worker.service -n 80
```

The fallback uses background processes and `data/*.pid` / `data/*.log`. `scripts/stop.sh` handles those owned PID files. `scripts/stop.sh` also stops systemd units only when their WorkingDirectory matches this checkout. A user service can depend on a surviving user manager; configure system policy/lingering only with the operator's authorization. No assumption is made that an SSH terminal remains open.

## Lite container target

`compose.yaml` has profile `lite`, static frontend build stage, CPU OCR dependencies, no GPU reservation, and nonroot application UID **10001**. Build on a suitable development host and transfer the image/artifact; do not run a large frontend toolchain on a constrained ECS during judging.

```bash
docker compose --profile lite build
docker compose --profile lite up -d
curl --fail http://127.0.0.1:18970/healthz
docker compose --profile lite logs --tail 80 api worker
```

The host bind mount `./data:/app/data` overrides the image directory ownership. In a **fresh deployment checkout with a new empty data directory**, arrange UID10001 write access before starting, for example using an operator-authorized `install -d -o 10001 -g 10001 -m 0700 data`. Check existing ownership first. Do not recursively change ownership of the development data or another service's directory. Backups must be readable by the chosen backup operator without making the volume public.

Declared limits are API512MiB/0.7CPU and worker896MiB/1CPU. Their sum is 1408MiB of configured ceilings; this does not establish actual peak memory, overall host suitability or a successful Docker build. Plotting occurs in a bounded child of the API, so its usage is included in that service's cgroup. Actual constrained-memory and long-document results belong in TEST_REPORT.

Container loopback is not host loopback. The development SOCKS address `127.0.0.1:17891` is valid only for host processes; it does not reach the host proxy from an isolated container. Configure `GEMINI_CONTAINER_PROXY` and `PUBLIC_CONTAINER_PROXY` with a reachable, authenticated/operator-controlled route, or use a deployment region with direct API access. Do not expose a private proxy publicly or change the existing proxy rules. Verify provider access from the actual runtime container, not just the development shell. Unavailable outbound networking remains a visible BLOCKED live integration.

For new public hosting, preserve existing sites and choose an independently configured subdomain/vhost only after authorization. Reverse proxy to the app, enable HTTPS, use `RT_SECURE_COOKIE=true`, allow same-origin requests, set bounded upload/time limits and disable proxy buffering for SSE. Do not publish `.env`, `data/`, logs or raw private evaluation traces as static files. Reviewer access requires an explicitly configured private access code.

## Optional ECS frontend, local compute

If ECS memory/networking is unsuitable, the current complete API+worker+SQLite may remain on the local server, with ECS acting only as the HTTPS reverse proxy. A private VPN or managed SSH reverse tunnel can connect them. Keep SQLite and the worker on the **same host and local filesystem**. Do not mount the SQLite WAL directory over SSHFS/NFS and run the worker on another machine.

An operator may set up a reverse tunnel from the local server, using an authorized existing SSH identity and an unused ECS loopback port:

```bash
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -R 127.0.0.1:18970:127.0.0.1:18970 ecs-user@ecs-host
```

This command is a deployment example, not an executed connection. Run the tunnel under a dedicated supervised service for judging. Check the selected port remotely before creating it. Route only the new app vhost to that remote loopback port, and verify from outside the ECS network. A general authenticated remote-worker job protocol is **not implemented** in V1; it must not be represented as a deployed feature.

## Backup and restore

Quiesce new submissions and stop the two owned services for the simplest consistent snapshot. Back up the entire private `data/` directory, `.env` separately with mode600, and the exact source/image revision. SQLite includes documents, checkpoints, translations, quota ledger, sessions and artifact records; the same snapshot must include referenced PDFs, embedding BLOBs and chart files. Copying only the main `.sqlite` file during active WAL writes is unsafe; use SQLite's backup API or a stopped-service directory snapshot.

Restore into a fresh private data directory, check ownership, restore `.env`, then start API/worker and verify existing PDFs, historical runs, translation coverage and quota counts. Restart intentionally preserves quota accounting; it is not a quota reset mechanism. Keep sensitive backups out of Git. Production disaster-recovery and public availability tests remain separate acceptance evidence.

## Ubuntu24 measured local constraints

`evidence/ubuntu24/lite-live.json` records three concurrent reviewer uploads on the real API512M and worker896M cgroups, with a541-page self-authored input completing tail-page search and strict workspace file isolation. Sum of their individual observed MemoryPeak values was153112576 bytes (about146MiB) in that run. This is a local constrained-service measurement, not an ECS/Docker result or a maximum for every possible input. The optional heavy parser is in its own5G/2CPU cgroup; it is excluded from the lite budget and cannot be assumed to fit2GiB.

Parser transport is local Unix socket `data/parsing/parser.sock` with mode600 and private job directories. It has fixed library names, bounded single-page inputs, local-only models and no inherited provider keys. GPU tests query current free memory per job, reserve>=2048MiB and monitor only their own process sessions; unaccountable WSL usage stops the job. A loopback health endpoint alone does not establish model readiness or successful inference. See `services/parsing/README.md`.

For SQLite transfer use Python sqlite3.Connection.backup into a project-private snapshot, verify integrity_check, transfer PDFs and that snapshot, and relocate only database paths in the copied environment. A live raw main-db copy can omit valid WAL records. Quota rows and unknown/failed attempts must remain intact. The migration retained Hydrogen4, FlashLite22, embedding56 attempts; current usage is in TEST_REPORT and the local database, not an official vendor balance.

## 2026-11-16 Compose layout (current)

`compose.yaml` now runs four services: `api`, `worker-documents` (parsing and indexing), `worker-interactive` (questions, translation, audits) and, with the `https` profile, `caddy` with automatic certificates for `RT_DOMAIN`. Data lives in the named volume `rt-data`, so the image's non-root user owns it without host chown. Memory limits: API 512 MiB, document worker 640 MiB, interactive worker 384 MiB.

```bash
cp .env.example .env && chmod 600 .env        # access codes, model keys, budgets, RT_SECURE_COOKIE=true for HTTPS
docker compose --profile lite up -d --build
RT_DOMAIN=demo.example.org RT_SECURE_COOKIE=true docker compose --profile lite --profile https up -d
docker compose exec api python -c "import sqlite3; s=sqlite3.connect('/app/data/researchtrace.sqlite'); s.backup(sqlite3.connect('/app/data/backup.sqlite'))"
```

Where Docker Hub is rate-limited, set `RT_IMAGE_REGISTRY=mirror.gcr.io/library/`. Status: `docker compose config` validated in the cloud sandbox; the image build there was BLOCKED by the sandbox network (Docker Hub 429; the egress proxy refuses plain-HTTP Debian mirrors). A first real build must be run on the target server and recorded in `docs/TEST_REPORT.md`.
