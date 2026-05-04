#!/usr/bin/env python3
"""Local-mode helper invoked by /kanban:init / next / done / block / status.

Mirrors the architecture used by jira_setup.py: every state-mutating slash
command in local mode calls this helper via Bash, which writes kanban.json
through `kanban_io.save()` (atomic os.replace) — that path is invisible to
the kanban-guard.sh PreToolUse hook, which only blocks Edit/Write tools.

Subcommands print one JSON object to stdout. Errors print JSON to stdout
with `ok: false` and exit non-zero.

  init --kanban-path P [--with-examples]
       -> {"ok": true, "kanban_path": ..., "schema_path": ..., "tasks": <count>}

  next --kanban-path P [--category C] [--priority P] [--task-id ID]
       -> {"ok": true, "claimed": {"id":..., "title":..., "priority":...}}
       -> {"ok": true, "claimed": null, "candidates": [...top 3...], "reason": "..."}
       -> {"ok": false, "error": "..."}

  done --kanban-path P [--task-id ID] [--note TEXT]
       -> {"ok": true, "id": ..., "unblocked": [...]}

  block --kanban-path P --task-id ID --reason TEXT
       -> {"ok": true, "id": ..., "downstream": [...]}

  status --kanban-path P
       -> {"ok": true, "counts": {...}, "doing": [...], "next": [...], "blocked": [...]}
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve()
PLUGIN_ROOT = HERE.parents[1]               # holds lib/, drivers/, templates/
TEMPLATES = PLUGIN_ROOT / "templates"
sys.path.insert(0, str(PLUGIN_ROOT))

from lib import kanban_io  # noqa: E402


LOCAL_COLUMNS = ("TODO", "DOING", "APPROVED", "BLOCKED")


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _emit(obj: dict[str, Any]) -> None:
    json.dump(obj, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


def _fail(msg: str, code: int = 1, **extra: Any) -> int:
    _emit({"ok": False, "error": msg, **extra})
    return code


def _load(p: Path) -> dict[str, Any]:
    return kanban_io.load(p)


def _save(p: Path, data: dict[str, Any]) -> None:
    data.setdefault("meta", {})["updated_at"] = _now_iso()
    kanban_io.save(p, data)


def _require_local(data: dict[str, Any]) -> str | None:
    backend = data.get("backend") or {}
    driver = backend.get("driver", "local")
    if driver != "local":
        return f"backend.driver must be 'local'; got {driver!r}"
    return None


def _find_task(data: dict[str, Any], task_id: str) -> dict[str, Any] | None:
    for t in data.get("tasks") or []:
        if t.get("id") == task_id:
            return t
    return None


def _next_task_id(tasks: list[dict[str, Any]]) -> str:
    nums = []
    for t in tasks:
        tid = t.get("id", "")
        if tid.startswith("task-"):
            try:
                nums.append(int(tid[5:]))
            except ValueError:
                pass
    n = (max(nums) + 1) if nums else 1
    return f"task-{n:03d}"


# --- subcommands ---------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> int:
    p = Path(args.kanban_path)
    if p.exists() and not args.force:
        return _fail(
            f"{p} already exists — pass --force to overwrite (this destroys existing tasks)"
        )

    src_name = "kanban.example.json" if args.with_examples else "kanban.empty.json"
    src = TEMPLATES / src_name
    schema_src = TEMPLATES / "kanban.schema.json"
    if not src.exists() or not schema_src.exists():
        return _fail(f"template not found in {TEMPLATES}")

    p.parent.mkdir(parents=True, exist_ok=True)
    schema_dst = p.parent / "kanban.schema.json"
    shutil.copy(schema_src, schema_dst)

    body = src.read_text(encoding="utf-8")
    ts = _now_iso()
    body = body.replace("__CREATED_AT__", ts).replace("__UPDATED_AT__", ts)
    p.write_text(body, encoding="utf-8")

    # Round-trip through kanban_io to enforce v0.2 normalised shape on disk.
    data = _load(p)
    kanban_io.save(p, data)

    _emit(
        {
            "ok": True,
            "kanban_path": str(p),
            "schema_path": str(schema_dst),
            "tasks": len(data.get("tasks") or []),
            "with_examples": bool(args.with_examples),
        }
    )
    return 0


def _candidate_tasks(
    data: dict[str, Any],
    category: str | None,
    priority: str | None,
) -> list[dict[str, Any]]:
    """TODO tasks whose deps are all APPROVED, after applying user filters."""
    tasks = data.get("tasks") or []
    done_ids = {t.get("id") for t in tasks if t.get("column") == "APPROVED"}
    priorities = (data.get("meta") or {}).get("priorities") or []
    cutoff = priorities.index(priority) if priority and priority in priorities else None

    out: list[dict[str, Any]] = []
    for t in tasks:
        if t.get("column") != "TODO":
            continue
        if category and t.get("category") != category:
            continue
        if cutoff is not None:
            tp = t.get("priority")
            if tp not in priorities or priorities.index(tp) > cutoff:
                continue
        deps = t.get("depends") or []
        if any(d not in done_ids for d in deps):
            continue
        out.append(t)

    def sort_key(t: dict[str, Any]):
        p = t.get("priority")
        idx = priorities.index(p) if p in priorities else len(priorities)
        return (idx, t.get("created") or "", t.get("id") or "")

    out.sort(key=sort_key)
    return out


def cmd_next(args: argparse.Namespace) -> int:
    p = Path(args.kanban_path)
    if not p.exists():
        return _fail(f"kanban.json not found at {p} — run /kanban:init first")
    data = _load(p)
    if (err := _require_local(data)):
        return _fail(err)

    if args.task_id:
        target = _find_task(data, args.task_id)
        if not target:
            return _fail(f"task {args.task_id!r} not found")
        if target.get("column") != "TODO":
            return _fail(
                f"task {args.task_id} is in {target.get('column')!r}, not TODO"
            )
        candidates = [target]
    else:
        candidates = _candidate_tasks(data, args.category, args.priority)
        if not candidates:
            tasks = data.get("tasks") or []
            todos = [t for t in tasks if t.get("column") == "TODO"]
            if not todos:
                reason = "no TODO tasks"
            elif args.category or args.priority:
                reason = "no TODO tasks match the given filters"
            else:
                reason = "all TODO tasks have unresolved dependencies"
            _emit({"ok": True, "claimed": None, "candidates": [], "reason": reason})
            return 0

    # Top-3 ambiguity: if the top two share the same priority, surface them
    # rather than guess. The slash command will ask the user.
    if not args.task_id and len(candidates) >= 2:
        priorities = (data.get("meta") or {}).get("priorities") or []
        top_p = candidates[0].get("priority")
        same_top = [c for c in candidates if c.get("priority") == top_p]
        if len(same_top) >= 2:
            _emit(
                {
                    "ok": True,
                    "claimed": None,
                    "candidates": [
                        {
                            "id": c.get("id"),
                            "title": c.get("title"),
                            "priority": c.get("priority"),
                            "category": c.get("category"),
                        }
                        for c in candidates[:3]
                    ],
                    "reason": "tie at top priority — pick one",
                }
            )
            return 0

    pick = candidates[0]
    ts = _now_iso()
    pick["column"] = "DOING"
    pick["started"] = pick.get("started") or ts
    pick["updated"] = ts
    pick.setdefault("assignee", "claude-code")
    if not pick.get("assignee"):
        pick["assignee"] = "claude-code"
    _save(p, data)

    _emit(
        {
            "ok": True,
            "claimed": {
                "id": pick["id"],
                "title": pick.get("title"),
                "priority": pick.get("priority"),
                "category": pick.get("category"),
                "deps": list(pick.get("depends") or []),
            },
        }
    )
    return 0


def cmd_done(args: argparse.Namespace) -> int:
    p = Path(args.kanban_path)
    if not p.exists():
        return _fail(f"kanban.json not found at {p}")
    data = _load(p)
    if (err := _require_local(data)):
        return _fail(err)

    tasks = data.get("tasks") or []

    if args.task_id:
        target = _find_task(data, args.task_id)
    else:
        doing = [
            t for t in tasks
            if t.get("column") == "DOING" and t.get("assignee") == "claude-code"
        ]
        if len(doing) == 0:
            return _fail("no DOING task assigned to claude-code; pass --task-id")
        if len(doing) > 1:
            return _fail(
                "multiple DOING tasks; pass --task-id",
                doing=[t.get("id") for t in doing],
            )
        target = doing[0]

    if not target:
        return _fail(f"task {args.task_id!r} not found")
    col = target.get("column")
    if col == "APPROVED":
        return _fail(f"{target['id']} is already APPROVED")
    if col != "DOING":
        return _fail(f"{target['id']} is in {col!r}, not DOING")

    ts = _now_iso()
    target["column"] = "APPROVED"
    target["completed"] = ts
    target["updated"] = ts
    if not target.get("started"):
        target["started"] = ts
    if args.note:
        target.setdefault("comments", []).append(
            {"author": "claude-code", "ts": ts, "text": args.note}
        )
    _save(p, data)

    # Compute newly unblocked tasks: TODO whose deps now all APPROVED.
    done_ids = {t.get("id") for t in data.get("tasks") or [] if t.get("column") == "APPROVED"}
    unblocked = []
    for t in data.get("tasks") or []:
        if t.get("column") != "TODO":
            continue
        deps = t.get("depends") or []
        if not deps or target["id"] not in deps:
            continue
        if all(d in done_ids for d in deps):
            unblocked.append({"id": t.get("id"), "title": t.get("title")})

    _emit(
        {
            "ok": True,
            "id": target["id"],
            "title": target.get("title"),
            "completed": ts,
            "unblocked": unblocked,
        }
    )
    return 0


def cmd_block(args: argparse.Namespace) -> int:
    p = Path(args.kanban_path)
    if not p.exists():
        return _fail(f"kanban.json not found at {p}")
    if not args.reason or not args.reason.strip():
        return _fail("--reason is required and must be non-empty")
    data = _load(p)
    if (err := _require_local(data)):
        return _fail(err)
    target = _find_task(data, args.task_id)
    if not target:
        return _fail(f"task {args.task_id!r} not found")
    col = target.get("column")
    if col == "BLOCKED":
        return _fail(f"{target['id']} is already BLOCKED")
    if col == "APPROVED":
        return _fail(f"{target['id']} is APPROVED — terminal, cannot be blocked")
    if col not in {"TODO", "DOING"}:
        return _fail(f"unexpected column {col!r}")

    ts = _now_iso()
    target["column"] = "BLOCKED"
    target["updated"] = ts
    target.setdefault("custom", {})["blocked_reason"] = args.reason
    target.setdefault("comments", []).append(
        {"author": "claude-code", "ts": ts, "text": f"Blocked: {args.reason}"}
    )
    _save(p, data)

    downstream = [
        {"id": t.get("id"), "title": t.get("title")}
        for t in (data.get("tasks") or [])
        if args.task_id in (t.get("depends") or [])
    ]
    _emit(
        {
            "ok": True,
            "id": target["id"],
            "title": target.get("title"),
            "reason": args.reason,
            "downstream": downstream,
        }
    )
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    p = Path(args.kanban_path)
    if not p.exists():
        return _fail(f"kanban.json not found at {p}")
    data = _load(p)
    if (err := _require_local(data)):
        return _fail(err)

    tasks = data.get("tasks") or []
    counts: dict[str, int] = {c: 0 for c in LOCAL_COLUMNS}
    for t in tasks:
        c = t.get("column")
        if c in counts:
            counts[c] += 1

    doing = [
        {
            "id": t.get("id"),
            "title": t.get("title"),
            "priority": t.get("priority"),
            "started": t.get("started"),
            "assignee": t.get("assignee"),
        }
        for t in tasks
        if t.get("column") == "DOING"
    ]
    blocked = [
        {
            "id": t.get("id"),
            "title": t.get("title"),
            "priority": t.get("priority"),
            "reason": (t.get("custom") or {}).get("blocked_reason"),
        }
        for t in tasks
        if t.get("column") == "BLOCKED"
    ]
    next_up = _candidate_tasks(data, None, None)[:3]
    next_summary = [
        {
            "id": t.get("id"),
            "title": t.get("title"),
            "priority": t.get("priority"),
            "category": t.get("category"),
        }
        for t in next_up
    ]

    _emit(
        {
            "ok": True,
            "counts": counts,
            "doing": doing,
            "blocked": blocked,
            "next": next_summary,
            "version": data.get("version") or "0.2",
        }
    )
    return 0


# --- entry point ---------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kanban_local")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init")
    s.add_argument("--kanban-path", required=True)
    s.add_argument("--with-examples", action="store_true")
    s.add_argument("--force", action="store_true",
                   help="overwrite an existing kanban.json (destructive)")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("next")
    s.add_argument("--kanban-path", required=True)
    s.add_argument("--category")
    s.add_argument("--priority")
    s.add_argument("--task-id",
                   help="claim a specific TODO task instead of auto-picking")
    s.set_defaults(func=cmd_next)

    s = sub.add_parser("done")
    s.add_argument("--kanban-path", required=True)
    s.add_argument("--task-id")
    s.add_argument("--note")
    s.set_defaults(func=cmd_done)

    s = sub.add_parser("block")
    s.add_argument("--kanban-path", required=True)
    s.add_argument("--task-id", required=True)
    s.add_argument("--reason", required=True)
    s.set_defaults(func=cmd_block)

    s = sub.add_parser("status")
    s.add_argument("--kanban-path", required=True)
    s.set_defaults(func=cmd_status)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
