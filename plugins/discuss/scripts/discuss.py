#!/usr/bin/env python3
"""discuss — bind this Claude Code session to a porthole conversation.

  discuss.py open [--ask] [file]
                           create / find the file and its thread, bind, print JSON;
                           --ask logs what came after /discuss as the first message
  discuss.py open --thread <name>
                           bind to the existing doc/chat/<name>.md as it is (no new
                           thread, no renaming) — how porthole hands a conversation
                           to a terminal it started
  discuss.py status        what this session is bound to (JSON)
  discuss.py unbind        stop recording this session into the thread
  discuss.py hook          hook entry (UserPromptSubmit / Stop / SessionStart / SessionEnd)

Contract with porthole (its doc/SPEC.md §4.2.3):
  ${XDG_STATE_HOME:-~/.local/state}/porthole/bindings/<session_id>.json
One file per session. Only this script creates bindings; porthole reads them to
decide where a message typed in the browser goes. They are deliberately not kept
in the thread file: that file is editable from porthole.

The hook is silent and always exits 0 — anything it printed on UserPromptSubmit /
SessionStart would be injected into the model's context.
Standard library only.
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

RELAY_MARK = "[porthole]"
DEFAULT_URL = "http://127.0.0.1:4321"
SESSION_RE = re.compile(r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$", re.I)
TERMINAL_RE = re.compile(r"^t[0-9a-z]{1,8}$")
_COMMAND = re.compile(r"<command-name>/(?:discuss:)?discuss</command-name>")
_COMMAND_ARGS = re.compile(r"<command-args>(.*)</command-args>", re.DOTALL)
_SYS_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)
THREAD_RE = re.compile(r"^[A-Za-z0-9_-]+$")
LINK_RE = re.compile(r"<!--\s*porthole:link\s+(\S[^>]*?)\s*-->")  # porthole's chat-link.ts
# What may wrap text typed in by `hc send`: Claude Code's paste tag, hc's sender tag.
_WRAP_OPEN = re.compile(r"^(?:\s*<(?:pasted_content|hc)\b[^>]*>\s*)+")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# ---------------------------------------------------------------- state files

def state_dir() -> str:
    if os.environ.get("PORTHOLE_STATE_DIR"):
        return os.environ["PORTHOLE_STATE_DIR"]
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(base, "porthole")


def binding_path(session_id: str) -> str:
    return os.path.join(state_dir(), "bindings", f"{session_id}.json")


def load_json(path: str):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def save_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def patch_binding(session_id: str, **fields) -> None:
    """Re-read, change only our own fields, write — porthole may rename `thread`."""
    path = binding_path(session_id)
    cur = load_json(path)
    if cur is None:
        return  # unbound meanwhile
    cur.update(fields)
    save_json(path, cur)


# ---------------------------------------------------------- process / terminal

def _proc(pid: int):
    """(ppid, argv) of a process, or None."""
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8", errors="replace") as fh:
            ppid = int(fh.read().rpartition(")")[2].split()[1])
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            argv = [a.decode("utf-8", "replace") for a in fh.read().split(b"\0")]
        return ppid, argv
    except OSError:
        pass
    try:
        out = subprocess.run(
            ["ps", "-o", "ppid=,command=", "-p", str(pid)], capture_output=True, text=True, timeout=3
        ).stdout.strip()
        head, _, cmd = out.partition(" ")
        return int(head), cmd.split()
    except Exception:
        return None


def claude_pid():
    """The claude process this script runs under, or None."""
    pid = os.getppid()
    for _ in range(12):
        info = _proc(pid)
        if not info or pid <= 1:
            return None
        ppid, argv = info
        name = os.path.basename(argv[0]) if argv and argv[0] else ""
        if name in ("claude", "claude.exe") or (
            name.startswith("node") and len(argv) > 1 and "claude" in argv[1]
        ):
            return pid
        pid = ppid
    return None


def hc_terminal():
    """This machine's herdr-core terminal address, or None (no hc here)."""
    t = os.environ.get("HC_TERMINAL_ID", "")
    return t if TERMINAL_RE.match(t) and shutil.which("hc") else None


# -------------------------------------------------------------------- porthole

class Fail(Exception):
    pass


