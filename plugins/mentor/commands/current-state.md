---
description: Enable doc/current_state/ after the fact, or show its status if already enabled.
allowed-tools: Read, Write, Glob, Bash(ls:*), Bash(test:*), Bash(mkdir:*), Bash(cp:*), Bash(workbench-mentor:*), Bash(export:*), AskUserQuestion
---

# /mentor:current-state

Manage the opt-in `doc/current_state/` layer (see [`epic/mentor-current-state.md`](../../../epic/mentor-current-state.md)). Two modes:

- **Not yet enabled** → offer to scaffold (same prompt as `/mentor:init` Phase 4.5).
- **Already enabled** → list files in `doc/current_state/`, flag missing seed.

## 1. Pre-flight

```bash
export PATH="$HOME/.claude-workbench/bin:$PATH"
workbench-mentor --health
```

- Exit non-zero → tell user to run `/mentor:init` first; stop.

Then:

```bash
workbench-mentor config --format json
```

Read `mode` and `current_state.enabled` / `current_state.path`.

- **`mode == basic`**: stop. `current_state` is development-mode only — tell user to switch via `/mentor:init --reset` if they want it.

## 2. Branch on enabled state

### Branch A — `current_state.enabled: false`

Show the same offer as `/mentor:init` Phase 4.5, via `AskUserQuestion`:

> Scaffold `doc/current_state/`?
>   Purpose: snapshot of how the system actually looks now.
>   What ships: doc/current_state/ARCHITECTURE.md (single seed file)
>   What follows: agent will add more files (UML, CODEMAP, ...) as needs arise.
>   [y/N]   ← default N

- **No / cancel**: print "current_state remains disabled" and exit. Don't nag.
- **Yes**:
  1. `mkdir -p <current_state.path>` (default `doc/current_state/`)
  2. Copy `${CLAUDE_PLUGIN_ROOT}/frameworks/development/templates/current_state/ARCHITECTURE.md` → `<current_state.path>/ARCHITECTURE.md` (skip if exists)
  3. Update `.claude/mentor.yaml`: set `current_state.enabled: true` and `current_state.path` (preserve user's other config). **Never** rewrite the whole file — patch only the `current_state:` block.
  4. Print:
     ```
     ✓ doc/current_state/ enabled.
       Created: doc/current_state/ARCHITECTURE.md
     SessionStart hook will surface ARCHITECTURE.md alongside SPEC + active sprint.
     Two SKILL rules now apply (see mentor-workflow/SKILL.md).
     ```

### Branch B — `current_state.enabled: true`

Read-only status report:

```bash
ls <current_state.path>
```

- Verify `<current_state.path>/ARCHITECTURE.md` exists. If missing → show warning and offer to re-seed.
- List all `.md` files in the directory (the agent-added ones).
- Print frontmatter `title:` for each (best-effort).

Example output:

```
current_state (enabled, path: doc/current_state/)
  ✓ ARCHITECTURE.md       — Architecture (current state)
  + CODEMAP.md            — Code map  [agent-added]
  + DATA_MODEL.md         — Data model  [agent-added]

Reminder: Rule 1 — sync ARCHITECTURE on out-of-scope code changes.
          Rule 2 — agent-built file = agent-maintained.
```

## Absolute rules

- **Never** write `.claude/mentor.yaml` from scratch — only patch the `current_state:` block. Other plugins / future fields must survive.
- **Never** overwrite an existing `ARCHITECTURE.md`. If user wants a fresh copy, they delete the old one first.
- **Never** disable `current_state.enabled: true → false` from this command. To disable, user edits `.claude/mentor.yaml` by hand (it's destructive enough to warrant typing).
- **Never** create `doc/current_state/` files other than `ARCHITECTURE.md`. Other files (UML, CODEMAP, ...) are **agent-created on demand**, not template-driven.
