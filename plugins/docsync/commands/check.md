---
description: Scan for pending doc syncs since a git ref.
argument-hint: [<git-ref>] [--format=json|text]
allowed-tools: Bash(workbench-docsync:*)
---

# /docsync:check

Arguments: `$ARGUMENTS` — either a git ref (default `HEAD~1`) or `--format=json`.

## 1. Parse

- First positional → git ref. Examples: `HEAD~5`, `main`, `abc123`, `$(git merge-base HEAD main)`.
- `--format=json|text` → default `text` (nicer for interactive use).

## 2. Run

```bash
workbench-docsync check --since "$REF" --format "$FORMAT"
```

Exit codes:
- 0 → clean. Report: "✓ no pending syncs since $REF".
- 2 → pendings. Surface the output verbatim, then list concrete next actions:
  - Which doc files to read first (only the required ones).
  - Which `required_if` conditions need a judgement call.
- 1 → error. Surface stderr; tell the user to run `/docsync:validate`.

## 3. Do NOT auto-fix

Never offer to "update the doc for you" from inside this command. `check` is diagnostic. The user decides whether to run a dedicated edit flow — or ask Claude to update docs in a separate turn.

## Absolute rules

- Never write any file from this command.
- Never silently exit 0 when exit code was 2.
- Never invoke `workbench-docsync summarize` from here — that's for the Stop hook.