def http_json(url: str, timeout: float = 6):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def find_porthole():
    """(url, base) of a running porthole, or raise Fail with how to fix it."""
    env = (os.environ.get("PORTHOLE_URL") or "").strip()
    cands = [env] if env else []
    if not env:
        srv = load_json(os.path.join(state_dir(), "server.json"))
        if srv and isinstance(srv.get("url"), str):
            cands.append(srv["url"])
        cands.append(DEFAULT_URL)
    for url in dict.fromkeys(c.rstrip("/") for c in cands):
        try:
            d = http_json(f"{url}/api/repos")
            if isinstance(d, dict) and d.get("base"):
                return url, os.path.realpath(d["base"])
        except Exception:
            continue
    raise Fail(
        "porthole is not reachable (tried: " + ", ".join(dict.fromkeys(cands)) + ").\n"
        "/discuss runs on porthole — install and start it first:\n"
        "  git clone https://github.com/kirinchen/porthole && cd porthole\n"
        "  cp .env.example .env      # set PORTHOLE_BASE to the folder that holds your repos\n"
        "  npm install && npm run install:all && npm run prod\n"
        "If it is running somewhere else, set PORTHOLE_URL (e.g. in the `env` block of ~/.claude/settings.json)."
    )


def locate_repo(base: str, cwd: str):
    """cwd → (repo name, repo root). porthole's repo = first folder under its base."""
    real = os.path.realpath(cwd)
    rel = os.path.relpath(real, base)
    if rel == "." or rel == ".." or rel.startswith(".." + os.sep) or os.path.isabs(rel):
        raise Fail(
            f"this folder is not inside porthole's base, so porthole cannot show it.\n"
            f"  folder: {real}\n  base:   {base}\n"
            "Run /discuss from a repo under that base, or restart porthole with PORTHOLE_BASE set to a parent of this folder."
        )
    repo = rel.split(os.sep)[0]
    return repo, os.path.join(base, repo)


def resolve_file(root: str, cwd: str, arg: str):
    """→ (repo-relative posix path, absolute path, created). Creates a missing .md."""
    if not arg:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = os.path.join(root, "doc", "discuss", f"discuss-{stamp}.md")
    else:
        target = os.path.join(cwd, os.path.expanduser(arg))
    target = os.path.realpath(target)
    rel = os.path.relpath(target, root)
    if rel.startswith("..") or os.path.isabs(rel):
        raise Fail(f"{target} is outside this repo ({root}).")
    if rel.split(os.sep)[0] == ".git":
        raise Fail("refusing to open a file inside .git.")
    if os.path.isdir(target):
        raise Fail(f"{target} is a directory — give a file.")
    created = False
    if not os.path.exists(target):
        stem, ext = os.path.splitext(target)
        if not ext:
            target, rel = target + ".md", rel + ".md"
            ext = ".md"
        if not os.path.exists(target):
            if ext.lower() not in (".md", ".markdown"):
                raise Fail(f"{target} does not exist. /discuss only creates markdown files.")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "x", encoding="utf-8") as fh:
                fh.write(f"# {os.path.basename(stem)}\n")
            created = True
    return rel.replace(os.sep, "/"), target, created


# ------------------------------------------------------------------ transcript

def transcript_of(session_id: str):
    cfg = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    hits = glob.glob(os.path.join(glob.escape(cfg), "projects", "*", f"{session_id}.jsonl"))
    return hits[0] if hits else None


def read_transcript(path: str) -> list:
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.endswith("\n"):
                break  # half-written last line: next time
            try:
                rec = json.loads(line)
            except Exception:
                rec = {}
            out.append(rec if isinstance(rec, dict) else {})
    return out


def asked(records: list):
    """(text, timestamp) typed after the /discuss being run now, else None.

    Read from the transcript so the words reach the thread exactly as typed and
    never pass through a shell. A later ordinary message means that /discuss is
    an old one, so it stops there.
    """
    for rec in reversed(records):
        turn = turn_of(rec)
        if turn and turn[0] == "human":
            return None
        if rec.get("type") != "user" or rec.get("isSidechain") or rec.get("isMeta"):
            continue
        content = (rec.get("message") or {}).get("content")
        if isinstance(content, list):
            content = "\n".join(
                b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
            )
        if not isinstance(content, str) or "<command-name>" not in content:
            continue
        m = _COMMAND_ARGS.search(content) if _COMMAND.search(content) else None
        text = m.group(1).strip() if m else ""
        return (text, rec.get("timestamp") or "") if text else None
    return None


