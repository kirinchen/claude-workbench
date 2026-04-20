# Claude Workbench — SPEC

**Project**: `kirin/claude-workbench`
**Version**: 0.1.0 (Draft)
**Last Updated**: 2026-04-20
**Author**: Kirin

> **Document lineage**: this file is the merge of three earlier drafts — the original kanban-only SPEC, the workbench family expansion (SPEC_InClude3), and the docsync dev-profile plugin SPEC. Where those docs disagreed, the workbench family SPEC wins for structure, the docsync SPEC wins for §6, and old-SPEC-only content (viewer, automation runners) is preserved as §7.

---

## 1. Family Overview

### 1.1 What

`claude-workbench` is a family of Claude Code plugins that turn the CLI into a persistent, event-driven AI workspace. Four atomic plugins and two meta-bundles are distributed from a single marketplace:

```
┌──────────────────────────────────────────────────────────────────────┐
│  claude-workbench (marketplace)                                       │
│                                                                        │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐        ┌──────────┐            │
│  │ kanban  │  │ notify  │  │ memory  │        │ docsync  │            │
│  │ tasks   │  │ push    │  │ RAG     │        │ code ↔   │            │
│  │         │  │ notif.  │  │ store   │        │  docs    │            │
│  └────┬────┘  └────┬────┘  └────┬────┘        └────┬─────┘            │
│       │            │            │                   │                  │
│       └─────┬──────┴────────────┘                   │                  │
│             ▼                                       ▼                  │
│      ┌─────────────┐                         ┌──────────────┐         │
│      │  workbench  │                         │ workbench-dev│         │
│      │ (core meta) │  ◄────── depends ──┐    │ (dev meta)   │         │
│      └─────────────┘                    └────┤               │         │
│                                              └──────────────┘         │
└──────────────────────────────────────────────────────────────────────┘
```

### 1.2 Why

Claude Code's default usage is session-scoped: open session → give instructions → wait → close. That leaves four gaps:

1. **Task state doesn't persist.** Session closes, context evaporates.
2. **No event-driven trigger.** The user must attend to drive interaction.
3. **Nobody sees the decisions.** Leave the desk and Claude stalls alone.
4. **Knowledge doesn't accumulate.** Every session starts from zero.

The four plugins target one gap each:

| Plugin | Profile | Gap it closes |
|---|---|---|
| **kanban** | core | Task state persistence + shared human/AI work queue |
| **notify** | core | External notification when Claude needs attention |
| **memory** | core | Cross-session RAG knowledge base |
| **docsync** | dev | Code ↔ documentation drift prevention |

All four are independently useful. Composition is opt-in via capability detection (§8.7).

### 1.3 Design Principles

1. **Has-a, not is-a** — inject capability as a plugin; never fork a template.
2. **Modular + composable** — each plugin stands alone; siblings compound when present.
3. **Progressive adoption** — install one, live with it, add others later.
4. **Deterministic engine + AI judgement** — scripts enforce hard rules; Claude handles ambiguity.
5. **Cost-aware** — default path uses Claude Pro/Max subscription (headless mode), not API credits.
6. **Local-first** — data stays on the user's machine; no third-party services beyond the AI provider.
7. **Config-driven, not prompt-driven** (docsync-flavoured) — where rules are project-specific, they live in versioned local config, generated interactively rather than hand-written.

### 1.4 Target User

- Heavy individual Claude Code users
- Juggling multiple projects in parallel
- Comfortable with git, CLI, basic shell scripting
- Prefer subscription + self-hosting over fully-managed SaaS

### 1.5 Plugin Profiles

- **Core** (`kanban`, `notify`, `memory`) — bundled into the default `workbench` meta-plugin. Every workbench user gets these.
- **Dev** (`docsync`, and future candidates like `review`, `lint`) — bundled into `workbench-dev`. For users whose primary use of Claude Code is software engineering.

Profiles are an organisational device, not an architectural boundary — any plugin can depend on any other via capability detection regardless of profile.

---

## 2. System Architecture

### 2.1 Data Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│ User Project                                                         │
│ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ │
│ │ kanban.json  │ │    .env      │ │  memory.db   │ │.claude/      │ │
│ │ (task state) │ │ (API tokens) │ │ (RAG store)  │ │  docsync.yaml│ │
│ └──────┬───────┘ └──────┬───────┘ └──────┬───────┘ └──────┬───────┘ │
│        │                │                │                │          │
│        └──────┬─────────┴──────┬─────────┴────────────────┘          │
│               ▼                ▼                                      │
│ ┌────────────────────────────────────────┐   ┌──────────────┐       │
│ │   Claude Code + Plugins                │◄──┤  Human       │       │
│ │   (skills · commands · hooks · MCP)    │   │  (viewer /   │       │
│ └──────┬─────────┬───────────┬───────────┘   │   phone)     │       │
│        │         │           │               └──────▲───────┘       │
│        │         │  Pushover │                      │                │
│        │         │   /ntfy   │                      │                │
│        │         └───────────┼──────────────────────┘                │
│        │                     │  (push)                               │
│ ┌──────▼────────────────────────────────┐                           │
│ │  External Runners (optional)           │                           │
│ │  cron · git hook · webhook             │                           │
│ │  → `claude -p` headless                │                           │
│ └────────────────────────────────────────┘                           │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 Plugin Interaction Matrix

| Pair | Effect |
|---|---|
| kanban × notify | Task transitions trigger push; decisions needed → high priority push |
| kanban × memory | `next` queries past work; `done` saves completion note |
| kanban × docsync | DONE gate: block if docs haven't been updated (when enforcement=block) |
| notify × memory | Decision prompts carry "last time you chose X" |
| docsync × memory | Doc change summaries persisted for cross-session consistency |
| docsync × notify | Passive — docsync never pushes directly (see §8.6) |
| All four | `cron → kanban:next → memory recall → work → docsync gate → notify push → user decides → memory save → kanban:done` |

Integration is always opt-in through **capability detection** (§8.7). Missing a sibling never breaks a plugin — it just degrades to single-plugin behaviour.

### 2.3 Plugin Responsibility Boundaries

Strict boundaries prevent scope creep and overlap:

| Plugin | Does | Does NOT |
|---|---|---|
| kanban | Task state, state machine, dependency resolution | Notify, accumulate memory, edit docs |
| notify | Dispatch to external channel, provider abstraction | Decide *when* to notify (event source does) |
| memory | Store/retrieve knowledge, embedding, retrieval | Push context proactively (hooks or peers do) |
| docsync | Code↔doc mapping tracking, rule engine, interactive config | Modify doc contents itself, block non-DONE code changes |

---

## 3. Plugin 1: `kanban`

### 3.1 Role

Work bridge between Claude and the user. The user adds tasks in `kanban.json`; Claude picks, executes, and updates state. Both sides read and write the same file.

