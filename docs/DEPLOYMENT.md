# Deployment and recovery

Local operation is independent of existing web services. Default app address is `http://127.0.0.1:18970`; the port and bind address are configured in `.env`. No existing nginx, proxy routing, DNS, ECS service or GPU process is changed by this project. Public HTTPS deployment is **NOT RUN** until an external request and authorized reviewer login are verified.

## Local launch

Use Linux or WSL with Python 3.12 and Node 22 on PATH. On this inspected host, Python is `/home/CuiMinghao/.local/bin/python3.12` and Node/npm are in `/home/CuiMinghao/envs/cardweb/bin`; the system defaults are older. Do not replace system binaries.

```bash
export PATH=/home/CuiMinghao/envs/cardweb/bin:$PATH
export PYTHON_BIN=/home/CuiMinghao/.local/bin/python3.12
./scripts/dev.sh
curl --fail http://127.0.0.1:18970/healthz
```

On first setup, fill server-only `.env` from `.env.example`, mode 600. Set distinct private reviewer/admin codes and provider keys. The UI uses the access code, never the provider key. No-key mode still supports PDF reading, local indexing and CSV plots; model actions must report configuration failure. `HYDROGEN_SMOKE_LIMIT=4` is a persistent development safety cap, not the evaluation allowance for an entire judging period.

When user systemd is available, dev.sh installs only `researchtrace-api.service` and `researchtrace-worker.service`; existing units for another checkout are not overwritten. Inspect with:

```bash
systemctl --user status researchtrace-api.service researchtrace-worker.service
journalctl --user -u researchtrace-api.service -u researchtrace-worker.service -n 80
```

The fallback uses background processes and `data/*.pid` / `data/*.log`. `scripts/stop.sh` handles those owned PID files. For systemd services, stop the two named user units explicitly. A user service can depend on a surviving user manager; configure system policy/lingering only with the operator's authorization. No assumption is made that an SSH terminal remains open.

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
