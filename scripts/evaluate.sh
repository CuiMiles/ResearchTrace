#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
echo 'Quality evaluation NOT RUN: requires independently reviewed ground truth and a separate explicit budget.'
echo 'Default smoke is bounded at 4 Hydrogen calls and is not a 50-question accuracy evaluation.'