### 3.2 Data Model

```jsonc
{
  "$schema": "./kanban.schema.json",
  "schema_version": 1,
  "meta": {
    "priorities": ["P0", "P1", "P2", "P3"],
    "categories": ["trading", "aiops", "youtube", "infra"],
    "columns": ["TODO", "DOING", "DONE", "BLOCKED"],
    "created_at": "2026-04-18T10:00:00+08:00",
    "updated_at": "2026-04-20T14:30:00+08:00"
  },
  "tasks": [
    {
      "id": "task-042",
      "title": "Rewrite grid pricing dynamic classifier",
      "column": "TODO",
      "priority": "P1",
      "category": "trading",
      "tags": ["bitfinex", "refactor"],
      "depends": ["task-038", "task-040"],
      "created": "2026-04-18T10:00:00+08:00",
      "updated": "2026-04-19T14:30:00+08:00",
      "started": null,
      "completed": null,
      "assignee": "claude-code",
      "description": "See fin-exchange-manage repo's pricing.py.",
      "comments": [
        { "author": "kirin", "ts": "2026-04-19T09:00:00+08:00", "text": "Rule-based first; ML later." }
      ],
      "custom": {
        "estimated_hours": 4,
        "blocked_reason": null,
        "needs_user_input": false
      }
    }
  ]
}
```

**Field rules**:

| Field | Type | Required | Notes |
|---|---|---|---|
| `schema_version` | int | ✓ | Currently `1`. Never decrement. |
| `meta.priorities` | string[] | ✓ | Ordered highest → lowest. |
| `meta.categories` | string[] | | User-defined. |
| `meta.columns` | string[] | ✓ | Exactly `["TODO","DOING","DONE","BLOCKED"]`. |
| `meta.{created,updated}_at` | ISO 8601 | ✓ | With timezone. |
| `tasks[].id` | string | ✓ | `^task-[0-9]{3,}$`. |
| `tasks[].title` | string | ✓ | Single line. |
| `tasks[].column` | enum | ✓ | One of `meta.columns`. |
| `tasks[].priority` | enum | ✓ | One of `meta.priorities`. |
| `tasks[].category` | string | | Must match `meta.categories` if set. |
| `tasks[].tags` | string[] | | Free-form. |
| `tasks[].depends` | string[] | | Other task ids. DAG-enforced. |
| `tasks[].{created,updated}` | ISO 8601 | ✓ | With timezone. |
| `tasks[].started` | ISO 8601 | conditional | Required when column ∈ {DOING, DONE}. |
| `tasks[].completed` | ISO 8601 | conditional | Required when column == DONE. |
| `tasks[].assignee` | string | | `claude-code`, a human, or null. |
| `tasks[].description` | string | | Multi-line markdown. No secrets. |
| `tasks[].comments` | `{author, ts, text}[]` | | Append-only in practice. |
| `tasks[].custom` | object | | Schema-free; `blocked_reason`, `needs_user_input`, `estimated_hours` are recognised. |

### 3.3 State Transitions

```
             (create)
                │
                ▼
            ┌───────┐
            │ TODO  │ ◄──────────────┐
            └───┬───┘                │
                │ /kanban:next       │ (unblock)
                ▼                    │
            ┌───────┐                │
            │ DOING │ ───────────────┼─► ┌─────────┐
            └───┬───┘                │   │ BLOCKED │
                │ /kanban:done       │   └─────────┘
                ▼                    │
            ┌───────┐                │
            │ DONE  │────────────────┘   (DONE is terminal)
            └───────┘
```

Invariants:

- **TODO → DOING**: set `started = now`; every `depends` id must be in `DONE`.
- **DOING → DONE**: set `completed = now`.
- **DOING → BLOCKED** (or TODO → BLOCKED): `custom.blocked_reason` must be non-empty; `started` preserved if set.
- **BLOCKED → TODO**: clear `custom.blocked_reason`.
- **DONE → anything**: forbidden. Create a new task if work must resume.

### 3.4 Directory Structure

```
plugins/kanban/
├── .claude-plugin/plugin.json
├── skills/
│   └── kanban-workflow/
│       ├── SKILL.md
│       └── references/
│           ├── schema-spec.md
│           ├── priority-rules.md
│           └── dependency-rules.md
├── commands/
│   ├── init.md               # /kanban:init
│   ├── next.md               # /kanban:next
│   ├── done.md               # /kanban:done
│   ├── block.md              # /kanban:block
│   ├── status.md             # /kanban:status
│   └── enable-automation.md  # /kanban:enable-automation
├── hooks/hooks.json
├── scripts/
│   ├── kanban-guard.sh           # PreToolUse: block direct edits
│   ├── kanban-autocommit.sh      # PostToolUse: standalone commits + sibling fan-out
│   ├── kanban-session-check.sh   # SessionStart + UserPromptSubmit: surface DOING/BLOCKED
│   ├── cron-runner.sh            # headless runner (installed by install-cron.sh)
│   └── install-cron.sh           # crontab installer
└── templates/
    ├── kanban.schema.json
    ├── kanban.empty.json
    └── kanban.example.json
```

### 3.5 Slash Commands

| Command | Args | Purpose |
|---|---|---|
| `/kanban:init` | `[--with-examples]` | Scaffold `kanban.json` + `kanban.schema.json` |
| `/kanban:next` | `[--category=X] [--priority=Y]` | Pick next eligible TODO, move to DOING, begin |
| `/kanban:done` | `[<task-id>] [--note=<text>]` | Close task (default: current DOING) |
| `/kanban:block` | `<task-id> --reason=<text>` | Move to BLOCKED with required reason |
| `/kanban:status` | | Read-only summary |
| `/kanban:enable-automation` | | Interactive: install cron or git hook |

Each command file has `argument-hint` frontmatter, explicit step lists, and absolute rules (no free-form AI interpretation of state transitions).

### 3.6 Hooks

```json
{
  "SessionStart": [{ "hooks": [{ "type": "command",
    "command": "bash ${CLAUDE_PLUGIN_ROOT}/scripts/kanban-session-check.sh" }] }],
  "UserPromptSubmit": [{ "hooks": [{ "type": "command",
    "command": "bash ${CLAUDE_PLUGIN_ROOT}/scripts/kanban-session-check.sh --lightweight" }] }],
  "PreToolUse": [{ "matcher": "Edit|Write|MultiEdit",
    "hooks": [{ "type": "command",
      "command": "bash ${CLAUDE_PLUGIN_ROOT}/scripts/kanban-guard.sh" }] }],
  "PostToolUse": [{ "matcher": "Bash|Write|Edit|MultiEdit",
    "hooks": [{ "type": "command",
      "command": "bash ${CLAUDE_PLUGIN_ROOT}/scripts/kanban-autocommit.sh" }] }]
}
```

