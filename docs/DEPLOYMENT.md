# ECS deployment lane — 2026-11-16 (current)

The deployment worktree is based on `6b02876`. The authorised target is ECS `i-bp13r66a7w9gwi5fs48n` through node01 Workbench, with **only** `/opt/researchtrace`, the new nginx site `researchtrace`, and new loopback listeners. The default nginx site and local development/API/GPU services have not been stopped or overwritten.

Current measured state: Ubuntu 24.04, 2 CPU, 1612 MiB RAM plus 4 GiB swap, about 31 GiB disk free. Ubuntu Docker `29.1.3` and Compose `2.40.3` were installed; existing nginx keeps ports 80/443. Caddy remains an option in root `compose.yaml` for a fresh server, but is deliberately not started over this server's nginx.

**PASS**: Workbench operations; base-image download; dedicated nginx configuration and successful reload; existing `https://sluna.xyz` returns 200; restricted node01 user-systemd tunnel; ECS loopback ports 18985/18986 respond 401 without retrieval credentials. `GatewayPorts` remains off. The SSH key is project-specific, forced-command restricted, and allows only three loopback reverse forwards. The host key was obtained through authenticated Workbench. A per-unit CONNECT proxy is needed because direct node01→ECS TCP22 timed out; the global proxy is unchanged.

**In progress**: first real baseline image build (system packages installed, Python dependencies installing at this checkpoint). The first direct Debian-CDN build stalled and only its own build container was stopped; its log is retained on ECS. The retry uses `--build-arg DEBIAN_MIRROR=mirrors.aliyun.com`, without editing daemon-wide registry/proxy settings.

**BLOCKED**: `researchtrace.sluna.xyz` has no address record in current DNS. Add `A researchtrace -> 118.31.50.2` in the existing domain's authorised DNS account. No DNS credentials were found in the known CLI location. After DNS propagation, use `certbot certonly --webroot -w /opt/researchtrace/acme -d researchtrace.sluna.xyz --register-unsafely-without-email --agree-tos --non-interactive`, then add TLS directives only to `/etc/nginx/sites-available/researchtrace`; retain the existing default site and certificate. Do not report HTTPS or browser login PASS before those are actually checked.

**NOT RUN at this checkpoint**: final-source image, main-provided seed import/vector copy, real model generation on ECS, public new-browser reviewer workflow, production restore drill, and GitHub Actions execution. Deployment lane model calls: **0**. Initial bootstrap runtime config is private with random access codes, no provider keys, paid fallback off, and model functions disabled; final runtime configuration and historical ledger are supplied by main, never echoed.

## Deploy final source after main integration

1. Create a new `/opt/researchtrace/releases/<release>` containing only reviewed source, requirements, `deploy/`, `scripts/backup.py`, and the verified frontend at `deploy/web-dist`. Keep `.env`, seed database/files and secrets separate from the source archive.
2. `python3 scripts/deploy_ecs.py upload <archive> /opt/researchtrace/releases/<archive>` relays through node01's existing Workbench authentication. The tool never prints upload signing URLs. `exec --file <reviewed-shell-file>` runs an operator-owned script; it is not exposed as a research Agent tool.
3. Build on ECS using `DOCKER_BUILDKIT=0 docker build --memory=768m --cpu-quota=100000 --build-arg DEBIAN_MIRROR=mirrors.aliyun.com -f deploy/Dockerfile.prebuilt -t researchtrace:<release> .`. Frontend build occurs on the development host. Reuse the installed base image; do not change the Docker daemon's settings.
4. Main supplies the already computed seed vectors, full original call ledger and a mode-600 `/opt/researchtrace/private/runtime.env`. Do not recompute vectors per reviewer or reset the four consumed smoke calls. Seed-path relocation and reviewer-account cloning belong to main's schema-aware tooling.
5. `sh deploy/activate.sh /opt/researchtrace/releases/<release> researchtrace:<release>` validates Compose, backs up existing state if any, starts only project containers, checks API health, publishes the current symlink and installs the backup timer. Workbench commands time out at 30 seconds, so start long builds/activation with nohup and inspect their private exit files. A failed candidate does not change the current source symlink; rollback runtime with the previous recorded image and release, retaining the current data/ledger.
6. Check `/healthz`, unauthenticated `/api/v1/documents` =401, two worker heartbeats, private PDF authorisation, actual model reachability from the container, and the public HTTPS/reviewer browser workflow. These checks are distinct.

`deploy/compose.ecs.yaml` uses host networking because authenticated SSH tunnels are loopback-only; API explicitly binds **127.0.0.1:18970**, and no container port is published publicly. App UID10001, no extra capabilities, no-new-privileges, bounded CPU/PID/logs. API/document/interactive memory limits are384/512/384MiB respectively; these are limits, not measured peak usage. Shared GPU availability is optional, and model/auth tokens are still required to use retrieval.

## Backup, restore and CI

`researchtrace-backup.timer` schedules **03:15 Asia/Shanghai** plus up to10min jitter, with Persistent=true. The root oneshot service runs `scripts/backup.py`: a bounded BEGIN IMMEDIATE writer gate plus SQLite backup API and file copy gives a consistent snapshot while WAL readers continue. It fails rather than publishing an incomplete snapshot when the20-second writer-pause budget expires; it never copies a live WAL as a database backup. It checks referenced PDFs, integrity, private permissions, and refuses symlinks. Private env is copied separately inside the mode700 backup; no values are logged. Seven known snapshots are retained, unrelated files untouched. This provides local recovery; off-host disaster recovery remains NOT RUN.

```sh
python3 scripts/backup.py --data /opt/researchtrace/data --destination /opt/researchtrace/backups --env /opt/researchtrace/private/runtime.env
python3 scripts/backup.py --restore /opt/researchtrace/backups/backup-<timestamp> --destination /opt/researchtrace/restored-data
```

Restore refuses an existing destination, relocates copied PDF paths and retains every quota row including failures/unknown outcomes. Restore env separately from the snapshot using mode600. Test with `python3 -m unittest discover -s deploy -p 'test_*.py' -v`: **4 passed** (live WAL+PDF+unknown quota, symlink rejection, missing PDF refusal, retention/fresh-destination guard).

`.github/workflows/ci.yml` uses locked Python3.12/Node22 dependencies, backend regression+deployment tests, Ruff, frontend typecheck/build, contract generation, both Compose validations and a separate real container build/health/auth/nonroot check. CI contains no provider credentials. Workflow authored/locally YAML parsed; GitHub execution remains **NOT RUN** until main pushes it.

---

## Historical local/deployment notes (not current production status)

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
