# kanban

*[繁體中文](./README_zhtw.md)*

Part of the [claude-workbench](../../README.md) family. Task-state persistence + workflow grammar for Claude Code.

**Two storage modes, same slash-command surface:**

| Mode | Storage | When to pick |
|---|---|---|
| **local** | `kanban.json` at the project root | personal projects, single-machine, no team sharing |
| **jira**  | Jira Cloud (per-board config + per-machine token) | multi-machine teams, async collaboration, mobile review |

You can run `/kanban:init` (local) and graduate to `/kanban:initjira` later — the slash commands stay the same.

See [`kanban_quickstart.md`](../../kanban_quickstart.md) for the walk-through, [`SPEC.md §3`](../../SPEC.md) for full design.

## Install

```
> /plugin marketplace add kirinchen/claude-workbench
> /plugin install kanban@claude-workbench
> /kanban:init                     # local mode — scaffold kanban.json
# (optional) switch to Jira-backed:
> /kanban:initjira                 # interactive setup
> /kanban:assign-ap <name>         # this repo's AP for Jira routing
```

## Slash commands

The complete list reflects what's installed in your environment — Claude Code's `/` autocomplete is authoritative. As of kanban 0.3.20:

### Day-to-day workflow

| Command | What it does |
|---|---|
| `/kanban:status` | Read-only board summary (driver-aware) |
| `/kanban:sync` | Pull the open-card summary for the current AP |
| `/kanban:doing` | Work the DOING pool — read every card you currently own and execute in a sensible order *(Jira; local mode keeps `/kanban:next`)* |
| `/kanban:done` | Mark a task (default: current DOING) as DONE |
| `/kanban:block <key>` | Move a task to BLOCKED with a required reason |
| `/kanban:question <key> "<text>"` | Post a question and transition to BLOCKED |
| `/kanban:reply <key>` | Post a reply comment, optionally `@`-mentioning the recipient |

### Inbox / async signals

| Command | What it does |
|---|---|
| `/kanban:mentions` | List Jira comments / descriptions that `@`-mention this agent's account (your inbox) |
| `/kanban:reconcile` | Surface cards invisible to the canonical view (unmapped status, missing AP) |

### Card lifecycle

| Command | What it does |
|---|---|
| `/kanban:create-sub <parent>` | Spawn N sub-cards from a parent issue, linked back via Jira issue link |
| `/kanban:next` | DEPRECATED in Jira mode (use `/kanban:doing`); still works in local mode |

### Setup / configuration (Jira)

| Command | What it does |
|---|---|
| `/kanban:init` | Initialize `kanban.json` + schema in the current project |
| `/kanban:initjira` | Switch project from local to Jira-backed (5-step interactive) |
| `/kanban:import-jira-code` | Bootstrap or re-sync Jira mode from a code emitted by another repo |
| `/kanban:showjira-code` | Print this repo's Jira mapping as shareable JSON (paste-ready for `import-jira-code`) |
| `/kanban:reset-credentials` | Set or rotate Jira credentials on this machine *(secret-safe — runs in your own terminal)* |
| `/kanban:assign-ap <name>` | Set the current repo's Agent Property (AP) — written to `.claude/kanban-agent.json` |
| `/kanban:register-ap <name>` | Register a new AP value to the Jira AP custom field |
| `/kanban:fix-ap-screen` | Attach the AP custom field to project screens (recovers from issue #6) |
| `/kanban:edit-conventions` | Author or edit the team's `conventions` block — narrative notes + per-team toggles |
| `/kanban:show-conventions` | Display the team's `conventions` block (read-only) |
| `/kanban:enable-automation` | Install a trigger so Claude Code runs on `kanban.json` changes (cron / git hook) |
| `/kanban:whoami` | Show current driver / board / AP / token validity |

### Deprecated

| Command | Replaced by |
|---|---|
| `/kanban:initjira-by-code` | `/kanban:import-jira-code` (#34) |
| `/kanban:next` (Jira mode) | `/kanban:doing` (#33) |

## Core concepts

- **Canonical columns**: `TODO → DOING → BLOCKED → REVIEW → DONE → CANCELLED`. Slash commands always speak canonical names; the Jira driver translates via the `transitions` DSL.
- **Compound transitions** (`v0.3+`): `BLOCKED > In Progress + Label` lets multiple canonical states share one Jira status, disambiguated by labels — see `epic/kanban_plugin_ Jira_backend_driver_UPDATE.md`.
- **Agent Property (AP)**: a Jira single-select custom field that routes cards to specific agents/repos. Each repo declares its AP in `.claude/kanban-agent.json#ap`; commands like `/kanban:doing` filter by it (`cf[<id>] = "<repo's ap>"`).
- **Conventions**: per-team narrative notes + opt-in toggles (e.g. `blockedRequiresLink: true`) that travel with `/kanban:showjira-code`. Receivers must explicitly acknowledge before `import-jira-code` completes.

## Hooks

- **PreToolUse** (`kanban-guard.sh`) — blocks Edit/Write on `kanban.json`. State changes go through slash commands.
- **PostToolUse** (`kanban-autocommit.sh`) — auto-commits `kanban.json` as standalone commits when it's the only dirty file.
- **SessionStart** (`kanban-session-check.sh`) — surfaces DOING / BLOCKED + mention count at session start.
- **UserPromptSubmit** (`kanban-card-detect.sh`) — when a Jira URL or `KEY-N` is pasted into a prompt, injects card title, status, AP, recent comments as `additionalContext` (Jira mode only).

## File layout

```
plugins/kanban/
├── .claude-plugin/plugin.json
├── commands/                        # 24 slash commands (one .md per command)
├── drivers/
│   ├── base.py                      # Driver protocol + Task/Comment dataclasses
│   ├── local.py                     # kanban.json driver
│   └── jira.py                      # Jira Cloud driver
├── lib/
│   ├── jira_client.py               # HTTP + ADF helpers
│   ├── kanban_io.py                 # atomic kanban.json read/write
│   ├── transitions.py               # compound transitions DSL
│   ├── ap_registry.py               # AP fuzzy-collision check
│   ├── conventions.py               # team conventions block
│   ├── credentials.py               # ~/.claude-workbench/.env reader/writer
│   ├── card_cache.py                # 30s precheck cache
│   └── card_parser.py               # Jira KEY-N extraction from prompt text
├── hooks/hooks.json
├── scripts/
│   ├── kanban-guard.sh              # PreToolUse
│   ├── kanban-autocommit.sh         # PostToolUse
│   ├── kanban-session-check.sh      # SessionStart
│   ├── kanban-card-detect.sh        # UserPromptSubmit
│   ├── kanban_local.py              # local-driver helper
│   ├── jira_setup.py                # Jira-driver helper (subcommands)
│   ├── cron-runner.sh               # /kanban:enable-automation cron mode
│   └── test_phase{1..25}.py         # regression suite (108+ checks)
├── skills/
│   ├── kanban-workflow/SKILL.md     # generic + local-mode workflow
│   └── kanban-jira-agent/SKILL.md   # Jira-mode agent behaviour
└── templates/
    ├── kanban.example.json
    └── kanban.schema.json
```
