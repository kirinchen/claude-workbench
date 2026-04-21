#!/usr/bin/env python3
"""workbench-docsync — public CLI for the claude-workbench docsync plugin.

Subcommands:

  match <path>         Which rules match this path?
  check --since <ref>  Pending doc syncs since a git ref. Exit 2 if pending.
  summarize            Summarise doc changes in the current session (for memory).
  rules                Print all rules as JSON.
  validate             Validate the YAML shape + paths; exit 0 if clean.
  --health             Capability-detection check (exit 0 iff usable).

All subcommands support ``--format json`` (default) or ``--format text``.
All are read-only. The plugin never mutates ``.claude/docsync.yaml`` itself —
that's the user's to own.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from rule_engine import (  # noqa: E402
    changed_files_since,
    load_config,
    match_rules,
    pending_syncs,
    pending_to_json,
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
        return _fail("docsync: no .claude/docsync.yaml found")
    if not cfg.rules:
        return _fail("docsync: config has zero rules; nothing to enforce")
    print(f"docsync: ok ({path})")
    return 0


def cmd_match(args):
    cfg, path = load_config()
    if cfg is None:
        return _fail("docsync: no config found")
    matches = match_rules(cfg, [args.path])
    if args.format == "json":
        out = {
            "path": args.path,
            "config": str(path) if path else None,
            "matches": [
                {
                    "rule_id": r.id,
                    "pattern": r.pattern,
                    "docs": [
                        {"path": d.path, "section": d.section,
                         "required": d.required, "required_if": d.required_if}
                        for d in r.docs
                    ],
                }
                for _, r in matches
            ],
        }
        print(json.dumps(out, indent=2))
    else:
        if not matches:
            print(f"No rules match {args.path}.")
            return 0
        print(f"Matches for {args.path}:")
        for _, r in matches:
            print(f"  rule {r.id}  (pattern: {r.pattern})")
            for d in r.docs:
                sec = f" §{d.section}" if d.section else ""
                ri = f" required_if={d.required_if}" if d.required_if else ""
                print(f"    → {d.path}{sec}   required={d.required}{ri}")
    return 0


def cmd_check(args):
    cfg, path = load_config()
    if cfg is None or path is None:
        return _fail("docsync: no config found")
    proj = path.parent.parent
    changed = changed_files_since(proj, args.since)
    pending = pending_syncs(cfg, changed)
    if args.format == "json":
        print(pending_to_json(pending))
    else:
        if not pending:
            print(f"docsync: clean (since {args.since}).")
        else:
            print(f"docsync: {len(pending)} pending sync(s) since {args.since}:")
            for p in pending:
                sec = f" §{p.doc_section}" if p.doc_section else ""
                ri = f" ({p.required_if})" if p.required_if else ""
                print(f"  - {p.doc_path}{sec}{ri}   ← {p.code_path} (rule: {p.rule_id})")
    return 2 if pending else 0


def cmd_summarize(args):
    cfg, path = load_config()
    if cfg is None or path is None:
        return _fail("docsync: no config found")
    proj = path.parent.parent
    changed = changed_files_since(proj, args.since)
    docs_changed = [c for c in changed if c.lower().endswith((".md", ".mdx", ".rst"))]
    pending = pending_syncs(cfg, changed)
    if args.format == "json":
        print(json.dumps({
            "session": args.session,
            "docs_changed": docs_changed,
            "pending": json.loads(pending_to_json(pending))["pending"],
        }))
    else:
        print(f"Session {args.session or 'unknown'}:")
        print(f"  {len(docs_changed)} docs changed, {len(pending)} pending.")
        for d in docs_changed:
            print(f"  updated: {d}")
        for p in pending:
            print(f"  pending: {p.doc_path} ← {p.code_path}")
    return 0


def cmd_rules(args):
    cfg, path = load_config()
    if cfg is None:
        return _fail("docsync: no config found")
    if args.format == "json":
        print(json.dumps({
            "config": str(path) if path else None,
            "rules": [
                {
                    "id": r.id,
                    "pattern": r.pattern,
                    "docs": [
                        {"path": d.path, "section": d.section,
                         "required": d.required, "required_if": d.required_if}
                        for d in r.docs
                    ],
                } for r in cfg.rules
            ],
            "enforcement": cfg.enforcement,
            "skip_conditions": cfg.skip_conditions,
            "bootstrap_docs": cfg.bootstrap_docs,
        }, indent=2))
    else:
        print(f"docsync config: {path}")
        print(f"enforcement: {cfg.enforcement}")
        print(f"bootstrap_docs ({len(cfg.bootstrap_docs)}):")
        for d in cfg.bootstrap_docs:
            print(f"  - {d}")
        print(f"rules ({len(cfg.rules)}):")
        for r in cfg.rules:
            print(f"  {r.id}  pattern={r.pattern}")
            for d in r.docs:
                sec = f" §{d.section}" if d.section else ""
                ri = f" required_if={d.required_if}" if d.required_if else ""
                print(f"    → {d.path}{sec}  required={d.required}{ri}")
        print(f"skip_conditions: {', '.join(cfg.skip_conditions) or '(none)'}")
    return 0


def cmd_validate(_args):
    cfg, path = load_config()
    if cfg is None or path is None:
        return _fail("docsync: no config found")
    errors = []
    proj = path.parent.parent
    if cfg.schema_version != 1:
        errors.append(f"schema_version must be 1 (got {cfg.schema_version})")
    if cfg.enforcement not in ("silent", "warn", "block"):
        errors.append(f"enforcement must be silent|warn|block (got {cfg.enforcement!r})")
    seen_ids = set()
    for r in cfg.rules:
        if not r.pattern:
            errors.append(f"rule {r.id}: empty pattern")
        if r.id in seen_ids:
            errors.append(f"rule {r.id}: duplicate id")
        seen_ids.add(r.id)
        for d in r.docs:
            if d.required_if and d.required_if not in (
                "architecture_changed", "api_changed",
                "params_changed", "schema_changed",
            ):
                errors.append(f"rule {r.id}: unknown required_if={d.required_if!r}")
    for bd in cfg.bootstrap_docs:
        if not (proj / bd).is_file():
            errors.append(f"bootstrap_docs: missing file {bd}")

    if errors:
        for e in errors:
            print(f"  ✗ {e}", file=sys.stderr)
        return 2
    print(f"docsync: {path} validates clean "
          f"({len(cfg.rules)} rules, {len(cfg.bootstrap_docs)} bootstrap docs).")
    return 0


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def build_parser():
    # Common flags available on both the top-level and each subcommand so
    # ``workbench-docsync match path --format json`` works as expected.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--format", choices=["json", "text"], default="json",
                        help="Output format (default: json).")

    ap = argparse.ArgumentParser(prog="workbench-docsync", parents=[common])
    ap.add_argument("--health", action="store_true",
                    help="Exit 0 iff docsync is configured and usable.")
    sub = ap.add_subparsers(dest="subcmd")

    sp = sub.add_parser("match", parents=[common],
                        help="Which rules match a given path?")
    sp.add_argument("path")
    sp.set_defaults(func=cmd_match)

    sp = sub.add_parser("check", parents=[common],
                        help="Pending doc syncs since a git ref.")
    sp.add_argument("--since", default="HEAD~1")
    sp.set_defaults(func=cmd_check)

    sp = sub.add_parser("summarize", parents=[common],
                        help="Summarise doc changes this session.")
    sp.add_argument("--session", default=None)
    sp.add_argument("--since", default="HEAD~20")
    sp.set_defaults(func=cmd_summarize)

    sp = sub.add_parser("rules", parents=[common], help="Dump all rules.")
    sp.set_defaults(func=cmd_rules)

    sp = sub.add_parser("validate", parents=[common], help="Validate the YAML.")
    sp.set_defaults(func=cmd_validate)

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
