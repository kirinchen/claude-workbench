# Skip-condition decision tree

docsync rule engine surfaces candidate doc updates; you decide whether each is needed. The YAML declares allowed skips via `skip_conditions:` and conditional requirements via `required_if:`. This file defines each value.

## `skip_conditions`

A skip condition **entirely exempts** a code change from the corresponding doc update. Be strict — over-skipping is the failure mode docsync exists to prevent.

### `bug_fix_only`

Apply when **all** of:
- The code change fixes a defect in existing behaviour.
- The module's observable behaviour *after* the fix matches the doc's claim about it.
- No new public API, config parameter, invariant, or error mode was introduced.

**Do NOT apply when**:
- The "bug" was that the doc over-promised — then the doc is what needs updating.
- The fix changed timing, concurrency, or failure semantics visibly.
- You added a new return value, error type, or log level.

### `internal_refactor`

Apply when **all** of:
- The edit is purely structural (extract function, rename private identifier, move code between files within the same module).
- No public API surface changed.
- No tests needed to be modified to keep them passing.

**Do NOT apply when**:
- A private helper was promoted to public.
- Files moved between modules (that's an architecture change).
- A class was split even if the facade stayed stable — downstream readers may care.

### `test_only`

Apply when the ONLY files changed are tests or test fixtures. If any non-test file changed, this doesn't apply.

### `comment_formatting_only`

Apply when the diff contains only: comment changes, whitespace changes, or reformatter output. If the reformatter happened to surface a dead-code warning you fixed, that's not comment_formatting_only.

## `required_if` semantic conditions

Each value is evaluated against the full diff, not individual files.

### `architecture_changed`

Applies when any of:
- A new module was added to the workspace.
- A module was removed, renamed, or merged.
- Dependency direction between modules flipped.
- A sync boundary (process, thread, async runtime) moved.

NOT:
- Changing how an existing module works internally.
- Adding a new file inside an existing module.

### `api_changed`

Applies when any of:
- A public function/method's signature changed (params, return, error type).
- A public type's shape changed (fields added/removed/renamed).
- An endpoint was added, removed, or its path/method changed.

NOT:
- Internal helper signatures.
- Comment/doc-string changes on public APIs (update the API doc, but not via api_changed).

### `params_changed`

Applies when any of:
- A tunable config parameter was added, removed, or renamed.
- A parameter's default changed.
- A parameter's valid range or semantics changed.

Signal: if a user-facing config file, env var, CLI flag, or TOML/JSON key is involved, this usually fires.

### `schema_changed`

Applies when a data schema (JSON Schema, OpenAPI, SQL DDL, Proto, Avro) had a field added, removed, renamed, or retyped.

Do NOT fire for comment-only schema changes.

## Combining conditions

If a single doc rule has `required_if: api_changed` and you believe the change is also `internal_refactor`:

- `skip_conditions` wins over `required_if` ONLY when the skip is narrower. `internal_refactor` is narrow and requires no public surface change; if `api_changed` actually fires, `internal_refactor` cannot have applied. In practice these two shouldn't both be true.

If in doubt: **update the doc**. False positives are a minor nuisance; false negatives rot the repo.

## Documenting your skip

When you decide to skip, state which condition and why *inline in your response* (not in a file). A typical one-liner:

> docsync: skipping `doc/ARCHITECTURE.md` — change is `internal_refactor` per rule `position-manager` (no cross-module dependency direction changed, no new module).

That audit trail is what makes the config-driven approach beat the hardcoded-in-CLAUDE.md approach: your reasoning is reviewable.