Hook behaviour:

- `kanban-session-check.sh` (SessionStart) — surface DOING and BLOCKED tasks as `additionalContext`. Future: `git fetch` + detect remote drift.
- `--lightweight` (UserPromptSubmit) — DOING only; lower noise.
- `kanban-guard.sh` — exit 2 if Edit/Write/MultiEdit targets `kanban.json`; point at `/kanban:*` commands.
- `kanban-autocommit.sh` — if `kanban.json` is the only dirty file, commit standalone with transition-aware message (`kanban: task-042 TODO→DOING`). Then fans out to notify/memory if siblings are installed.

### 3.7 Capability Detection

`kanban-session-check.sh` and `kanban-autocommit.sh` both open with:

```bash
has_plugin() { command -v "workbench-$1" >/dev/null 2>&1; }
HAS_NOTIFY=0; has_plugin notify && HAS_NOTIFY=1
HAS_MEMORY=0; has_plugin memory && HAS_MEMORY=1
HAS_DOCSYNC=0; has_plugin docsync && HAS_DOCSYNC=1
```

Integration blocks only run when the corresponding flag is `1`. Absent siblings → silent no-op.

---

## 4. Plugin 2: `notify`

### 4.1 Role

Reach the user through an external channel when Claude Code needs attention — avoiding "AI stalls, user is AFK" deadlocks.

### 4.2 Trigger Events

Uses Claude Code's built-in `Notification` hook. Four event types:

| Event | Meaning | Default priority |
|---|---|---|
| `permission_prompt` | Claude wants permission for a tool | high |
| `elicitation_dialog` | Claude wants to ask the user | high |
| `idle_prompt` | Claude is idle waiting for input | normal |
| `auth_success` | Auth flow finished | low |

### 4.3 Provider Abstraction

```
┌────────────┐    ┌──────────────────┐    ┌────────────────────┐
│ Claude     │───►│ notify-dispatch  │───►│ Pushover / ntfy /  │
│ hook event │    │ (Python)         │    │ Slack / Telegram   │
└────────────┘    └──────────────────┘    └────────────────────┘
```

v0.1.0 ships Pushover only. Additional providers drop in without hook changes.

### 4.4 Config — `~/.claude-workbench/notify-config.json`

```jsonc
{
  "schema_version": 1,
  "default_provider": "pushover",
  "providers": {
    "pushover": {
      "enabled": true,
      "user_key": "${PUSHOVER_USER_KEY}",
      "app_token": "${PUSHOVER_APP_TOKEN}",
      "device": null,
      "sound_map": {
        "permission_prompt": "siren",
        "elicitation_dialog": "cosmic",
        "idle_prompt": "pushover",
        "auth_success": "none"
      }
    },
    "ntfy": { "enabled": false, "topic": "kirin-claude-code", "server": "https://ntfy.sh" }
  },
  "rules": [
    { "match": { "notification_type": "permission_prompt" }, "providers": ["pushover"], "priority": 1 },
    { "match": { "notification_type": "idle_prompt" },       "providers": ["pushover"], "priority": -1, "throttle_seconds": 300 }
  ]
}
```

- `${…}` env-var expansion. Never store plain secrets in config.
- `rules` per-event routing + priority + throttle.
- `throttle_seconds` caps idle-prompt spam.

### 4.5 Directory Structure

```
plugins/notify/
├── .claude-plugin/plugin.json
├── skills/notify-usage/SKILL.md
├── commands/{setup,test,config}.md
├── hooks/hooks.json
├── scripts/
│   ├── notify-dispatch.py
│   ├── providers/{pushover,ntfy,slack,telegram}.py
│   └── workbench-notify          # public CLI entry
└── templates/notify-config.example.json
```

### 4.6 Slash Commands

| Command | Purpose |
|---|---|
| `/notify:setup` | Interactive provider config (prompts for tokens) |
| `/notify:test` | Send a test message |
| `/notify:config` | Show or edit config |

### 4.7 Hooks

```json
{
  "Notification": [
    { "matcher": "permission_prompt|elicitation_dialog",
      "hooks": [{ "type": "command",
        "command": "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/notify-dispatch.py" }] },
    { "matcher": "idle_prompt",
      "hooks": [{ "type": "command",
        "command": "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/notify-dispatch.py --throttle 300" }] }
  ]
}
```

### 4.8 Public CLI

`workbench-notify` is the integration entry for sibling plugins:

```bash
workbench-notify \
  --title "Kanban" \
  --message "Task task-042 needs your decision" \
  --priority high \
  --provider pushover \
  --url "claude://resume-session/<session-id>"
```

Installed into `~/.claude-workbench/bin/` (must be on PATH).

### 4.9 Pushover Implementation Notes

- HTTPS POST to `https://api.pushover.net/1/messages.json`.
- 5-second timeout (hooks must not stall Claude).
- Failures append to `~/.claude-workbench/logs/notify-failures.log`; never block.
- Message scrubbed of token-shaped substrings (`sk-…`, `ghp_…`, etc.) before send.

---

## 5. Plugin 3: `memory`

### 5.1 Role

Persistent knowledge base across Claude Code sessions. Auto-captures session summaries, stores in SQLite with embeddings, and injects relevant prior memories at SessionStart.

### 5.2 Data Model — `memory.db`

```sql
CREATE TABLE memories (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    topic        TEXT NOT NULL,
    content      TEXT NOT NULL,
    tags         TEXT,                    -- JSON array
    source       TEXT,                    -- session_id, task_id, or 'manual'
    project      TEXT,                    -- hash(cwd)
    created_at   TEXT NOT NULL,           -- ISO 8601
    updated_at   TEXT NOT NULL,
    access_count INTEGER DEFAULT 0,
    last_access  TEXT
);
CREATE INDEX idx_project ON memories(project);
CREATE INDEX idx_created ON memories(created_at);
CREATE INDEX idx_tags    ON memories(tags);

-- Vector search via sqlite-vss
CREATE VIRTUAL TABLE memory_embeddings USING vss0(
    embedding(384)   -- sentence-transformers/all-MiniLM-L6-v2
);
```

File permissions: `600`. Project isolation via `hash(cwd)`.

### 5.3 Save Strategy

Three write paths:

1. **Explicit** — Claude calls MCP tool `memory.save(topic, content, tags)`.
2. **Implicit** — `Stop` hook runs a summariser at session end, extracting N key points.
3. **Manual** — user runs `workbench-memory save "…"`.

Embeddings generated locally via `sentence-transformers/all-MiniLM-L6-v2` (CPU, 384 dim, multilingual). No external API.

### 5.4 Retrieval Strategy

Three read paths:

