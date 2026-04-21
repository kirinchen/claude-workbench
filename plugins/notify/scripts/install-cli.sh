#!/usr/bin/env bash
# install-cli.sh — link workbench-notify into ~/.claude-workbench/bin/.
#
# Idempotent. Called by /notify:setup (and by the user manually if the CLI
# wasn't on PATH after install). Never fails fatally — prints the state it
# observed and exits 0 except on truly unexpected errors.
set -euo pipefail

plugin_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")"/.. && pwd)"
src="$plugin_root/scripts/workbench-notify"
dispatch="$plugin_root/scripts/notify-dispatch.py"

bin_dir="${WORKBENCH_BIN:-$HOME/.claude-workbench/bin}"
mkdir -p "$bin_dir"

if [ ! -x "$src" ]; then
  chmod +x "$src" "$dispatch" 2>/dev/null || true
fi

dst="$bin_dir/workbench-notify"

# Refuse to overwrite a non-symlink we didn't create — user may have hand-edited.
if [ -e "$dst" ] && [ ! -L "$dst" ]; then
  echo "notify install: $dst exists and is not a symlink; leaving it alone." >&2
  echo "   Source lives at: $src" >&2
  exit 0
fi

ln -sf "$src" "$dst"

cat <<EOF
notify install: linked
  $dst -> $src

If '$bin_dir' is not on your PATH, add to your shell rc:
  export PATH="$bin_dir:\$PATH"

Sanity check:
  workbench-notify --health
EOF
