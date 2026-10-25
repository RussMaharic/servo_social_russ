#!/usr/bin/env bash
set -euo pipefail
TASK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Shared setup preserves an existing healthy environment instead of reinstalling.
exec python3 "$TASK_ROOT/scripts/setup-dexops.py" "$@"
