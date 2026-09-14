---
description: Compose a message into another tmux session's input box and send it, then confirm it landed or queued.
argument-hint: <session> <what to say>
allowed-tools: Bash(bash:*), Bash(python3:*)
---

# /tmux:send

Arguments: `$ARGUMENTS`

- `$1` — the session name (exact; get it from `/tmux:ls`).
- Everything after it — the description of what to say. Required.

Same composition as `/tmux:draft`, but Enter is pressed. This writes into
someone else's working session — compose deliberately.

## 1. Read the current box

```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/tmux-input.sh "$1" --get
```

Exit 2 → no such session; relay the printed list and stop.

- `ui: "dialog"` → **stop**. A selector is open; Enter would answer *it*, not
  send a message. Tell the user to deal with the dialog first.
- `has_draft: true` → someone left unsent text in that box. **Do not silently
  destroy it.** Show the existing draft and ask whether to fold it into the new
  message or replace it, unless the user's description already makes the intent
  obvious (e.g. "改寫成…", "replace it with…").
- `has_draft: false` with a non-empty `ghost` → nothing is in the box. The
  faint text is a placeholder for abandoned input; there is nothing to
  preserve and nothing to ask about. Proceed.
- `status: "busy"` / `"busy+queued"` → the send will be queued, not acted on.
  Say so up front; it changes what the user should expect.

## 2. Compose

One line, in the user's language. No newlines (a literal newline submits
early — the script rejects them).

## 3. Send

```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/tmux-input.sh "$1" --send "<composed text>"
```

The script clears the box, types the text with `send-keys -l`, pauses, then
sends `Enter` as a **separate** key — bundling them drops characters. It then
waits and re-reads the pane, printing the post-send state.

## 4. Confirm it landed — do not skip this

```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/tmux-capture.sh "$1" -S 30
```

Decide which of these actually happened and report the right one:

| Evidence on screen | Report |
|---|---|
| Message echoed in the transcript, `status: busy` | Delivered; the target is working on it. |
| `status: busy+queued`, box shows the queue placeholder | **Queued** behind what it is already doing. It will be picked up when the current turn ends. |
| Box is empty and the message is nowhere on screen | Ambiguous — say so. Do not claim success. |
| Box still holds the text | Enter did not take. Report the failure; do not press Enter again on your own. |

## 5. Report

```
<session> — <delivered | queued | failed>

  sent: <the exact text>

<one line of evidence: the transcript line or the queue placeholder you saw>
```
