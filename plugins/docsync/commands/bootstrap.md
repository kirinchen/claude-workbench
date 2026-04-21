---
description: List the bootstrap docs docsync asks Claude to read at session start.
allowed-tools: Read, Bash(workbench-docsync:*), Bash(test:*)
---

# /docsync:bootstrap

## 1. Load

```bash
workbench-docsync rules --format json
```

Extract `bootstrap_docs` from the output.

## 2. Render

For each entry:
- Show the path.
- Mark whether the file currently exists.
- If it exists and is small (< 50 KB), offer to read it now ("read all" / "read one" / "skip").
- If it's missing, flag as a config drift issue — the YAML references a file that no longer exists.

## 3. If the user asks you to "load them"

Read each present bootstrap doc in order. After reading, produce a short per-doc summary (2–3 sentences) so the user can sanity-check that the docs they're bootstrapping on are still truthful.

## Absolute rules

- Do NOT auto-read every bootstrap doc on invocation — that's expensive and usually unwanted. Ask first.
- Never fabricate a summary if you haven't actually read the doc this session.