1. **SessionStart injection** — queries top-K relevant memories for current `cwd`, injects as `additionalContext`.
2. **Explicit** — Claude calls `memory.search(query, limit)`.
3. **Manual** — `workbench-memory search "…"`.

Injection format:

```markdown
<!-- Injected by memory plugin -->
## Relevant memories from past sessions

### Bitfinex lending bot rate limit handling (2026-04-10)
…

### Claude Code auth on WSL2 (2026-04-15)
…
<!-- End memory injection -->
```

### 5.5 Directory Structure

```
plugins/memory/
├── .claude-plugin/plugin.json
├── skills/memory-workflow/
│   ├── SKILL.md
│   └── references/tagging-guide.md
├── commands/{init,save,search,list,forget,export}.md
├── hooks/hooks.json
├── .mcp.json                      # registers memory MCP server
├── mcp-server/
│   ├── server.py
│   ├── embedder.py
│   └── schema.sql
├── scripts/
│   ├── memory-inject.py          # SessionStart
│   ├── memory-summarize.py       # Stop
│   └── workbench-memory          # public CLI entry
└── templates/memory-config.example.json
```

### 5.6 MCP Server Tools

| Tool | Params | Returns |
|---|---|---|
| `memory.save` | topic, content, tags[] | memory_id |
| `memory.search` | query, limit=5, min_similarity=0.5 | matches[] |
| `memory.list_recent` | days=7, project=current | matches[] |
| `memory.get` | id | memory |
| `memory.update` | id, content, tags | memory |
| `memory.forget` | id | success |

### 5.7 Slash Commands

| Command | Purpose |
|---|---|
| `/memory:init` | Build SQLite + download embedding model |
| `/memory:save` | Manual save |
| `/memory:search <query>` | Manual retrieval |
| `/memory:list` | Recent N |
| `/memory:forget <id>` | Delete |
| `/memory:export` | Markdown backup |

### 5.8 Hooks

```json
{
  "SessionStart": [{ "hooks": [{ "type": "command",
    "command": "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/memory-inject.py" }] }],
  "Stop": [{ "hooks": [{ "type": "command",
    "command": "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/memory-summarize.py" }] }]
}
```

### 5.9 Retention

- Default: never auto-delete. User owns retention.
- `/memory:forget <id>` manual delete.
- `workbench-memory prune --older-than 365d --min-access 0` opt-in CLI.
- Future: cold-storage (out of embedding index, still queryable).

### 5.10 Public CLI

```bash
workbench-memory save --topic "…" --content "…" --tags "a,b"
workbench-memory search --query "…" --project current --limit 3 --format json
```

Installed into `~/.claude-workbench/bin/`.

---

## 6. Plugin 4: `docsync` (dev profile)

### 6.1 Role

Keep **code changes** and **documentation** in sync. Targets projects that maintain living docs (ARCHITECTURE.md, CODE_MAP.md, per-module README, …) and lose truthfulness as Claude edits code without touching corresponding docs.

### 6.2 Design Philosophy

**Config-driven, not prompt-driven**:

- Plugin ships only the *engine* (rules + hooks + commands).
- Per-project mapping lives in `.claude/docsync.yaml`, committed with the repo.
- The user never hand-writes the YAML — `/docsync:init` generates it interactively.

This turns the common "mapping rules hardcoded into CLAUDE.md" pattern into something structured, portable, and verifiable.

### 6.3 Interactive Onboarding Philosophy

`/docsync:init` demonstrates the Workbench family's recommended `init` UX:
**scan → infer → interview → validate**. A good AI onboarding behaves like an experienced consultant walking into an office — look around first, only ask what you genuinely need the human for. Full flow in §6.7.

### 6.4 Data Model — `.claude/docsync.yaml`

```yaml
schema_version: 1

# Docs the plugin asks Claude to read at SessionStart.
bootstrap_docs:
  - doc/ARCHITECTURE.md
  - doc/CODE_MAP.md
  - doc/DIRECTORY_TREE.md
  - doc/SPEC.md

# Code → doc update rules.
rules:
  - id: common-code-map
    pattern: "common/**"
    docs:
      - path: doc/CODE_MAP.md
        section: common
        required: true
      - path: doc/ARCHITECTURE.md
        required_if: architecture_changed

  - id: position-manager
    pattern: "position-manager/**"
    docs:
      - path: doc/CODE_MAP.md
        section: position-manager
      - path: position-manager/dynamic_param.md
        required_if: params_changed

# Allow Claude to skip doc updates in these contexts (semantic judgement,
# guided by the skill).
skip_conditions:
  - bug_fix_only
  - internal_refactor
  - test_only
  - comment_formatting_only

# How strict to be.
enforcement: warn       # warn | block | silent

# Sibling-plugin integration (optional).
integration:
  kanban:
    block_done_if_pending: false
  memory:
    summarize_doc_changes: true
```

Key fields:

| Field | Type | Notes |
|---|---|---|
| `rules[].id` | string | Identifier used in logs/errors. |
| `rules[].pattern` | glob | `common/**`, `src/api/*.rs`, … |
| `rules[].docs[].path` | string | File to update. |
| `rules[].docs[].section` | string | Optional — named section within a large doc. |
| `rules[].docs[].required` | bool | Default `true`. |
| `rules[].docs[].required_if` | enum | `architecture_changed` \| `api_changed` \| `params_changed` \| `schema_changed` |
| `skip_conditions` | enum[] | See list above. Semantic — Claude decides. |
| `enforcement` | enum | `silent` / `warn` / `block`. |

`required_if` values are **semantic**, not programmatic. The skill teaches Claude when each applies; the rule engine merely surfaces candidates.

`enforcement` semantics:

| Value | Effect |
|---|---|
| `silent` | Only `/docsync:check` surfaces pendings. |
| `warn` (default) | PostToolUse hook reminds Claude in context. |
| `block` | When kanban integration is enabled, DONE is gated on sync completion. |

### 6.5 Directory Structure

```
plugins/docsync/
├── .claude-plugin/plugin.json
├── skills/docsync-workflow/
│   ├── SKILL.md
│   └── references/
│       ├── update-patterns.md       # How to write CODE_MAP / ARCHITECTURE / README sections
│       └── skip-decision-tree.md    # When each skip_condition applies
├── commands/
│   ├── init.md                      # /docsync:init
│   ├── check.md                     # /docsync:check
│   ├── rules.md                     # /docsync:rules
│   ├── bootstrap.md                 # /docsync:bootstrap
│   └── validate.md                  # /docsync:validate
├── hooks/hooks.json
├── scripts/
│   ├── docsync-bootstrap.py         # SessionStart: inject bootstrap_docs reminder
│   ├── docsync-guard.py             # PostToolUse: detect pending sync
│   ├── docsync-finalcheck.py        # Stop: session-end summary
│   ├── rule-engine.py
│   └── workbench-docsync            # public CLI
└── templates/
    ├── docsync.example.yaml         # Rust monorepo
    ├── docsync.python.yaml
    └── docsync.js.yaml
```

