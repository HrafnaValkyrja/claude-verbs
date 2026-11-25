"""Command line: claude-verbs run plan.py [--dry] [--policy p.toml] [--log-dir d].

PURPOSE: execute a plan file and print its report.
WHY: one command per plan; exit code says what happened (0 ok, 1 step failed, 2 denied or bad input).
REFS: PLAN.md Phase 1.
READS-BY: console script `claude-verbs`, `python -m claude_verbs`
"""
from __future__ import annotations

import argparse
import runpy
import sys

from .core import Plan, PolicyDenied, RunError, run


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="claude-verbs")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a plan file")
    r.add_argument("plan")
    r.add_argument("--dry", action="store_true", help="simulate; change nothing")
    r.add_argument("--policy", help="TOML policy file (default: $CLAUDE_VERBS_POLICY, else built-in)")
    r.add_argument("--log-dir", help="directory for the JSONL run log")
    a = ap.parse_args(argv)

    try:
        with Plan() as plan:
            runpy.run_path(a.plan, run_name="__plan__")
    except FileNotFoundError:
        print(f"claude-verbs: no such plan file: {a.plan}", file=sys.stderr)
        return 2
    if not plan.steps:
        print(f"claude-verbs: {a.plan} made no steps; nothing ran", file=sys.stderr)
        return 2
    try:
        report = run(plan, dry=a.dry, policy=a.policy, log_dir=a.log_dir)
    except PolicyDenied as e:
        print(e.report)
        print(f"claude-verbs: {e}", file=sys.stderr)
        return 2
    except RunError as e:
        print(e.report)
        return 1
    print(report)
    return 0
