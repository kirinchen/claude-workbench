#!/usr/bin/env bash
# install-cron.sh — install a cron job that runs cron-runner.sh every N minutes.
#
# Usage:
#   install-cron.sh <project-dir> [interval-minutes]
#
# Default interval is 10 minutes. Copies cron-runner.sh to a stable location
# (~/.claude-workbench/bin/) so the plugin can be reinstalled or upgraded
# without breaking cron.
set -euo pipefail

PROJECT_DIR="${1:?project dir required}"
PROJECT_DIR="$(realpath "$PROJECT_DIR")"
INTERVAL="${2:-10}"

# cron-runner.sh lives inside the plugin. ${CLAUDE_PLUGIN_ROOT} is set when
# invoked from a slash command; fall back to the script's own directory.
SRC_RUNNER="${CLAUDE_PLUGIN_ROOT:-$(dirname "$(realpath "$0")")/..}/scripts/cron-runner.sh"
[ -f "$SRC_RUNNER" ] || { echo "error: cron-runner.sh not found at $SRC_RUNNER" >&2; exit 1; }

BIN_DIR="$HOME/.claude-workbench/bin"
DEST_RUNNER="$BIN_DIR/cron-runner.sh"

mkdir -p "$BIN_DIR"
install -m 0755 "$SRC_RUNNER" "$DEST_RUNNER"

# --- Cron line ---------------------------------------------------------------
CRON_LINE="*/$INTERVAL * * * * $DEST_RUNNER $PROJECT_DIR"
CRON_TAG="# claude-workbench:kanban:$PROJECT_DIR"

# Refuse duplicate install (idempotent).
if crontab -l 2>/dev/null | grep -Fq "$CRON_TAG"; then
  echo "Already installed for $PROJECT_DIR. To reinstall, first remove via:"
  echo "  crontab -e   # delete the line tagged '$CRON_TAG'"
  exit 0
fi

# Append. Preserve existing crontab contents.
{
  crontab -l 2>/dev/null || true
  printf '\n%s\n%s\n' "$CRON_TAG" "$CRON_LINE"
} | crontab -

cat <<MSG
Installed cron job:
  $CRON_LINE

Logs: ~/.claude-workbench/logs/cron-runner.log
Remove with:  crontab -e   # delete the two lines tagged '$CRON_TAG'
MSG