### 6.6 Slash Commands

| Command | Args | Purpose |
|---|---|---|
| `/docsync:init` | `[--from-existing-claude-md]` | Interactively generate `.claude/docsync.yaml` |
| `/docsync:check` | `[<path>]` | Manually scan for pending syncs |
| `/docsync:rules` | `[<path>]` | Show rules; test what matches a given path |
| `/docsync:bootstrap` | | List bootstrap_docs read this session |
| `/docsync:validate` | | Validate YAML schema |

### 6.7 Interactive Init Flow

The core UX pattern. Five phases.

**Phase 1 — Scan** (silent):

1. Detect project type via: `Cargo.toml` + `[workspace]` (Rust monorepo), `pnpm-workspace.yaml`/`lerna.json` (JS monorepo), `pyproject.toml`/`setup.py` (Python), `go.mod` (Go), or multiple → mixed.
2. Enumerate code modules: top-level dirs minus `.git`, `node_modules`, `target`, `dist`, `.venv`, `doc*`, `.cache`.
3. Enumerate docs: `doc/`, `docs/`, `documentation/`, plus root-level `README`, `ARCHITECTURE`, `CODE_MAP`, `SPEC`, `DIRECTORY_TREE`, `CONTRIBUTING`; plus each module's `README.md`.
4. If `--from-existing-claude-md`: parse `CLAUDE.md` for existing mapping tables, pre-fill inferences.

**Phase 2 — Inquiry** (interactive, uses `AskUserQuestion`):

Summarise the scan first: "Found N modules, M docs." Then ask in batches of ≤3:

- **Batch 1 — Bootstrap docs**: multi-select which docs to load at SessionStart.
- **Batch 2 — Module → doc mapping**: per-module single-select (global CODE_MAP / module README / both / neither / custom).
- **Batch 3 — Enforcement**: `warn` (recommended) / `block` / `silent`.
- **Batch 4 — Skip conditions**: multi-select.
- **Batch 5 — Integration** (only if sibling installed): kanban DONE gate? memory summary?

**Phase 3 — Propose**:

Render the draft YAML as a single code block. Ask: "Does this look right?" Accept `yes` / `edit <section>` / `cancel`.

**Phase 4 — Dry-run validate** (the killer feature):

Before writing, prove the rules make sense against real history:

1. `git log --oneline -n 20`.
2. Pick 3 representative commits (cross-module, doc-heavy, code-only).
3. For each: list changed files, run rules, report what would have been flagged.

Example:

```
If docsync v1 had been active:

commit abc123 "refactor grid pricing"
├ changed: position-manager/src/grid.rs
└ would prompt: doc/CODE_MAP.md (position-manager section)
                position-manager/dynamic_param.md (grid params changed)

commit def456 "fix typo in comment"
├ changed: common/src/types.rs
└ would skip (matches skip_condition: comment_formatting_only)
```

Users grasp the rules from previews much faster than from YAML.

**Phase 5 — Write & next steps**:

1. Write `.claude/docsync.yaml`.
2. Ask whether to commit (default yes — team-shareable).
3. Verify `.claude/` isn't clobbered by gitignore rules that hide other project data.
4. Print next-steps summary.

### 6.8 Hooks

```json
{
  "SessionStart": [{ "hooks": [{ "type": "command",
    "command": "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/docsync-bootstrap.py" }] }],
  "PostToolUse": [{ "matcher": "Edit|Write|MultiEdit",
    "hooks": [{ "type": "command",
      "command": "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/docsync-guard.py" }] }],
  "Stop": [{ "hooks": [{ "type": "command",
    "command": "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/docsync-finalcheck.py" }] }]
}
```

Behaviour:

- `docsync-bootstrap.py` — read yaml, check `bootstrap_docs` existence, emit `systemMessage` reminder. Never blocks session start.
- `docsync-guard.py` — on each code edit, match rules, check whether any mapped doc was also edited this session. Per `enforcement`: silent / warn via `systemMessage` / block (only when kanban gate is active).
- `docsync-finalcheck.py` — session end: aggregate changes, report unsynced docs.

### 6.9 Skill

`skills/docsync-workflow/SKILL.md` teaches Claude:

1. **When `skip_conditions` apply** — semantic judgement (e.g. null-check fix = `bug_fix_only`; changing error-handling flow is NOT).
2. **How to write good doc updates** — `references/update-patterns.md` gives per-doc templates.
3. **Rule conflict resolution** — when a code change triggers two rules, how to prioritise.
4. **Absolute rules** — never skip a `required: true` doc to save time; never self-edit `.claude/docsync.yaml` (user owns it).

### 6.10 Public CLI

```bash
# Which rules match this path?
workbench-docsync match <file-path> --format json

# Any pending syncs since a git ref? (exit 0 = clean, 2 = pending)
workbench-docsync check --since <git-ref> --format json

# Summarise doc changes this session (for memory integration)
workbench-docsync summarize --session <session-id> --format json
```

All read-only. Never mutates the YAML.

### 6.11 Profile Classification

docsync is `dev` profile — not in the default `workbench` meta. Bundled into `workbench-dev` (§9.2).

---

## 7. Companion Tools

### 7.1 Viewer — `kanban-tui`

Standalone app for human-facing visualisation and editing of `kanban.json`. Does NOT depend on Claude Code — any schema-conforming viewer works.

