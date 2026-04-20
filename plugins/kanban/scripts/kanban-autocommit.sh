#!/usr/bin/env bash
# kanban-autocommit.sh — PostToolUse hook that auto-commits kanban.json changes.
#
# Triggered after Bash/Write/Edit tool calls. If kanban.json is the ONLY tracked
# change in the working tree, commit it with a message summarising the
# transition. Keeping kanban commits standalone avoids entangling them with
# code changes.
#
# Reads the PostToolUse event JSON from stdin (not strictly needed, but kept
# for symmetry and future extension). Silent on no-op. Exit 0 always — this is
# a convenience, never a blocker.
set -euo pipefail

# Locate project root. Prefer CLAUDE_PROJECT_DIR, else fall back to git toplevel.
proj="${CLAUDE_PROJECT_DIR:-}"
if [ -z "$proj" ]; then
  proj="$(git rev-parse --show-toplevel 2>/dev/null || true)"
fi
[ -z "$proj" ] && exit 0
[ -f "$proj/kanban.json" ] || exit 0

cd "$proj"

# Bail if not a git repo.
git rev-parse --git-dir >/dev/null 2>&1 || exit 0

# Is kanban.json modified vs HEAD?
if git diff --quiet -- kanban.json 2>/dev/null && \
   git diff --cached --quiet -- kanban.json 2>/dev/null; then
  # Nothing to commit.
  exit 0
fi

# Refuse if other files are also dirty — we want standalone kanban commits.
other_changes="$(git status --porcelain -- . | awk '{print $2}' | grep -v '^kanban\.json$' || true)"
if [ -n "$other_changes" ]; then
  # Not our job to bundle; silently skip.
  exit 0
fi

# Build a commit message from the diff. Try to capture the (id, column) pairs
# that changed so the message is useful.
summary="kanban: update"
if command -v jq >/dev/null 2>&1; then
  # Extract task ids whose column differs between HEAD and worktree.
  before="$(git show HEAD:kanban.json 2>/dev/null || echo '{}')"
  after="$(cat kanban.json)"
  changes="$(jq -rn --argjson a "$before" --argjson b "$after" '
    ($a.tasks // []) as $A | ($b.tasks // []) as $B |
    [ $B[] as $t | ($A[] | select(.id == $t.id) | .column) as $prev |
      select($prev != $t.column) |
      "\($t.id) \($prev // "NEW")→\($t.column)" ] | .[]
  ' 2>/dev/null || true)"
  if [ -n "$changes" ]; then
    summary="kanban: $(printf '%s' "$changes" | paste -sd ', ' -)"
  fi
fi

git add -- kanban.json
git commit -m "$summary" -- kanban.json >/dev/null 2>&1 || true

exit 0
