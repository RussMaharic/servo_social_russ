#!/usr/bin/env bash
set -euo pipefail
DEXOPS_ROOT="$(cd "$(dirname "$0")" && pwd)"
exec bash "$DEXOPS_ROOT/scripts/start-connect.sh"