**Implementation** (recommended): Python + [Textual](https://textual.textualize.io/).

- Single Python codebase, cross-platform.
- TUI + web (`textual serve`).
- Distribution: `pipx install kanban-tui`; PyInstaller binaries on GitHub Releases; Homebrew tap (future).

**MVP features**:

- Four-column view (TODO / DOING / DONE / BLOCKED).
- Task card: id, title, priority, category, tags.
- Expand card → description, comments, history.
- Keyboard nav: `j/k` select, `h/l` move columns, `n` new task, `e` edit.
- Schema validation before write.
- File watcher: auto-reload on external edits.

**Post-MVP**:

- Dependency DAG view.
- Gantt / timeline.
- Multi-project aggregated view.
- Web version (`textual serve`).
- VSCode extension (separate project).

### 7.2 Automation Runners

Let Claude Code run against kanban **without** a live session. Three modes:

#### 7.2.1 Cron polling (recommended default)

Installed by `/kanban:enable-automation`. Crontab line:

```cron
*/10 * * * * /home/kirin/.claude-workbench/bin/cron-runner.sh /home/kirin/myproject
```

`cron-runner.sh`:

1. `flock` guards against overlap.
2. `git pull --ff-only` (never merges).
3. Local pre-check: any ready TODO? (deps all DONE). If zero, exit early — no Claude invocation.
4. `claude -p "…"` with explicit `--allowedTools`, `--permission-mode acceptEdits`.
5. Logs to `~/.claude-workbench/logs/cron-runner.log`.

Uses the user's `claude login` (Pro/Max subscription). **No API credits consumed.**

#### 7.2.2 Git post-merge hook

Installed by `/kanban:enable-automation` mode 2. Fires only when `kanban.json` is in the pulled diff. Lower latency than cron but requires the user to `git pull` on the host machine.

#### 7.2.3 Webhook server (advanced)

A FastAPI server listening for GitHub webhooks. HMAC-verified. Triggers headless Claude when `kanban.json` changes land on `main`. Out of scope for v0.1.0 — deployment is user's responsibility.

#### 7.2.4 Cost

| Mode | Auth | Cost |
|---|---|---|
| Local cron | `claude login` (Pro/Max) | subscription |
| Local git-hook | `claude login` (Pro/Max) | subscription |
| Self-hosted webhook | `claude login` (Pro/Max) | subscription |
| GitHub Actions | `ANTHROPIC_API_KEY` | **API billed** |

Default docs recommend the first three. GitHub Actions is flagged "only when API billing is acceptable".

---

## 8. Cross-Plugin Integration

### 8.1 kanban × notify

Triggered inside `kanban-autocommit.sh` after a state transition:

| Event | Message | Priority |
|---|---|---|
| TODO → DOING (long tasks) | "Started: $title" | low |
| DOING → DONE | "Completed: $title" | normal |
| DOING → BLOCKED | "$id blocked: $reason" | high |
| `custom.needs_user_input == true` | "$id needs your decision" | high |

```bash
if [[ $HAS_NOTIFY -eq 1 ]]; then
    case "$prev->$new" in
        "TODO->DOING")    workbench-notify --priority low  --title "Kanban" --message "Started: $title" ;;
        "DOING->BLOCKED") workbench-notify --priority high --title "Kanban: action needed" --message "$tid blocked: $reason" ;;
        "DOING->DONE")    workbench-notify --priority normal --title "Kanban" --message "Completed: $title" ;;
    esac
fi
```

### 8.2 kanban × memory

**Scenario A — start**: `/kanban:next` prompt includes:

> Before executing the task, if `workbench-memory` is available: extract key terms from title+tags, run `workbench-memory search --query "<terms>" --limit 3 --format json`, and surface relevant matches before starting.

**Scenario B — done**: `kanban-autocommit.sh` on `DOING → DONE`:

```bash
if [[ $HAS_MEMORY -eq 1 ]]; then
    workbench-memory save \
        --topic "Task $tid: $title" \
        --content "$completion_note" \
        --tags "$tags" \
        --source "kanban:$tid"
fi
```

### 8.3 notify × memory

When `notify-dispatch.py` handles `elicitation_dialog`, it can carry prior decisions:

```python
if has_memory_plugin():
    past = subprocess.run(
        ["workbench-memory", "search",
         "--query", context, "--tags", "decision",
         "--limit", "1", "--format", "json"],
        capture_output=True, text=True, timeout=3
    )
    if past.stdout:
        msg += f"\n\n💭 Past decision: {json.loads(past.stdout)['content'][:200]}"
```

### 8.4 docsync × kanban

**DONE gate** (`integration.kanban.block_done_if_pending: true`):

`kanban-autocommit.sh` before confirming `DOING → DONE`:

```bash
if [[ $HAS_DOCSYNC -eq 1 ]]; then
    if ! workbench-docsync check --since "$(git merge-base HEAD main)" --format json \
        | jq -e '.pending | length == 0' >/dev/null; then
        echo "Task cannot be marked DONE: docsync has pending syncs" >&2
        workbench-docsync check --since "$(git merge-base HEAD main)"
        exit 2
    fi
fi
```

**Task-driven bootstrap extension**: if a task description mentions specific doc paths, docsync temporarily adds them to `bootstrap_docs` for that session.

### 8.5 docsync × memory

When `integration.memory.summarize_doc_changes: true`, `docsync-finalcheck.py` on session end:

```bash
if [[ $HAS_MEMORY -eq 1 ]]; then
    for doc in "${UPDATED_DOCS[@]}"; do
        summary=$(workbench-docsync summarize --file "$doc" --format json)
        workbench-memory save \
            --topic "Doc update: $doc" \
            --content "$summary" \
            --tags "docsync,$(basename $doc .md)" \
            --source "docsync:$SESSION_ID"
    done
fi
```

Memory then recalls "last time we changed this kind of code, here's how we updated the doc" on the next similar edit.

### 8.6 docsync × notify (passive)

docsync never calls notify directly — doc drift is not worth a push. **However** when `enforcement: block` gates a kanban DONE (§8.4), the blocked transition fires through kanban's notify integration (§8.1) with `needs_user_input = true`.

### 8.7 Capability Detection Standard

Every integration-aware script opens with:

```bash
has_plugin() { command -v "workbench-$1" >/dev/null 2>&1; }
HAS_KANBAN=0;  has_plugin kanban  && HAS_KANBAN=1
HAS_NOTIFY=0;  has_plugin notify  && HAS_NOTIFY=1
HAS_MEMORY=0;  has_plugin memory  && HAS_MEMORY=1
HAS_DOCSYNC=0; has_plugin docsync && HAS_DOCSYNC=1
```

Caveat: `command -v` only proves the CLI exists, not that the sibling is configured. Future refinement: each CLI gains a `--health` subcommand returning exit 0 when ready — detection uses that.

### 8.8 End-to-end UX when all enabled

```
[09:00] User adds task-050 "Refactor lending bot pricing" in viewer before leaving home

[09:15] Cron fires → headless Claude starts
        [SessionStart hooks]
        ├─ kanban:    sees task-050 in TODO → auto /kanban:next
        ├─ memory:    injects "2024-03: similar refactor used EMA smoothing"
        └─ docsync:   reminder to read doc/ARCHITECTURE.md + position-manager/README.md

[09:20] Claude refactors; hits a rate-limit design decision
        [elicitation_dialog event]
        ├─ notify:    Pushover pushes to phone:
        │     "Decide: token bucket or leaky bucket?
        │      💭 Past decision: 2025-12 you chose token bucket"
        └─ Claude waits

[09:22] User on commute, replies "token bucket" via iOS app

[09:30] Claude finishes coding; tries to /kanban:done
        ├─ docsync gate: pending sync on position-manager/dynamic_param.md
        ├─ Claude updates the doc
        └─ retry DONE → passes gate

[09:31] State fan-out
        ├─ kanban:    DOING → DONE, autocommit
        ├─ notify:    Pushover "task-050 complete"
        ├─ memory:    saves "task-050: chose token bucket, reason …"
        └─ docsync:   memory-saves "position-manager/dynamic_param.md updated: …"

[19:00] User returns, opens viewer: task-050 DONE with complete timeline + decision trail
```

---

## 9. Meta-plugins

### 9.1 `workbench` (core bundle)

```json
{
  "name": "workbench",
  "version": "0.1.0",
  "description": "Complete Claude Workbench — kanban + notify + memory",
  "author": "kirin",
  "dependencies": [
    { "name": "kanban", "version": "^0.1.0" },
    { "name": "notify", "version": "^0.1.0" },
    { "name": "memory", "version": "^0.1.0" }
  ]
}
```

No commands/skills/hooks of its own — pure dependency declaration.

### 9.2 `workbench-dev` (dev bundle)

```json
{
  "name": "workbench-dev",
  "version": "0.1.0",
  "description": "Claude Workbench for developers — core + docsync + (future: review, lint)",
  "author": "kirin",
  "dependencies": [
    { "name": "workbench", "version": "^0.1.0" },
    { "name": "docsync",   "version": "^0.1.0" }
  ]
}
```

Layered on top of `workbench` to avoid version drift between the core three.

---

## 10. Repository Structure

```
kirin/claude-workbench/
├── README.md
├── LICENSE                                  # MIT
├── CHANGELOG.md
├── SPEC.md                                  # this file
├── current_state.md                         # impl snapshot
│
├── .claude-plugin/
│   └── marketplace.json                     # 6 entries (4 plugins + 2 meta)
│
├── plugins/
│   ├── kanban/                              # §3
│   ├── notify/                              # §4
│   ├── memory/                              # §5
│   ├── docsync/                             # §6
│   ├── workbench/                           # §9.1 meta
│   └── workbench-dev/                       # §9.2 meta
│
├── viewer/                                  # §7.1 (optional)
│   ├── pyproject.toml
│   └── src/kanban_tui/
│
├── automation/                              # §7.2 canonical runner sources
│   ├── cron-runner.sh
│   ├── git-hooks/post-merge
│   ├── webhook-server.py
│   └── systemd/kanban-agent.service
│
├── schema/                                  # canonical schemas
│   ├── kanban.schema.json
│   └── docsync.schema.json
│
├── docs/
│   ├── quickstart.md
│   ├── architecture.md
│   ├── composition.md                       # how plugins compound
│   ├── provider-setup/{pushover,ntfy}.md
│   ├── plugin-development.md
│   └── troubleshooting.md
│
├── scripts/                                 # CI helpers
│   ├── sync-schema.sh                       # schema/ → plugins/*/templates/
│   ├── sync-automation.sh                   # automation/ → plugins/kanban/scripts/
│   └── validate-plugins.sh
│
└── .github/workflows/
    ├── ci.yml                               # lint, test, validate-plugins
    ├── release-viewer.yml
    └── release.yml
```

### 10.1 `marketplace.json` (6 entries)

```json
{
  "name": "claude-workbench",
  "owner": { "name": "Kirin" },
  "plugins": [
    { "name": "kanban",  "source": "./plugins/kanban",  "description": "Kanban workflow", "category": "productivity", "keywords": ["kanban","tasks"] },
    { "name": "notify",  "source": "./plugins/notify",  "description": "Push notifications", "category": "productivity", "keywords": ["notifications","pushover"] },
    { "name": "memory",  "source": "./plugins/memory",  "description": "Persistent RAG memory", "category": "productivity", "keywords": ["memory","rag"] },
    { "name": "docsync", "source": "./plugins/docsync", "description": "Code ↔ doc sync tracking", "category": "developer-tools", "keywords": ["docs","drift"] },
    { "name": "workbench",     "source": "./plugins/workbench",     "description": "★ Core bundle (kanban + notify + memory)", "category": "productivity", "keywords": ["bundle","meta"] },
    { "name": "workbench-dev", "source": "./plugins/workbench-dev", "description": "★ Dev bundle (workbench + docsync)", "category": "developer-tools", "keywords": ["bundle","meta"] }
  ]
}
```

### 10.2 Schema Sync Strategy

`schema/*.json` is canonical. CI (`scripts/sync-schema.sh`) copies to:

- `plugins/kanban/templates/kanban.schema.json`
- `plugins/docsync/templates/docsync.schema.json`
- `viewer/src/kanban_tui/schema.json`

One source, three mirrors, zero hand-editing.

### 10.3 Automation Sync Strategy

`automation/*` is canonical. CI (`scripts/sync-automation.sh`) copies the scripts that need to ship *inside* the plugin (for `/kanban:enable-automation` access) to `plugins/kanban/scripts/`.

---

## 11. Security

### 11.1 Plugin Security

- All hook scripts use `set -euo pipefail`.
- `kanban-guard.sh` rejects any attempt to bypass the schema (direct Edit/Write on `kanban.json`).
- Never execute arbitrary strings from `kanban.json`, `memory.db`, or `.claude/docsync.yaml` content.
- `--allowedTools` is always an explicit whitelist. No wildcards.

### 11.2 Automation Security

- Webhook servers must verify HMAC signatures.
- Cron runners use `flock` against re-entry.
- Runner log files must not contain full message bodies (avoid secret leak via log).
- User responsible for keeping `kanban.json` / `memory.db` / `docsync.yaml` free of secrets; hook-level secret scanning is future work.

### 11.3 Memory Privacy

- All data local. Embedding model runs on-device.
- `memory.db` default perms `0600`.
- Project isolation via `hash(cwd)`; never leak across projects unless user explicitly queries global.

### 11.4 Notify Security

- HTTPS-only for all providers.
- Response bodies never written back into `kanban.json` or `memory.db`.
- Message scrubber masks token-shaped substrings before send.

### 11.5 Secret Handling

- `${ENV_VAR}` expansion in configs; never inline secrets in JSON.
- Document `.env` + `direnv` as the recommended pattern.
- `.gitignore` templates for each profile.

### 11.6 Supply Chain

- Release binaries with SHA256.
- Signed git commits.
- Sigstore / cosign under consideration.

### 11.7 Privacy

- No telemetry.
- No third-party data egress (except the Anthropic API itself when using headless).
- Headless conversations follow Anthropic privacy policy.

---

## 12. Versioning & Release

Monorepo uses a unified Semantic Version:

- **MAJOR** — any plugin breaks its schema or public API.
- **MINOR** — new features, new plugins.
- **PATCH** — bug fixes.

Meta-plugin dependencies use caret range (`^0.1.0`) so minor bumps propagate automatically.

Release flow:

1. Update `CHANGELOG.md`.
2. Update versions in all `plugin.json` + `marketplace.json` (script helper).
3. `git tag v0.2.0 && git push origin v0.2.0`.
4. CI validates plugins, syncs schemas, builds viewer (3 platforms), publishes GitHub Release + PyPI package.

Users upgrade with:

```bash
/plugin update kanban@claude-workbench         # single plugin
/plugin update workbench@claude-workbench      # core bundle
/plugin update workbench-dev@claude-workbench  # dev bundle
```

Breaking schema bumps ship a migration CLI:

```bash
kanban-tui migrate --from 1 --to 2 kanban.json
```

---

## 13. MVP Roadmap

| Phase | Target | Status |
|---|---|---|
| **0a** — Workbench skeleton (marketplace, stub plugins, schema) | v0.1.0 bootstrap | ✓ shipped |
| **0b** — kanban finalising (`/kanban:block`, `/kanban:enable-automation`, cron scripts) | v0.1.0 kanban | ✓ shipped |
| **1** — kanban v0.1.0 validation | 1 week real-project usage | in progress |
| **2** — notify v0.1.0 (Pushover + `workbench-notify` CLI) | 1 week | pending |
| **3** — kanban × notify integration | 2–3 days | pending |
| **4** — memory v0.1.0 (SQLite + MCP + embeddings) | 2 weeks | pending |
| **5** — three-way integration (§8.8 E2E flow) | 1 week | pending |
| **6** — `workbench` bundle release | 0.5 week | pending |
| **7** — docsync v0.1.0 + `workbench-dev` bundle | 2 weeks | pending |
| **8+** (v0.2+) — additional notify providers; memory cold-storage / cross-project; viewer DAG + web; kanban webhook runner; `review`/`lint`/`schedule` new plugins | ongoing | backlog |

docsync is deliberately last in the sequence — it depends on the mature cross-plugin integration pattern that earlier phases establish.

---

## 14. Open Questions

Numbered for easy reference across discussions:

1. **Task ID generation**: monotonic (`task-043`) vs hash (`task-a4f2`)? Monotonic clashes in multi-user.
2. **DONE archival**: when to move old DONE tasks to `kanban-archive/YYYY-MM.json`? By count? Age? Size?
3. **Concurrent headless Claude**: multiple cron runners on different machines hitting the same repo — is `DOING + timestamp` a sufficient lock?
4. **Viewer write conflicts**: last-write-wins + file watcher reload (v0.1) or CRDT (future)?
5. **Schema extension mechanism**: users wanting first-class fields beyond `custom` — support project-local schema extension?
6. **Multi-repo aggregation**: global kanban view across projects — useful or bloat?
7. **Memory scope / cross-project search**: privacy implications if enabled.
8. **Notify rate limiting**: UX pattern to avoid alert fatigue?
9. **Plugin version skew**: kanban v0.2 (new schema) + notify v0.1 still installed — graceful handling?
10. **Viewer inclusion in marketplace**: PyPI/standalone only, or also marketplace entry?
11. **Memory embedding model install UX**: ~80 MB first download — progress bar? Lazy on first save?
12. **docsync section-level granularity**: how to detect "user updated section X" — heading markers, or conservative "any edit = synced"?
13. **docsync semantic conditions**: `required_if: api_changed` — how far can the skill push Claude's judgement before v0.2?
14. **docsync multi-language monorepo**: template composition strategy when Rust + Python + shell mix.
15. **docsync rename/move**: `git mv` as a code change — does it trigger rules? What if the old filename appears in a doc?
16. **docsync ↔ CLAUDE.md coexistence**: prompt the user to remove CLAUDE.md sections docsync now owns, or let them coexist?
17. **docsync perf at scale**: `/docsync:check --since main` over a large monorepo — cache strategy?

---

## 15. References

- [Claude Code Plugins — docs](https://code.claude.com/docs/en/plugins)
- [Claude Code Plugins — reference](https://code.claude.com/docs/en/plugins-reference)
- [Claude Code Hooks — reference](https://code.claude.com/docs/en/hooks)
- [Claude Code Headless mode](https://code.claude.com/docs/en/headless)
- [Claude Code `AskUserQuestion` tool](https://code.claude.com/docs/en/plugins-reference#ask-user-question)
- [Model Context Protocol](https://modelcontextprotocol.io)
- [JSON Schema draft-07](https://json-schema.org/draft-07)
- [sqlite-vss](https://github.com/asg017/sqlite-vss)
- [sentence-transformers](https://www.sbert.net/)
- [Pushover API](https://pushover.net/api)
- [Textual](https://textual.textualize.io/)
- Prior art: Obsidian Kanban plugin, GitHub Projects, Linear API.

---

## Appendix A — Installation UX scripts

### A.1 Progressive install

```bash
# Day 1 — just kanban
$ claude
> /plugin marketplace add kirin/claude-workbench
> /plugin install kanban@claude-workbench
> /kanban:init --with-examples
> /kanban:next

# Day 7 — add notifications
> /plugin install notify@claude-workbench
> /notify:setup       # guided Pushover config
> /notify:test

# Day 14 — add memory
> /plugin install memory@claude-workbench
> /memory:init        # downloads embedding model, builds SQLite

# Day 21 — add docsync (dev profile, opt-in)
> /plugin install docsync@claude-workbench
> /docsync:init       # interactive scan → interview → dry-run → write
```

### A.2 One-shot bundles

```bash
# Core only
> /plugin install workbench@claude-workbench
> /kanban:init && /notify:setup && /memory:init

# Developer full stack
> /plugin install workbench-dev@claude-workbench
> /kanban:init && /notify:setup && /memory:init && /docsync:init
```

### A.3 Automation enablement

```bash
> /kanban:enable-automation

Claude: Which trigger?
  1. Cron polling (every 10 min, recommended)
  2. Git post-merge hook

User: 1
Claude: Interval? (default 10)
User: 10

Claude: Installing…
Installed:
  */10 * * * * /home/kirin/.claude-workbench/bin/cron-runner.sh /home/kirin/my-project
Logs: ~/.claude-workbench/logs/cron-runner.log
Remove: crontab -e and delete the tagged lines.
```

---

## Appendix B — Plugin Interaction Matrix

Rows = consumer. Columns = provider. Cell = what the consumer gets when the provider plugin is installed.

| | kanban | notify | memory | docsync |
|---|---|---|---|---|
| **kanban** | — | Task-transition push | Past-work lookup on next; save on done | DONE gate (when enforcement=block) |
| **notify** | State-transition trigger | — | "Past decision: …" in prompts | — (docsync doesn't push directly) |
| **memory** | Task events → save | — | — | Doc-change summaries |
| **docsync** | Task description → bootstrap extension | — | Write-through summary | — |

Empty cell ≠ "not possible" — just not wired in v0.1.0. New integrations may be added in minor releases without schema bumps.

---

*End of SPEC.md*
