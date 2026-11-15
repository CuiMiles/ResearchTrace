#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
for name in api worker; do
  file="data/$name.pid"
  if [[ -f "$file" ]]; then
    pid="$(cat "$file")"
    if [[ -r "/proc/$pid/cmdline" ]] && tr '\0' ' ' <"/proc/$pid/cmdline" | grep -q "services.$name"; then
      kill "$pid"
    fi
    rm -f "$file"
  fi
done
