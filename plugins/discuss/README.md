# discuss

*[繁體中文](./README_zhtw.md)*

Discuss a file **with** your agent, in the browser and in the terminal at once.
`/discuss` opens the file in [porthole](https://github.com/kirinchen/porthole) —
markdown editor, diagram GUIs (Mermaid, D2, Excalidraw) — next to a conversation
that is **this same Claude Code session**. Successor of `draw`.

## Install

```
/plugin marketplace add kirinchen/claude-workbench
/plugin install discuss@claude-workbench
```

Needs `python3`, and a **running porthole** on the same machine:

```bash
git clone https://github.com/kirinchen/porthole && cd porthole
cp .env.example .env      # PORTHOLE_BASE = the folder that holds your repos
npm install && npm run install:all && npm run prod
```

`/discuss` finds it through the address porthole writes to
`~/.local/state/porthole/server.json`, then `http://127.0.0.1:4321`. Set
`PORTHOLE_URL` to override. The folder you run it from must be under
`PORTHOLE_BASE`. (`node` is only used to summarise Excalidraw drawings.)

## Use

| Command | What it does |
|---|---|
| `/discuss` | New `doc/discuss/discuss-<time>.md`, opened in porthole. |
| `/discuss <file>` | Open that file (a missing `.md` is created) and its conversation. |
| `/discuss <what to discuss>` | Start `doc/discuss/<short-name>.md` (or open the existing file you are clearly talking about), record your words as the first message, and answer. |
| `/discuss <file> <what to discuss>` | Open that file, record the whole line as the first message, and answer. |

The agent reads what you typed and decides which of these it is.

## Who hears what

| You speak in | Terminal session is | What happens |
|---|---|---|
| the terminal | open | The turn is appended to `doc/chat/<thread>.md`; porthole shows it within seconds. |
| porthole | open, with [`hc`](https://herdr.dev/core/) | Typed into this terminal. Same agent, same memory; the reply shows up in both. |
| porthole | open, **no `hc`** | Refused: **one-way** (terminal → porthole). The page says so. |
| porthole | closed | `claude -p --resume <session>` — it remembers the conversation. porthole runs this one with `--dangerously-skip-permissions`, like all its conversations. |

- **Only one agent answers.** While the terminal session is open, porthole never
  starts a second one.
- **Permission prompts stay yours.** If the terminal is waiting on one, porthole
  refuses to send and says why; it never answers the prompt.
- **Saving cannot clobber.** If the agent changed the file while you were editing,
  porthole tells you, and a stale save is refused (409).

## How it works

```
/discuss ──> scripts/discuss.py open ──> ~/.local/state/porthole/bindings/<session>.json
                                          (thread ⇄ session ⇄ terminal)
hooks: UserPromptSubmit / Stop ──> append turns to doc/chat/<thread>.md ──> porthole polls
       SessionStart / SessionEnd ──> mark the binding open / closed
porthole send ──> reads the binding ──> hc send "[porthole] …"  |  claude -p --resume
```

- The binding is kept out of the repo on purpose: the thread file can be edited
  from porthole, so a target stored there could be redirected.
- Messages from porthole start with `[porthole] `; the hook skips them, so nothing
  is recorded twice.
- `python3 scripts/discuss.py unbind` (or ask the agent to "stop recording to
  porthole") ends it. `/clear` starts a new session, which is not bound.

Tests: `python3 -m unittest discover -s plugins/discuss/tests`.
