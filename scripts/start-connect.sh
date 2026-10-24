#!/usr/bin/env bash
set -euo pipefail
TASK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ ! -x "$TASK_ROOT/.venv/bin/python" ]; then
  python3 -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ required"'
  python3 -m venv "$TASK_ROOT/.venv"
fi
"$TASK_ROOT/.venv/bin/python" -m pip install -e "$TASK_ROOT[gateway]"
echo "Dexops companion is starting. The deployed workspace will open automatically."
exec "$TASK_ROOT/.venv/bin/python" -m t2_bots.connect.app --workspace-url "https://servosocialruss.vercel.app/"