def is_relay(text: str) -> bool:
    """Typed into this terminal by porthole, which already logged it."""
    return _WRAP_OPEN.sub("", text, count=1).lstrip().startswith(RELAY_MARK)


def human_text(text: str):
    text = _SYS_REMINDER.sub("", text).strip()
    if not text or "<command-name>" in text or "<command-message>" in text:
        return None
    if text.startswith(("<local-command-", "<bash-", "<task-notification", "[Request interrupted")):
        return None
    return text


def turn_of(rec: dict):
    """(speaker, text, timestamp) for a conversational record, else None."""
    if rec.get("isSidechain") or rec.get("isMeta"):
        return None
    ts = rec.get("timestamp") or ""
    kind = rec.get("type")
    if kind == "attachment":  # typed while the agent was working
        att = rec.get("attachment") or {}
        if att.get("type") != "queued_command" or att.get("commandMode", "prompt") != "prompt":
            return None
        p = att.get("prompt")
        if isinstance(p, list):
            p = "\n".join(b.get("text", "") for b in p if isinstance(b, dict) and b.get("type") == "text")
        text = human_text(p) if isinstance(p, str) else None
        return ("human", text, ts) if text else None
    content = (rec.get("message") or {}).get("content")
    if kind == "user":
        if isinstance(content, list):  # images + text; tool results carry no text block
            if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                return None
            content = "\n".join(
                b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
            )
        text = human_text(content) if isinstance(content, str) else None
        return ("human", text, ts) if text else None
    if kind == "assistant" and isinstance(content, list):
        text = "".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        ).strip()
        return ("assistant", text, ts) if text else None
    return None


def render(records: list, pending: list):
    """New transcript records → markdown, plus the pending prompts still unseen.

    Skips what porthole relayed and what UserPromptSubmit already logged.
    Consecutive assistant texts become one turn, dated by the last one.
    """
    pending = list(pending)
    merged: list = []
    for rec in records:
        turn = turn_of(rec)
        if not turn:
            continue
        who, text, ts = turn
        if who == "human":
            if text in pending:
                pending.remove(text)
                logged = True
            else:
                logged = is_relay(text)
            if logged:
                merged.append(None)  # still a boundary: don't glue the two answers together
                continue
        if merged and merged[-1] and merged[-1][0] == who == "assistant":
            merged[-1][1] += "\n\n" + text
            merged[-1][2] = ts or merged[-1][2]
        else:
            merged.append([who, text, ts])
    return "".join(format_turn(*t) for t in merged if t), pending


def format_turn(who: str, text: str, ts: str) -> str:
    label = "\U0001f9d1 Human" if who == "human" else "\U0001f916 Assistant"
    return f"\n## {label} · {ts or now_iso()}\n\n{text}\n"


# ------------------------------------------------------------------ thread file

def thread_head(title: str, link) -> str:
    return f"# {title}\n" + (f"<!-- porthole:link {link} -->\n" if link else "")


