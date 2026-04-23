# Mentor — SOLID Refactor Backlog

> Tracking document for SOLID-principle violations identified in `plugins/mentor/` v0.1.0.
> **Not** a commitment to refactor now — this captures friction points so we recognise them when the first real extension request shows up. Premature abstraction is a worse outcome than the violations themselves.

---

## Status

- **Created**: 2026-04-23
- **Source**: ad-hoc audit during quickstart docs review (no real-world extension request yet)
- **Action**: defer — wait for the first concrete trigger before refactoring

---

## Triggers that should prompt revisiting this doc

Refactor when **any** of these happen:

1. Someone wants a **new document type** beyond Epic/Sprint/Issue/ADR (e.g. RFC, Postmortem, Runbook).
2. Someone wants a **new framework mode** beyond `basic` / `development` (e.g. `research`, `maintenance`).
3. Someone wants to add a **third sibling integration target** beyond kanban/memory/notify (e.g. Linear, Jira, GitHub Projects).
4. The Stop-hook fan-out logic (`mentor-finalcheck.py`) gets a fourth concern bolted on and starts feeling unmaintainable.
5. `framework_engine.py` exceeds ~700 lines or someone has trouble locating a function in it.

If none of the above happens within 2–3 mentor versions, this backlog can be closed as YAGNI.

---

## Violations identified

### 1. OCP — adding a new document type touches 5+ places

**Severity**: 🔴 highest impact

To add a new document type (say `RFC`):

| File | Change required |
|---|---|
| `plugins/mentor/scripts/mentor-guard.py` | Add `"rfc": {"id", "title", "status", ...}` to `REQUIRED_BY_TYPE` |
| `plugins/mentor/frameworks/development/templates/RFC/RFC-template.md` | Create the template |
| `plugins/mentor/frameworks/development/framework.yaml` | Add `scaffold` entry |
| `plugins/mentor/commands/new.md` | Update parser to accept `rfc` as first positional |
| `plugins/mentor/scripts/workbench-mentor.py` | Update `new` subcommand if it has type-specific logic |
| `plugins/mentor/skills/mentor-workflow/SKILL.md` + `references/` | Document when to use RFC |

**Ideal shape**: `framework.yaml` declares each doc type's required frontmatter and template, and the code is generic:

```yaml
doc_types:
  epic:
    required_frontmatter: [id, title, status]
    template: Epic/epic-template.md
    path_key: epic
  rfc:    # adding this is the only change needed
    required_frontmatter: [id, title, status, decision_date]
    template: RFC/RFC-template.md
    path_key: rfc
```

`mentor-guard.py` reads `doc_types` from config and enforces dynamically. `/mentor:new` becomes generic over registered types.

### 2. SRP — `framework_engine.py` is a god module

Currently handles:
- YAML loading (with PyYAML preferred + fallback subset parser)
- `.env`-style config search and loading
- Frontmatter parsing
- `MentorConfig` dataclass + sub-dataclasses
- Active-sprint resolution
- Trace algorithm (task → issue → epic)
- Review / violation detection
- Capability detection (`has_sibling`, `kanban_installed`)

**Ideal split**:

```
plugins/mentor/scripts/mentor/
├── config.py        — MentorConfig + load_config + find_config
├── yaml_compat.py   — PyYAML preferred + fallback parser
├── frontmatter.py   — parse_frontmatter + read_frontmatter
├── trace.py         — active_sprint + trace_task
├── review.py        — review + Violation
└── capability.py    — has_sibling + kanban_installed
```

Imports stay backward-compatible by re-exporting from `framework_engine.py` initially, then call sites move over time.

### 3. SRP — `mentor-finalcheck.py` Stop hook does three things

- Compliance summary (read-only)
- Memory fan-out for accepted ADRs (write to memory CLI)
- Memory fan-out for finished sprint retros (write to memory CLI)

The "fan-out to memory" logic is hard-coded. Adding a "fan-out to notify on Epic-done" or "fan-out to Linear" means more `if` branches in the same file.

**Ideal shape**: declarative event → handler mapping driven by `.claude/mentor.yaml`:

```yaml
on_session_end:
  - event: adr_accepted
    target: memory
    enabled: auto
  - event: sprint_retro_finalised
    target: memory
    enabled: auto
  - event: epic_done           # future
    target: notify
    enabled: auto
```

