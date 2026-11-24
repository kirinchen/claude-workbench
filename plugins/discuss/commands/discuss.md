---
description: Open a file in porthole's editor next to a conversation that is this same terminal session. Takes a file, or just what you want to discuss.
argument-hint: "[file and/or what to discuss; empty = a fresh markdown file]"
allowed-tools: Bash(python3:*), Glob, Grep
---

# /discuss

What the user typed after the command:

<arguments>
$ARGUMENTS
</arguments>

## 1. Read it as a file, a message, or both

| It is | File to open | Message? |
|---|---|---|
| empty | none (the script makes `doc/discuss/discuss-<time>.md`) | no |
| only a path or file name (`doc/foo.md`, `foo`, `the README`) | that file | no |
| a path plus more words (`doc/foo.md add a flow chart`) | that file | yes |
| words that clearly point at one existing file ("login spec 那份的流程") | that file — find it with Glob / Grep, a quick look only | yes |
| anything else (a topic, a question, a request) | a new `doc/discuss/<slug>.md`: 2–5 lowercase ASCII words joined by `-`, not taken yet | yes |

Judge by meaning, not by punctuation: a sentence containing `/` or `.` is still a
sentence. Never turn a sentence into a file name. If two existing files fit
equally well, start a new one and mention them in your answer. Ask nothing here.

## 2. Run

No message:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/discuss.py" open '<file, or empty>'
```

With a message, add `--ask`:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/discuss.py" open --ask '<file>'
```

`--ask` records what the user typed, word for word, as the first message of the
conversation; the script takes it from the transcript, so pass only the file.

Run it on its own, exactly in that form: nothing chained before or after it (a
longer command asks the user for permission).

It finds the running porthole, creates the markdown file if it is missing, picks
the file's conversation, binds it to **this** session, and prints one JSON line.

- **Non-zero exit** → relay the error text as it is (it says how to install,
  start, or point at porthole) and stop. Do not fall back to another editor.

## 3. Report, then answer

**First** print the `report` value as it is, all of its lines, before anything else.

- No message → stop there and let the user talk.
- With a message → carry on in the same turn and answer it, working in that file
  when it calls for a document or a diagram.
- `"asked": false` although you passed `--ask` → say that the first message was
  not recorded, and answer anyway.

From here on follow the `discuss-session` skill: messages starting with
`[porthole]` are the user, typing in the browser.
