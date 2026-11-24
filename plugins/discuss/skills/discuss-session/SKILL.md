---
name: discuss-session
description: Use after /discuss, when a message starts with "[porthole]", or when the user asks you to look at, review, or change a diagram in a file they have open in porthole — a ```mermaid / ```excalidraw / ```d2 block in a markdown file, or a .excalidraw file. Also "看一下我的圖", "幫我改圖", "my diagram", "the whiteboard", or "stop recording to porthole".
---

# discuss — one conversation, two windows

`/discuss` bound this session to a porthole conversation. The user may talk to
you here or in the browser; it is the same person and the same thread.

- **`[porthole] …`** is the user typing in the browser. Answer it like any other
  message. Your reply is recorded and shows up there by itself — do not repeat
  it, post it, or write to `doc/chat/` yourself.
- They cannot see your tool calls in the browser, only your text. Say what you
  changed and why.
- A permission prompt here blocks the browser too: porthole refuses to send
  until someone answers it in this terminal.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/discuss.py" status   # what this session is bound to
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/discuss.py" unbind   # stop recording
```

If `${CLAUDE_PLUGIN_ROOT}` comes through empty:
`ls -d ~/.claude/plugins/cache/*/discuss/*/scripts | tail -1`.

## The file

Edit the file in place — it is the one open in the browser. An idle preview
reloads by itself within seconds; an open editor shows a "changed elsewhere"
notice, and a stale save there is refused instead of overwriting you. Mention
that you changed it so they reload before editing on.

Re-read the file before editing it: the user may have saved from the browser.

## Diagrams

- **Mermaid / D2** are text: read and edit the lines between the fences, keep
  the fence line and the header line (`graph TD;`, `stateDiagram-v2`, …). The GUI
  editors understand a subset — keep to the style already there.
- **Excalidraw** is verbose JSON. To read it, get a summary (shapes, arrows as
  `from -> to`, free text):

  ```bash
  node "${CLAUDE_PLUGIN_ROOT}/scripts/diagram.mjs" summary <file> [--index N]
  ```

  To edit: change a text element's `text` *and* `originalText`; a new element is
  a sibling's full shape with a fresh `id`, fresh `seed`, `"version": 1`. Bound
  text needs `containerId` plus a `{"id", "type": "text"}` entry in the
  container's `boundElements`. Do not reformat the JSON.

When reviewing, name the nodes and connections you see first, so the user can
tell you read the right diagram.
