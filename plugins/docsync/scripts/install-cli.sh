#!/usr/bin/env bash
# install-cli.sh — link workbench-docsync into ~/.claude-workbench/bin/.
#
# Idempotent. Never fails fatally. Called by /docsync:init (after YAML write)
# or manually if the CLI wasn't on PATH.
set -euo pipefail

plugin_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")"/.. && pwd)"
shim="$plugin_root/scripts/workbench-docsync"
cli="$plugin_root/scripts/workbench-docsync.py"

bin_dir="${WORKBENCH_BIN:-$HOME/.claude-workbench/bin}"
mkdir -p "$bin_dir"

chmod +x "$shim" "$cli" 2>/dev/null || true

dst="$bin_dir/workbench-docsync"
if [ -e "$dst" ] && [ ! -L "$dst" ]; then
  echo "docsync install: $dst exists and is not a symlink; leaving it alone." >&2
  exit 0
fi
ln -sf "$shim" "$dst"

cat <<EOF
docsync install: linked
  $dst -> $shim

If '$bin_dir' is not on your PATH, add to your shell rc:
  export PATH="$bin_dir:\$PATH"

Sanity check:
  workbench-docsync --health
EOF
