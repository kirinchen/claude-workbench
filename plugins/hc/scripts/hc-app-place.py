#!/usr/bin/env python3
"""Put a herdr-core terminal into the Herdr App sidebar layout. Stdlib only.

    hc-app-place.py <terminal> [--dry-run]

Why: `hc run` creates a terminal in the core only. The Herdr App sidebar draws a
Space / Tab layout stored in the core document `herdr-app` (doc.get / doc.set);
a terminal that is not in that document does not show up in the App at all.

What it does: finds (or creates) the Space whose `folder` is the terminal's cwd
and appends one Tab holding that terminal. Idempotent: a terminal already placed
anywhere in the layout is left alone. Never removes or reorders anything.
doc.set is versioned; on a conflict (the App edited meanwhile) it re-reads and
retries. Exit 0 placed / already there, 2 no such terminal, 1 could not write.
"""
import json
import os
import secrets
import subprocess
import sys

DOC = "herdr-app"


def rpc(method, params):
    req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}) + "\n"
    out = subprocess.run(["hc", "connect"], input=req, capture_output=True, text=True, timeout=15).stdout
    res = json.loads(out.splitlines()[0])
    if "error" in res:
        raise RuntimeError(f"{method}: {res['error']}")
    return res["result"]


def placed(node, acc):
    if isinstance(node, dict):
        content = node.get("content")
        if isinstance(content, dict) and content.get("terminal"):
            acc.add(content["terminal"])
        for v in node.values():
            placed(v, acc)
    elif isinstance(node, list):
        for v in node:
            placed(v, acc)
    return acc


def place(spaces, address, name, cwd):
    """Return a new spaces list with the terminal added, or None if already placed."""
    if address in placed(spaces, set()):
        return None
    tab_id = "tb" + secrets.token_hex(16)
    tab = {"id": tab_id, "name": name, "root": {"id": tab_id, "type": "row", "children": [
        {"id": "pd" + secrets.token_hex(16), "type": "block", "content": {"terminal": address}}]}}
    out, hit = [], False
    for s in spaces:
        if not hit and s.get("folder") == cwd:
            s = {**s, "tabs": [*s.get("tabs", []), tab]}
            hit = True
        out.append(s)
    if not hit:
        out.append({"id": "sp" + secrets.token_hex(16), "name": os.path.basename(cwd) or cwd, "folder": cwd, "tabs": [tab]})
    return out


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv[1:]
    if len(args) != 1:
        sys.stderr.write(__doc__)
        return 64
    r = subprocess.run(["hc", "get", args[0], "--json"], capture_output=True, text=True, timeout=15)
    if r.returncode != 0:
        sys.stderr.write(f"hc-app-place: no such terminal: {args[0]}\n")
        return 2
    t = json.loads(r.stdout)
    address, name, cwd = t["address"], t.get("name") or t["address"], t.get("cwd") or ""
    err = None
    for _ in range(3):
        try:
            cur = rpc("doc.get", {"name": DOC})
            value = cur.get("value") or {}
            nxt = place(list(value.get("spaces", [])), address, name, cwd)
            if nxt is None:
                print(f"hc-app-place: {name} ({address}) already in the App layout")
                return 0
            if dry:
                print(f"hc-app-place: would add {name} ({address}) to space {os.path.basename(cwd) or cwd}")
                return 0
            rpc("doc.set", {"name": DOC, "value": {**value, "spaces": nxt}, "version": cur["version"]})
            print(f"hc-app-place: added {name} ({address}) to space {os.path.basename(cwd) or cwd}")
            return 0
        except Exception as e:  # version conflict or a busy core: re-read and retry
            err = e
    sys.stderr.write(f"hc-app-place: could not write the App layout: {err}\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
