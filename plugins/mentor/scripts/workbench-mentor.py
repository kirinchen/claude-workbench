#!/usr/bin/env python3
"""workbench-mentor — public CLI for the mentor plugin.

Subcommands:
  config         Print resolved .claude/mentor.yaml (JSON or text).
  active-sprint  Path + frontmatter of the first Sprint/*.md with status=active.
  trace <task>   task → issue → epic lookup chain.
  review         Compliance check; exit 2 if violations found.
  upgrade        Diff scaffold rules vs repo; --apply fills missing files.
  new <type>     Placeholder — real implementation delegated to /mentor:new slash command.
  --health       Exit 0 iff mentor is configured and loadable.

All subcommands support ``--format {json,text}``. Read-only by default;
``upgrade --apply`` is the only path that writes to the repo, and it
never overwrites existing files.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from framework_engine import (  # noqa: E402
    MentorConfig,
    active_sprint,
    config_to_dict,
    kanban_installed,
    load_config,
    load_yaml,
    read_frontmatter,
    review,
    trace_task,
)


def _fail(msg, code=1):
    print(msg, file=sys.stderr)
    return code


# -----------------------------------------------------------------------------
# Subcommands
# -----------------------------------------------------------------------------

def cmd_health(_args):
    cfg, path = load_config()
    if cfg is None or path is None:
        return _fail("mentor: no .claude/mentor.yaml found")
    if cfg.mode not in ("basic", "development"):
        return _fail(f"mentor: invalid mode {cfg.mode!r}; run /mentor:init --reset")
    print(f"mentor: ok ({path}, mode={cfg.mode})")
    return 0


def cmd_config(args):
    cfg, path = load_config()
    if cfg is None or path is None:
        return _fail("mentor: no config found")
    if args.format == "json":
        out = {"config_path": str(path), **config_to_dict(cfg)}
        print(json.dumps(out, indent=2))
    else:
        print(f"mentor config: {path}")
        print(f"  mode: {cfg.mode}")
        print(f"  paths.spec: {cfg.paths.spec}")
        if cfg.mode == "development":
            print(f"  paths.epic: {cfg.paths.epic}")
            print(f"  paths.sprint: {cfg.paths.sprint}")
            print(f"  paths.issue: {cfg.paths.issue}")
            print(f"  paths.wiki: {cfg.paths.wiki}")
        print(f"  bootstrap_docs: {cfg.agent_behavior.bootstrap_docs}")
        print(f"  integration.kanban.enabled: {cfg.integration.kanban_enabled}")
        print(f"  integration.memory.enabled: {cfg.integration.memory_enabled}")
        print(f"  integration.notify.enabled: {cfg.integration.notify_enabled}")
    return 0


def cmd_active_sprint(args):
    cfg, path = load_config()
    if cfg is None or path is None:
        return _fail("mentor: no config found")
    if cfg.mode != "development":
        msg = {"error": "active-sprint only meaningful in development mode",
               "mode": cfg.mode}
        print(json.dumps(msg) if args.format == "json" else msg["error"])
        return 1
    proj = path.parent.parent
    sp = active_sprint(proj, cfg)
    if sp is None:
        if args.format == "json":
            print(json.dumps({"active_sprint": None}))
        else:
            print("No active sprint.")
        return 0
    fm = read_frontmatter(sp) or {}
    if args.format == "json":
        print(json.dumps({
            "active_sprint": {
                "path": str(sp.relative_to(proj)),
                "frontmatter": fm,
            }
        }))
    else:
        print(f"Active sprint: {sp.relative_to(proj)}")
        for k in ("id", "goal", "start", "end", "status"):
            if k in fm:
                print(f"  {k}: {fm[k]}")
    return 0


def cmd_trace(args):
    cfg, path = load_config()
    if cfg is None or path is None:
        return _fail("mentor: no config found")
    if cfg.mode != "development":
        if args.format == "json":
            print(json.dumps({"mode": cfg.mode, "trace": None,
                              "note": "trace only meaningful in development mode"}))
        else:
            print(f"Mode is `{cfg.mode}`; task→issue→epic tracing needs development mode.")
        return 1
    proj = path.parent.parent
    r = trace_task(proj, cfg, args.task)
    if args.format == "json":
        print(json.dumps({
            "task_id": r.task_id,
            "issue": None if r.issue_path is None else {
                "id": r.issue_id,
                "path": str(r.issue_path.relative_to(proj)),
                "status": r.issue_fm.get("status"),
                "title": r.issue_fm.get("title"),
            },
            "epic": None if r.epic_path is None else {
                "id": r.epic_id,
                "path": str(r.epic_path.relative_to(proj)),
                "status": r.epic_fm.get("status"),
                "title": r.epic_fm.get("title"),
            },
            "sprint": None if r.sprint_path is None else {
                "id": r.sprint_id,
                "path": str(r.sprint_path.relative_to(proj)),
            },
        }, indent=2))
    else:
        print(f"Task {args.task}")
        if r.issue_path:
            print(f"  ↑ Issue {r.issue_id}: {r.issue_fm.get('title', '')}  "
                  f"[{r.issue_fm.get('status', '?')}]")
            print(f"     {r.issue_path.relative_to(proj)}")
        else:
            print("  (no Issue references this task — orphan task)")
        if r.epic_path:
            print(f"  ↑ Epic  {r.epic_id}: {r.epic_fm.get('title', '')}  "
                  f"[{r.epic_fm.get('status', '?')}]")
        if r.sprint_path:
            print(f"  Sprint {r.sprint_id}")
    return 0 if r.issue_path is not None else 2


def cmd_review(args):
    cfg, path = load_config()
    if cfg is None or path is None:
        return _fail("mentor: no config found")
    proj = path.parent.parent
    violations = review(proj, cfg)
    if args.format == "json":
        print(json.dumps({
            "mode": cfg.mode,
            "violations": [
                {"kind": v.kind, "path": v.path, "detail": v.detail}
                for v in violations
            ],
        }, indent=2))
    else:
        if not violations:
            print(f"mentor: review clean (mode: {cfg.mode}).")
        else:
            print(f"mentor: {len(violations)} violation(s) (mode: {cfg.mode}):")
            for v in violations:
                print(f"  [{v.kind}] {v.path}: {v.detail}")
    return 0 if not violations else 2


def _remap_scaffold_path(rule_path: str, cfg: MentorConfig) -> str:
    """Map a framework's default scaffold path to the user's configured path.

    Framework yaml uses default paths (doc/SPEC.md, doc/Epic/, ...). Users may
    override these in mentor.yaml's `paths.*` block. Map default → configured
    by simple prefix substitution; fall back to literal when no mapping fits.
    """
    p = rule_path
    if p == "doc/SPEC.md":
        return cfg.paths.spec
    if p == "doc/task.md":
        return cfg.paths.task_fallback
    prefix_map = [
        ("doc/Wiki/", cfg.paths.wiki),
        ("doc/Epic/", cfg.paths.epic),
        ("doc/Sprint/", cfg.paths.sprint),
        ("doc/Issue/", cfg.paths.issue),
        ("doc/current_state/", cfg.current_state.path),
    ]
    for default_prefix, user_prefix in prefix_map:
        if p.startswith(default_prefix):
            up = user_prefix if user_prefix.endswith("/") else user_prefix + "/"
            return up + p[len(default_prefix):]
    return p


def _evaluate_when(when: str, cfg: MentorConfig, proj: Path) -> tuple[bool, str | None]:
    """Return (applicable, skip_reason) for a scaffold rule's `when` clause."""
    when = (when or "").strip()
    if not when:
        return True, None
    if when == "no-kanban":
        if kanban_installed(proj):
            return False, "kanban plugin installed — task fallback not needed"
        return True, None
    if when == "current_state_enabled":
        if not cfg.current_state.enabled:
            return False, "current_state.enabled is false"
        return True, None
    return True, None


