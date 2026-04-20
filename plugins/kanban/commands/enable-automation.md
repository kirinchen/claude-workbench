---
description: Install a trigger so Claude Code runs on kanban.json changes without a live session.
allowed-tools: Read, Write, Bash(bash:*), Bash(crontab:*), Bash(ls:*), Bash(test:*), Bash(realpath:*)
---

# /kanban:enable-automation

Walk the user through installing an automation trigger for the current project. In v0.1.0, two modes are supported:

1. **Cron polling** — runs `cron-runner.sh` every N minutes. Low-friction, works everywhere.
2. **Git post-merge hook** — fires after `git pull`. Lower latency, only useful if the user pulls remotely-authored kanban changes.

A third mode (webhook server) is documented in SPEC §8 but is out of scope for v0.1.0 — if the user asks, explain they need to deploy the server manually.

## 1. Orient

Confirm we're in a project with `kanban.json`. If missing, tell them to run `/kanban:init` first and stop.

Print a one-paragraph explainer:

> Automation lets Claude pick up and execute kanban tasks without you opening a session. It uses your existing `claude login` (Pro/Max subscription), so it does NOT consume API credits. Logs go to `~/.claude-workbench/logs/`.

## 2. Ask which mode

Offer the two modes above with their tradeoffs. Accept user input (number or name).

| # | Mode | Best for |
|---|---|---|
| 1 | Cron polling (every 10 min) | Default; works when you're offline |
| 2 | Git post-merge hook | You edit kanban.json on another machine and pull |

Do NOT silently pick for them.

## 3a. Cron mode

1. Ask for the interval in minutes (default 10). Validate integer ≥ 1.
2. Run: `bash ${CLAUDE_PLUGIN_ROOT}/scripts/install-cron.sh "$CLAUDE_PROJECT_DIR" <interval>`
3. Report the installed crontab line and the log location.
4. Tell them how to uninstall: `crontab -e` and delete the tagged lines.

## 3b. Git post-merge mode

1. Check `.git/hooks/post-merge` doesn't already exist. If it does, show its contents and ask whether to append or abort.
2. Write a post-merge hook that:
   - Runs only when `kanban.json` was among the changed files in the pulled commits.
   - Invokes `claude -p` in headless mode with minimal `--allowedTools`.
3. `chmod +x .git/hooks/post-merge`.
4. Report that the hook is active and only fires on `git pull`.

Hook contents to write:

```bash
#!/usr/bin/env bash
set -euo pipefail
changed=$(git diff-tree -r --name-only --no-commit-id ORIG_HEAD HEAD 2>/dev/null || true)
if printf '%s\n' "$changed" | grep -q '^kanban\.json$'; then
    claude -p "kanban.json changed via git pull. /kanban:next and execute." \
      --allowedTools "Read,Write,Edit,Bash(git:*),Bash(date:*)" \
      --permission-mode acceptEdits \
      >> "$HOME/.claude-workbench/logs/git-hook.log" 2>&1 &
fi
```

## 4. Summarise

End with:
- What was installed (exact path or crontab line)
- How to verify it ran (check the log after N minutes / after next `git pull`)
- How to remove it

## Absolute rules

- Never install both modes silently — they can fire concurrently and trample state. If the user wants both, explain the risk and make them confirm per-mode.
- Never write a cron line or hook that runs `claude` with `--allowedTools "*"` or `--permission-mode bypassPermissions`. Minimal tool set is part of the security posture (§11).
- Do not edit user's existing `.git/hooks/post-merge` without showing the diff and getting explicit confirmation.
