#!/usr/bin/env bash
set -euo pipefail
TASK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ ! -x "$TASK_ROOT/.venv/bin/python" ]; then
  python3 -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ required"'
  python3 -m venv "$TASK_ROOT/.venv"
fi
"$TASK_ROOT/.venv/bin/python" -m pip install -e "$TASK_ROOT[gateway]"
COMMAND_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
mkdir -p "$COMMAND_DIR"
printf '#!/usr/bin/env bash\nexec %q -m t2_bots.connect.app --workspace-url %q "$@"\n' \
  "$TASK_ROOT/.venv/bin/python" "https://servosocialruss.vercel.app/" > "$COMMAND_DIR/dexops"
chmod 755 "$COMMAND_DIR/dexops"
case ":$PATH:" in
  *":$COMMAND_DIR:"*) ;;
  *)
    PROFILE="$HOME/.profile"
    [ "$(uname -s)" = "Darwin" ] && PROFILE="$HOME/.zprofile"
    PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'
    grep -Fqx "$PATH_LINE" "$PROFILE" 2>/dev/null || printf '\n%s\n' "$PATH_LINE" >> "$PROFILE"
    ;;
esac
echo "Dexops companion is starting. The deployed workspace will open automatically."
echo "Future terminals can start Dexops from any folder by running: dexops"
exec "$TASK_ROOT/.venv/bin/python" -m t2_bots.connect.app --workspace-url "https://servosocialruss.vercel.app/"
