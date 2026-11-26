"""Command line: claude-verbs run plan.py [--dry] [--policy p.toml] [--log-dir d].

PURPOSE: execute a plan file and print its report.
WHY: one command per plan; exit code says what happened (0 ok, 1 step failed, 2 denied or bad input).
REFS: PLAN.md Phase 1.
READS-BY: console script `claude-verbs`, `python -m claude_verbs`
"""
from __future__ import annotations

import argparse
import hashlib
import os
import time
from pathlib import Path
import runpy
import sys

from .core import Plan, PolicyDenied, RunError, run
from .policy import Policy


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="claude-verbs")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a plan file")
    r.add_argument("plan")
    r.add_argument("--dry", action="store_true", help="simulate; change nothing")
    r.add_argument("--verbose", "-v", action="store_true", help="show every ok step's output")
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
    pol = Policy.resolve(a.policy)
    need = sorted({s.risk for s in plan.steps} & set(pol.dry_first_classes()))
    stamp = _dry_stamp(a.plan)
    if need and not a.dry and not _fresh(stamp, pol.dry_first_minutes):
        print(f"claude-verbs: this plan has {'/'.join(need)} steps and the policy wants a dry run first; "
              f"run it with --dry, read the report, then run it again", file=sys.stderr)
        return 2
    try:
        report = run(plan, dry=a.dry, policy=pol, log_dir=a.log_dir, verbose=a.verbose)
    except PolicyDenied as e:
        print(e.report)
        print(f"claude-verbs: {e}", file=sys.stderr)
        return 2
    except RunError as e:
        print(e.report)
        return 1
    if a.dry:
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.touch()
    print(report)
    return 0


def _dry_stamp(plan_path) -> Path:
    """One stamp per plan text: an edited plan needs a new dry run."""
    digest = hashlib.sha256(Path(plan_path).read_bytes()).hexdigest()[:16]
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    return base / "claude-verbs" / "dry" / digest


def _fresh(stamp: Path, minutes: float) -> bool:
    try:
        return time.time() - stamp.stat().st_mtime < minutes * 60
    except OSError:
        return False