def read_link(path: str):
    """The file a thread is about, from its `<!-- porthole:link … -->` head, else None."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        m = LINK_RE.search(fh.read(4096))
    return m.group(1).strip() if m else None


def thread_file(b: dict):
    root, thread = b.get("root"), b.get("thread")
    if not isinstance(root, str) or not isinstance(thread, str) or not THREAD_RE.match(thread):
        return None
    return os.path.join(root, "doc", "chat", f"{thread}.md")


def append_thread(session_id: str, block: str) -> bool:
    """Append to the bound thread. porthole may be renaming it right now → retry once."""
    for attempt in (0, 1):
        b = load_json(binding_path(session_id))
        path = thread_file(b) if b else None
        if not path:
            return False
        if os.path.exists(path) or attempt:
            break
        time.sleep(0.4)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        block = thread_head(os.path.basename(b.get("link") or b["thread"]), b.get("link")) + block
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(block)
    return True


# ------------------------------------------------------------------------ hooks

def relay_run() -> bool:
    """porthole itself is running this session (`claude -p --resume`) and logs both sides."""
    return os.environ.get("PORTHOLE_RELAY") == "1"


def on_prompt(sid: str, b: dict, payload: dict) -> None:
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or relay_run():
        return
    text = human_text(prompt)
    if not text or text.startswith("/") or is_relay(text):
        return
    if append_thread(sid, format_turn("human", text, now_iso())):
        patch_binding(sid, pending=(b.get("pending") or [])[-20:] + [text])


def on_stop(sid: str, b: dict, payload: dict) -> None:
    path = payload.get("transcript_path")
    if not path or not os.path.exists(path):
        return
    last = payload.get("last_assistant_message")
    last = last.strip() if isinstance(last, str) else ""
    cursor = b.get("cursor")
    records = read_transcript(path)
    # The final message may reach the transcript a moment after Stop fires.
    for _ in range(15):
        fresh = records[cursor:] if isinstance(cursor, int) else records[-40:]
        if not last or any((t := turn_of(r)) and t[0] == "assistant" and last in t[1] for r in fresh):
            break
        time.sleep(0.2)
        records = read_transcript(path)
    total = len(records)
    if relay_run() or not isinstance(cursor, int) or cursor > total:
        patch_binding(sid, cursor=total, pending=[])
        return
    block, pending = render(records[cursor:], b.get("pending") or [])
    if block and not append_thread(sid, block):
        return
    patch_binding(sid, cursor=total, pending=pending)


def on_start(sid: str, b: dict, payload: dict) -> None:
    if relay_run():
        return
    fields = {"ended_at": None, "terminal": hc_terminal(), "pid": claude_pid()}
    path = payload.get("transcript_path")
    if b.get("ended_at") and path and os.path.exists(path):
        # Everything up to SessionEnd is logged, and whatever porthole ran after it
        # (`--resume`, possibly without this plugin loaded) porthole logged itself.
        fields.update(cursor=len(read_transcript(path)), pending=[])
    patch_binding(sid, **fields)


def on_end(sid: str) -> None:
    if not relay_run():
        patch_binding(sid, ended_at=now_iso())


def hook() -> None:
    payload = json.load(sys.stdin)
    sid = payload.get("session_id") or ""
    if not SESSION_RE.match(sid):
        return
    b = load_json(binding_path(sid))
    if b is None:
        return
    event = payload.get("hook_event_name")
    if event == "UserPromptSubmit":
        on_prompt(sid, b, payload)
    elif event == "Stop":
        on_stop(sid, b, payload)
    elif event == "SessionStart":
        on_start(sid, b, payload)
    elif event == "SessionEnd":
        on_stop(sid, b, payload)  # a turn cut off by Esc / exit never fired Stop
        on_end(sid)


# --------------------------------------------------------------------- commands

def my_session() -> str:
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if not SESSION_RE.match(sid):
        raise Fail("CLAUDE_CODE_SESSION_ID is not set — run this from inside Claude Code.")
    return sid


def pid_alive(pid) -> bool:
    if not isinstance(pid, int):
        return True  # unknown → assume it is still open
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def taken_by_other(sid: str, repo: str, thread: str) -> bool:
    for path in glob.glob(os.path.join(glob.escape(os.path.join(state_dir(), "bindings")), "*.json")):
        o = load_json(path)
        if not o or o.get("session_id") == sid or o.get("ended_at"):
            continue
        if o.get("repo") == repo and o.get("thread") == thread and pid_alive(o.get("pid")):
            return True
    return False


def report(url: str, rel: str, created: bool, continued: bool, two_way: bool) -> str:
    """What the user is told, word for word — so the agent does not have to phrase it."""
    note = " (new file)" if created else " (continuing an earlier conversation)" if continued else ""
    mode = (
        "Whatever you say here or in porthole is the same conversation."
        if two_way
        else "One-way: what you say here shows up in porthole, but porthole cannot send to this terminal "
        "(no hc / herdr-core here). After you close this session you can continue it from porthole."
    )
    return f"discuss → {url}\n{rel}{note}\n{mode}"


def bind(sid: str, repo: str, root: str, thread: str, link, cwd: str) -> list:
    """Write this session's binding; → the transcript so far (logging starts after it)."""
    transcript = transcript_of(sid)
    records = read_transcript(transcript) if transcript else []
    save_json(
        binding_path(sid),
        {
            "v": 1,
            "session_id": sid,
            "repo": repo,
            "root": root,
            "thread": thread,
            "link": link,
            "cwd": cwd,
            "terminal": hc_terminal(),
            "pid": claude_pid(),
            "created_at": now_iso(),
            "ended_at": None,
            "cursor": len(records) if transcript else None,
            "pending": [],
        },
    )
    return records


def web_link(url: str, repo: str, rel, thread: str) -> str:
    t = urllib.parse.quote(thread)
    if not rel:
        return f"{url}/{urllib.parse.quote(repo)}?thread={t}#chat"
    path = "/".join(urllib.parse.quote(p) for p in [repo, *rel.split("/")])
    return f"{url}/{path}?thread={t}#file"


