#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p evidence
.venv/bin/python -m pytest tests/unit tests/integration -q 2>&1 | tee evidence/pytest.log
.venv/bin/ruff check services --select E9,F63,F7,F82 2>&1 | tee evidence/backend-check.log
(cd apps/web && npm run build) 2>&1 | tee evidence/frontend-build.log
.venv/bin/python scripts/export_contract.py
