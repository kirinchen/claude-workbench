---
description: Compose a message into another tmux session's input box without sending it — you press Enter yourself.
argument-hint: <session> <what to say>
allowed-tools: Bash(bash:*), Bash(python3:*)
---

# /tmux:draft

Arguments: `$ARGUMENTS`

- `$1` — the session name (exact; get it from `/tmux:ls`).
- Everything after it — the description of what to say. Required.

Put composed text **into** the target's input box and stop there. Nothing is
submitted. The human reads it in the other pane and presses Enter — or edits
it, or clears it. Use `/tmux:send` when the intent is to actually send.

## 1. Read the current box

```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/tmux-input.sh "$1" --get
```

Exit 2 → no such session; the script printed the live list. Relay and stop.

Then branch on what came back:

- `ui: "dialog"` → **stop**. The target is waiting on a selector; typing would
  move the selection. Tell the user to answer it first.
- `status: "busy"` / `"busy+queued"` → still fine to draft (the box accepts
  text while it works), but say in the report that the target is busy, so
  pressing Enter will queue the message rather than start it.
- `has_draft: true` → this is a **rewrite**. Read `draft` and treat it as the
  starting point: fold the user's description into it rather than discarding
  what is already there. Quote the old draft in your report so the loss is
  visible if you did discard it.
- `has_draft: false` but `ghost` is non-empty → the box is **empty**; that
  faint text is a placeholder for input abandoned earlier, not a draft.
  Write fresh and do not try to preserve it. Typing replaces it outright.
- `has_draft: false` → write it fresh.

## 2. Compose

Write the message the description asks for, in the user's language. One line —
`tmux-input.sh` rejects embedded newlines, because a literal newline submits
the message early. Keep it to something a human can eyeball in one glance.

## 3. Place it

```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/tmux-input.sh "$1" --set "<composed text>"
```

`--set` clears the box (looped `End` + `C-u`) and types the new text with
`send-keys -l`. **No Enter is ever sent.** The script prints the resulting
state; check that `draft` matches what you intended.

If it does not match, say so plainly rather than retrying blind — a partial
overwrite is worse than a visible failure.

## 4. Report

```
<session> — drafted, not sent

  <the text now in the box>

<"replaced: <old draft>" if this was a rewrite>
Target is <idle|busy>. Press Enter in that pane to send it.
```