def cmd_thread(name: str) -> dict:
    """Bind to an existing thread exactly as named. Never creates or renames one."""
    sid = my_session()
    if not THREAD_RE.match(name):
        raise Fail(f"--thread wants a thread name (letters, digits, - and _), got {name!r}.")
    cwd = os.path.realpath(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    url, base = find_porthole()
    repo, root = locate_repo(base, cwd)
    rel_thread = f"doc/chat/{name}.md"
    tpath = os.path.join(root, "doc", "chat", f"{name}.md")
    if not os.path.isfile(tpath):
        raise Fail(f"there is no conversation {rel_thread} in {repo} — nothing to bind to (no new one was started).")
    if taken_by_other(sid, repo, name):
        raise Fail(f"{rel_thread} is already bound to another open terminal session — not binding it twice.")
    link = read_link(tpath)
    bind(sid, repo, root, name, link, cwd)
    terminal = hc_terminal()
    web = web_link(url, repo, link, name)
    return {
        "report": report(web, rel_thread + (f" (about {link})" if link else ""), False, True, bool(terminal)),
        "url": web,
        "file": link,
        "created": False,
        "thread": rel_thread,
        "continued": True,
        "terminal": terminal,
        "mode": "two-way" if terminal else "one-way",
        "asked": False,
        "read_first": rel_thread,
    }


def cmd_open(arg: str, ask: bool = False) -> dict:
    sid = my_session()
    cwd = os.path.realpath(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    here = os.getcwd()
    url, base = find_porthole()
    repo, root = locate_repo(base, cwd)
    rel, _abs, created = resolve_file(root, here, arg)

    q = urllib.parse.urlencode({"path": rel})
    api = f"{url}/api/{urllib.parse.quote(repo)}/chat/for-file?{q}"
    thread = http_json(api)["name"]
    if taken_by_other(sid, repo, thread):
        thread = http_json(api + "&new=1")["name"]

    tpath = os.path.join(root, "doc", "chat", f"{thread}.md")
    existed = os.path.exists(tpath)
    if not existed:
        os.makedirs(os.path.dirname(tpath), exist_ok=True)
        with open(tpath, "x", encoding="utf-8") as fh:
            fh.write(thread_head(os.path.basename(rel), rel))

    records = bind(sid, repo, root, thread, rel, cwd)
    terminal = hc_terminal()
    first = asked(records) if ask else None
    if first:
        append_thread(sid, format_turn("human", *first))
    link = web_link(url, repo, rel, thread)
    return {
        "report": report(link, rel, created, existed, bool(terminal)),
        "url": link,
        "file": rel,
        "created": created,
        "thread": f"doc/chat/{thread}.md",
        "continued": existed,
        "terminal": terminal,
        "mode": "two-way" if terminal else "one-way",
        "asked": bool(first),
    }


def cmd_status() -> dict:
    b = load_json(binding_path(my_session()))
    if not b:
        return {"bound": False}
    return {"bound": True, **{k: b.get(k) for k in ("repo", "thread", "link", "terminal", "created_at")}}


def cmd_unbind() -> dict:
    path = binding_path(my_session())
    try:
        os.remove(path)
        return {"unbound": True}
    except FileNotFoundError:
        return {"unbound": False, "reason": "this session is not bound"}


def main(argv: list) -> int:
    cmd = argv[0] if argv else ""
    if cmd == "hook":
        try:
            hook()
        except Exception:
            pass  # a logging hook must never break the agent
        return 0
    try:
        if cmd == "open":
            rest = argv[1:]
            if rest[:1] == ["--thread"]:
                if len(rest) != 2:
                    raise Fail("usage: discuss.py open --thread <name>")
                res = cmd_thread(rest[1])
            else:
                ask = rest[:1] == ["--ask"]
                res = cmd_open(" ".join(rest[ask:]).strip(), ask)
        elif cmd == "status":
            res = cmd_status()
        elif cmd == "unbind":
            res = cmd_unbind()
        else:
            print(__doc__, file=sys.stderr)
            return 2
    except Fail as e:
        print(str(e), file=sys.stderr)
        return 1
    except (urllib.error.URLError, OSError) as e:
        print(f"discuss: {e}", file=sys.stderr)
        return 1
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
