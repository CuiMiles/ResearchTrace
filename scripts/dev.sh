#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -f .env ]]; then
  cp .env.example .env
  chmod 600 .env
  echo 'Created .env. Configure RT_ACCESS_CODE and distinct RT_ADMIN_CODE before login.'
fi
if [[ ! -x .venv/bin/python ]]; then
  "${PYTHON_BIN:-python3}" -m venv .venv
  .venv/bin/pip install -r requirements.lock
fi
if [[ ! -f apps/web/dist/index.html ]]; then
  (cd apps/web && npm ci && npm run build)
fi
mkdir -p data
if command -v systemctl >/dev/null && systemctl --user show-environment >/dev/null 2>&1; then
  .venv/bin/python scripts/install_service.py
  .venv/bin/python -c 'import os; from dotenv import load_dotenv; load_dotenv(".env"); print("ResearchTrace: http://127.0.0.1:"+os.getenv("RT_PORT","18970"))'
  exit 0
fi
if [[ -f data/api.pid ]] && kill -0 "$(cat data/api.pid)" 2>/dev/null; then
  echo 'ResearchTrace API already running. See data/api.log.'
  exit 0
fi
nohup .venv/bin/python -m services.worker.main >data/worker.log 2>&1 </dev/null &
echo $! >data/worker.pid
nohup .venv/bin/python -m services.api.serve >data/api.log 2>&1 </dev/null &
echo $! >data/api.pid
for attempt in {1..30}; do
  if .venv/bin/python -c 'import httpx,os; from dotenv import load_dotenv; load_dotenv(".env"); r=httpx.get("http://127.0.0.1:"+os.getenv("RT_PORT","18970")+"/healthz",trust_env=False,timeout=1);r.raise_for_status()' 2>/dev/null; then
    .venv/bin/python -c 'import os; from dotenv import load_dotenv; load_dotenv(".env"); print("ResearchTrace started: http://127.0.0.1:"+os.getenv("RT_PORT","18970"))'
    echo 'Access codes: .env RT_ACCESS_CODE / RT_ADMIN_CODE (server login only).'
    exit 0
  fi
  sleep 1
done
echo 'Startup failed; inspect data/api.log and data/worker.log.'
exit 1