def cmd_upgrade(args):
    cfg, cfg_path = load_config()
    if cfg is None or cfg_path is None:
        return _fail("mentor: no .claude/mentor.yaml found — run /mentor:init first")
    proj = cfg_path.parent.parent

    plugin_root = HERE.parent  # scripts/ → plugin root
    fw_yaml = plugin_root / "frameworks" / cfg.mode / "framework.yaml"
    if not fw_yaml.is_file():
        return _fail(f"mentor: framework.yaml not found at {fw_yaml}")

    try:
        fw = load_yaml(fw_yaml)
    except Exception as e:
        return _fail(f"mentor: failed to parse {fw_yaml}: {e}")

    template_root = plugin_root / "frameworks" / cfg.mode / "templates"
    scaffold = fw.get("scaffold") or []

    items: list[dict] = []
    for rule in scaffold:
        rule_path = str(rule.get("path", "")).strip()
        if not rule_path:
            continue
        applicable, skip_reason = _evaluate_when(str(rule.get("when", "")), cfg, proj)
        target_rel = _remap_scaffold_path(rule_path, cfg)
        target = proj / target_rel
        from_tpl = str(rule.get("from_template", "")).strip()
        tpl_path = (template_root / from_tpl).resolve() if from_tpl else None
        items.append({
            "rule_path": rule_path,
            "target": target_rel,
            "exists": target.is_file(),
            "applicable": applicable,
            "skip_reason": skip_reason,
            "required": bool(rule.get("required", False)),
            "tpl_path": tpl_path,
            "from_template": from_tpl,
        })

    applied: list[str] = []
    if args.apply:
        for it in items:
            if not it["applicable"] or it["exists"] or it["tpl_path"] is None:
                continue
            tpl: Path = it["tpl_path"]
            if not tpl.is_file():
                # Template missing on disk — surface as a warning, don't crash
                continue
            target = proj / it["target"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(tpl.read_text(encoding="utf-8"), encoding="utf-8")
            it["exists"] = True
            applied.append(it["target"])

    missing_req = [it for it in items if it["applicable"] and not it["exists"] and it["required"]]
    missing_opt = [it for it in items if it["applicable"] and not it["exists"] and not it["required"]]
    present = [it for it in items if it["applicable"] and it["exists"]]
    skipped = [it for it in items if not it["applicable"]]

    if args.format == "json":
        print(json.dumps({
            "mode": cfg.mode,
            "applied": applied,
            "present": [it["target"] for it in present],
            "missing_required": [
                {"target": it["target"], "from_template": it["from_template"]}
                for it in missing_req
            ],
            "missing_optional": [
                {"target": it["target"], "from_template": it["from_template"]}
                for it in missing_opt
            ],
            "skipped": [
                {"target": it["target"], "reason": it["skip_reason"]}
                for it in skipped
            ],
        }, indent=2))
    else:
        print(f"mentor upgrade — mode: {cfg.mode}")
        if applied:
            print(f"\nApplied ({len(applied)}):")
            for p in applied:
                print(f"  + {p}")
        if missing_req:
            print(f"\nMissing required ({len(missing_req)}):")
            for it in missing_req:
                print(f"  - {it['target']}  (template: {it['from_template']})")
        if missing_opt:
            print(f"\nMissing optional ({len(missing_opt)}):")
            for it in missing_opt:
                print(f"  - {it['target']}  (template: {it['from_template']})")
        if skipped:
            print(f"\nSkipped ({len(skipped)}):")
            for it in skipped:
                print(f"  - {it['target']}  ({it['skip_reason']})")
        if args.verbose and present:
            print(f"\nPresent ({len(present)}):")
            for it in present:
                print(f"  = {it['target']}")
        if not args.apply and (missing_req or missing_opt):
            print("\nRun `workbench-mentor upgrade --apply` to fill in missing files "
                  "(never overwrites existing).")
        elif applied:
            print(f"\n{len(applied)} file(s) created. Existing files were never modified.")
        elif not missing_req and not missing_opt:
            print("\nNothing to do — all expected scaffold files are present.")

    return 2 if missing_req else 0


def cmd_new(args):
    """Minimal stub. The rich interactive path lives in /mentor:new (command)."""
    if args.format == "json":
        print(json.dumps({
            "note": "Use `/mentor:new <type>` slash command inside Claude Code for the "
                    "interactive flow. This CLI path is reserved for sibling-plugin use.",
            "type": args.type,
            "title": args.title,
        }))
    else:
        print("Use /mentor:new <type> in Claude Code for the interactive flow.")
    return 0


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--format", choices=["json", "text"], default="json")

    ap = argparse.ArgumentParser(prog="workbench-mentor", parents=[common])
    ap.add_argument("--health", action="store_true")
    sub = ap.add_subparsers(dest="subcmd")

    sp = sub.add_parser("config", parents=[common])
    sp.set_defaults(func=cmd_config)

    sp = sub.add_parser("active-sprint", parents=[common])
    sp.set_defaults(func=cmd_active_sprint)

    sp = sub.add_parser("trace", parents=[common])
    sp.add_argument("task")
    sp.set_defaults(func=cmd_trace)

    sp = sub.add_parser("review", parents=[common])
    sp.set_defaults(func=cmd_review)

    sp = sub.add_parser("upgrade", parents=[common])
    sp.add_argument("--apply", action="store_true",
                    help="Create missing scaffold files from templates "
                         "(never overwrites existing).")
    sp.add_argument("--verbose", action="store_true",
                    help="Also list scaffold files that are already present.")
    sp.set_defaults(func=cmd_upgrade)

    sp = sub.add_parser("new", parents=[common])
    sp.add_argument("type", choices=["epic", "sprint", "issue", "adr"])
    sp.add_argument("--title", default="")
    sp.set_defaults(func=cmd_new)

    return ap


def main() -> int:
    ap = build_parser()
    args = ap.parse_args()
    if args.health:
        return cmd_health(args)
    if not args.subcmd:
        ap.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
