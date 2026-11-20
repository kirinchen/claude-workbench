#!/usr/bin/env python3
"""Narrow herdr-core terminals down to one, a menu level at a time. Deterministic half of
picking a terminal for /hc:send and /hc:review (Claude Code's option menu holds 4 choices).

    hc-pick.py [--for send|review] [--query Q] [--machine M] [--space S] [--page N]

Prints JSON, one of:
  {"pick": {...terminal}}                          exactly one left: use it
  {"ask": {"header", "question", "options": [...]}}  show these as a menu; each option has
        "label", "description" and "args": run this script again with those args when chosen
  {"none": "<why>"}                                nothing matches

Levels: machine (when the terminals span machines), then space, then terminal; a level is
skipped when everything left fits in one menu. More than 4 choices -> 3 + "More…".
--query: typed text ("Other" in the menu). An exact name or address picks it; otherwise it
filters by name / address / space / program, case-insensitive.
The terminal this session runs in ($HC_TERMINAL_ID) is left out. Exit 2: hc unreachable.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

LOCAL = "local"
# Most worth sending to first: finished turns nobody read, then free, then busy; plain programs last.
RANK = {"done": 0, "idle": 1, "working": 2, "blocked": 3, "error": 4, "-": 5}
SAY = {"done": "done (unread)", "idle": "idle", "working": "working", "blocked": "blocked", "error": "error", "-": "plain program"}


def terminals():
    if not shutil.which("hc"):
        sys.stderr.write("hc-pick: `hc` (herdr-core) is not on PATH.\n")
        sys.exit(2)
    r = subprocess.run(["hc", "ls", "--json"], capture_output=True, text=True, timeout=20)
    if r.returncode != 0:
        sys.stderr.write(f"hc-pick: hc ls failed: {r.stderr.strip() or r.stdout.strip()}\n")
        sys.exit(2)
    me = os.environ.get("HC_TERMINAL_ID", "")
    out = []
    for t in json.loads(r.stdout).get("terminals", []):
        addr = t.get("address", "")
        if not addr or addr == me:
            continue
        where = t.get("where") or ""
        out.append({
            "name": t.get("name") or "",
            "address": addr,
            "machine": addr.split("/")[0] if "/" in addr else LOCAL,
            "space": where.split(" / ")[0] if where else "(no space)",
            "where": where or t.get("cwd") or "",
            "status": t.get("status") or "-",
            "program": t.get("agent") or "",
        })
    return out


def page(items, n, header, question, make, nextargs):
    """At most 4 options: everything if it fits, else 3 from page n plus More…"""
    if len(items) <= 4:
        shown, more = items, False
    else:
        shown, more = items[n * 3:n * 3 + 3], n * 3 + 3 < len(items)
    opts = [make(i) for i in shown]
    if more:
        rest = len(items) - (n * 3 + 3)
        opts.append({"label": "More…", "description": f"{rest} more; or choose Other and type part of a name", "args": nextargs(n + 1)})
    return {"ask": {"header": header, "question": question, "options": opts}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--for", dest="purpose", default="send", choices=["send", "review"])
    ap.add_argument("--query", default="")
    ap.add_argument("--machine")
    ap.add_argument("--space")
    ap.add_argument("--page", type=int, default=0)
    a = ap.parse_args()

    ts = terminals()
    q = a.query.strip()
    if q:
        exact = [t for t in ts if q in (t["name"], t["address"])]
        if len(exact) == 1:
            return {"pick": exact[0]}
        ql = q.lower()
        ts = [t for t in ts if any(ql in t[k].lower() for k in ("name", "address", "where", "program"))]
    if a.machine:
        ts = [t for t in ts if t["machine"] == a.machine]
    if a.space:
        ts = [t for t in ts if t["space"] == a.space]
    if not ts:
        return {"none": f"no terminal matches {q!r}" if q else "no other live terminal"}
    if len(ts) == 1:
        return {"pick": ts[0]}

    base = {"--for": a.purpose, "--query": q or None, "--machine": a.machine, "--space": a.space}
    def args(**over):
        d = {**base, **over}
        return [x for k, v in d.items() if v not in (None, "", 0) for x in (k, str(v))]
    verb = "send to" if a.purpose == "send" else "review"
    scope = " ".join(x for x in (a.space and f"in {a.space}", a.machine and a.machine != LOCAL and f"on {a.machine}") if x)

    machines = sorted({t["machine"] for t in ts}, key=lambda m: (m != LOCAL, m))
    if not a.machine and len(machines) > 1 and len(ts) > 4:
        def make(m):
            mine = [t for t in ts if t["machine"] == m]
            return {"label": m, "description": f"{len(mine)} terminals, {sum(t['status'] == 'done' for t in mine)} unread", "args": args(**{"--machine": m, "--page": None})}
        return page(machines, a.page, "Machine", f"Which machine? (terminal to {verb})", make, lambda n: args(**{"--page": n}))

    spaces = {}
    for t in ts:
        spaces.setdefault(t["space"], []).append(t)
    if not a.space and len(spaces) > 1 and len(ts) > 4:
        order = sorted(spaces, key=lambda s: (min(RANK.get(t["status"], 5) for t in spaces[s]), s.lower()))
        def make(s):
            mine = spaces[s]
            names = ", ".join(t["name"] or t["address"] for t in mine[:3]) + ("…" if len(mine) > 3 else "")
            return {"label": s, "description": f"{len(mine)}: {names}", "args": args(**{"--space": s, "--page": None})}
        return page(order, a.page, "Space", f"Which space{(' ' + scope) if scope else ''}? (terminal to {verb})", make, lambda n: args(**{"--page": n}))

    order = sorted(ts, key=lambda t: (RANK.get(t["status"], 5), (t["name"] or t["address"]).lower()))
    def make(t):
        warn = " — send will refuse, a person must answer it" if a.purpose == "send" and t["status"] == "blocked" else ""
        return {"label": t["name"] or t["address"], "description": f"{t['address']} · {SAY.get(t['status'], t['status'])} · {t['where']}{warn}", "args": args(**{"--query": t["address"], "--machine": None, "--space": None, "--page": None})}
    return page(order, a.page, "Terminal", f"Which terminal{(' ' + scope) if scope else ''} do you want to {verb}?", make, lambda n: args(**{"--page": n}))


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False))
