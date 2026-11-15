#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if command -v systemctl >/dev/null && systemctl --user show-environment >/dev/null 2>&1; then
  for name in api worker parser; do
    unit="researchtrace-$name.service"
    if systemctl --user cat "$unit" 2>/dev/null | grep -Fq "WorkingDirectory=$PWD"; then
      systemctl --user stop "$unit"
    fi
  done
fi
for name in api worker parser; do
  file="data/$name.pid"
  if [[ -f "$file" ]]; then
    pid="$(cat "$file")"
    if [[ -r "/proc/$pid/cmdline" ]] && tr '\0' ' ' <"/proc/$pid/cmdline" | grep -q "services.$name"; then
      kill "$pid"
    fi
    rm -f "$file"
  fi
done
