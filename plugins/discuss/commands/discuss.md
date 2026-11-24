---
description: Open a file in porthole's editor next to a conversation that is this same terminal session.
argument-hint: "[file — existing, or a new .md; empty = a fresh markdown file]"
allowed-tools: Bash(python3:*)
---

# /discuss

Arguments: `$ARGUMENTS`

## Run

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/discuss.py" open "$ARGUMENTS"
```

It finds the running porthole, creates the markdown file if it is missing, picks
the file's conversation, and binds it to **this** session. It prints one JSON
line: `{"url", "file", "created", "thread", "continued", "terminal", "mode"}`.

- **Non-zero exit** → relay the error text as it is (it says how to install,
  start, or point at porthole) and stop. Do not fall back to another editor.

## Report

Three lines at most, and always the full URL:

```
discuss → <url>
<file> (<"new file" if created, "continuing an earlier conversation" if continued>)
<mode "two-way":> Whatever you say here or in porthole is the same conversation.
<mode "one-way":> One-way: what you say here shows up in porthole, but porthole cannot send to this terminal (no hc / herdr-core here). After you close this session you can continue it from porthole.
```

Then stop and let the user talk. From here on follow the `discuss-session` skill:
messages starting with `[porthole]` are the user, typing in the browser.
