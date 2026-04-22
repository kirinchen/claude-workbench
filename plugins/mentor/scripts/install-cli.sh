#!/usr/bin/env bash
# install-cli.sh — link workbench-mentor into ~/.claude-workbench/bin/.
#
# Idempotent. Never fails fatally. Called by /mentor:init at the end of its
# interactive flow, or by the user manually if the CLI wasn't on PATH.
set -euo pipefail

plugin_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")"/.. && pwd)"
shim="$plugin_root/scripts/workbench-mentor"
cli="$plugin_root/scripts/workbench-mentor.py"

bin_dir="${WORKBENCH_BIN:-$HOME/.claude-workbench/bin}"
mkdir -p "$bin_dir"

chmod +x "$shim" "$cli" 2>/dev/null || true

dst="$bin_dir/workbench-mentor"
if [ -e "$dst" ] && [ ! -L "$dst" ]; then
  echo "mentor install: $dst exists and is not a symlink; leaving it alone." >&2
  exit 0
fi
ln -sf "$shim" "$dst"

cat <<EOF
mentor install: linked
  $dst -> $shim

Sanity check:
  workbench-mentor --health
EOF