`mentor-finalcheck.py` becomes a generic dispatcher; each `target` has a small adapter (`adapters/memory.py`, `adapters/notify.py`).

### 4. ISP — `MentorConfig` exposes everything to every consumer

`MentorConfig` carries `paths`, `id_patterns`, `agent_behavior`, `templates`, `integration` all at once. Consumers only need slices:

| Consumer | Actually needs |
|---|---|
| `mentor-bootstrap.py` (SessionStart) | `agent_behavior.bootstrap_docs`, `paths.sprint`, `paths.issue` |
| `mentor-guard.py` (PreToolUse) | `paths.*`, doc-type required-frontmatter map |
| `mentor-finalcheck.py` (Stop) | `integration.*`, `paths.adr`, `paths.sprint` |
| `workbench-mentor trace` | `paths.*` |
| `workbench-mentor --health` | nothing — just "is config loadable" |

**Ideal shape**: typed protocol-style accessors (`config.for_bootstrap()`, `config.for_guard()`) returning narrowed views. Smaller blast radius when adding fields, easier to mock in tests.

### 5. DIP — sibling fan-out hardcodes CLI invocation

`mentor-finalcheck.py` calls `subprocess.run(["workbench-memory", "save", "--topic", ...])` directly. Couples mentor to the exact memory CLI shape. If memory CLI changes argument order or renames `--topic`, mentor breaks silently.

**Ideal shape**: an `Adapter` interface per sibling (`MemoryAdapter`, `NotifyAdapter`) with stable mentor-side method names (`adapter.save_adr(adr)`, `adapter.notify_event(event)`). Adapter implementations encapsulate the CLI quirks.

This pairs with violation #3 (declarative fan-out).

### 6. OCP — new framework mode requires new directory tree + possibly code

Adding a `research` mode means:
- Duplicating most of `frameworks/development/templates/` into `frameworks/research/templates/`
- Adding `frameworks/research/framework.yaml`
- Possibly updating `/mentor:init` if interview questions differ

The first two are fine (template content is external). The interview-question coupling is where it can leak into code.

**Ideal shape**: framework declares its own interview questions (Phase 2/3/4 of `/mentor:init`) in `framework.yaml`, and the slash command renders them generically. Currently the slash command has a fixed shape with hard-coded "first sprint" question that's only meaningful in `development`.

---

## Non-issues (looked, found acceptable)

- **Capability detection (`has_sibling`, `--health` contract)** — already abstracted correctly. Sibling integration is opt-in and doesn't crash when the sibling is absent.
- **`schema_version` in `.claude/mentor.yaml`** — gives us a migration story for future config shape changes. Good.
- **Templates as external `.md` files** — adding fields to existing templates is a content edit, no code change needed. Good for the "evolving template" axis.
- **LSP** — barely applicable. There's no real subclass hierarchy to violate. The two modes are config branches, not type subclasses.

---

## Refactor priority (when triggered)

When the trigger fires, work in this order:

1. **#1 (OCP — doc types)** — highest user-visible impact; biggest leverage if RFC/Postmortem/Runbook becomes a real ask.
2. **#3 (SRP — finalcheck) + #5 (DIP — adapter)** — pair these; the declarative fan-out only works if adapters exist.
3. **#2 (SRP — god module split)** — mechanical refactor, do once #1 and #3 are settled so we know the import shape.
4. **#4 (ISP — narrow views)** — nice-to-have; only worth doing if test mocking actually hurts.
5. **#6 (OCP — modes)** — only relevant when a third mode is requested.

---

## Out of scope for this doc

- Adding the actual RFC / Postmortem / Runbook doc types (separate spec when needed).
- Migrating to a real plugin framework (the engineering cost dwarfs SOLID gains at this scale).
- Test coverage gaps — track separately; SOLID and tests are different concerns.

---

## See also

- [`epic/mentor-plugin-spec.md`](./mentor-plugin-spec.md) — original mentor design (the v0.1.0 implementation matches this)
- [`plugins/mentor/scripts/framework_engine.py`](../plugins/mentor/scripts/framework_engine.py) — the god module under audit
- [`plugins/mentor/scripts/mentor-finalcheck.py`](../plugins/mentor/scripts/mentor-finalcheck.py) — the multi-concern Stop hook
