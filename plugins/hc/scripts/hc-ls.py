#!/usr/bin/env python3
"""List herdr-core terminals as a table (or --json). Deterministic half of /hc:ls.

    hc-ls.py [--json]

Status comes from the program itself (OSC 7501) via `hc ls --json`; nothing is
scraped off the screen. Exit 2: `hc` is missing or the core cannot be reached.
"""
import json
import os
import shutil
import subprocess
import sys


def main() -> int:
    if not shutil.which("hc"):
        sys.stderr.write("hc-ls: `hc` (herdr-core) is not on PATH.\n")
        return 2
    r = subprocess.run(["hc", "ls", "--json"], capture_output=True, text=True, timeout=20)
    if r.returncode != 0:
        sys.stderr.write(f"hc-ls: hc ls failed: {r.stderr.strip() or r.stdout.strip()}\n")
        return 2
    data = json.loads(r.stdout)
    me = os.environ.get("HC_TERMINAL_ID", "")
    rows = []
    for t in data.get("terminals", []):
        rows.append({
            "name": t.get("name") or "",
            "address": t.get("address", ""),
            "status": t.get("status") or "-",          # idle / working / blocked / done / error; "-" = plain program
            "program": t.get("agent") or "",
            "where": t.get("where") or t.get("cwd") or "",
            "self": t.get("address") == me,
        })
    if "--json" in sys.argv[1:]:
        print(json.dumps({"terminals": rows, "machines": data.get("machines", [])}, ensure_ascii=False))
        return 0
    if not rows:
        print("(no live terminals)")
    else:
        w_name = max(len(r["name"] or r["address"]) for r in rows)
        w_addr = max(len(r["address"]) for r in rows)
        for r in sorted(rows, key=lambda r: (r["where"], r["name"])):
            mark = "*" if r["self"] else " "
            print(f"{mark} {(r['name'] or r['address']):<{w_name}}  {r['address']:<{w_addr}}  {r['status']:<8}  {r['program']:<12}  {r['where']}")
    for m in data.get("machines", []):
        print(f"machine {m.get('name')}: {m.get('state')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
