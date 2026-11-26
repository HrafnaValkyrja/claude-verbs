"""ship: the whole change flow as one verb that expands into visible steps.

PURPOSE: worktree -> edits/files -> commit -> push -> PR (+merge) -> deploy
         copies -> after-commands -> remove the worktree, as one call.
WHY: shipping a change took 3 to 10 tool calls; as a plan it is one, and the
     report still names the step that failed.
REFS: PLAN.md phase 2 ("ship (the whole change flow)").
LOGS: none of its own (the runner logs every step, labelled "[ship]").
READS-BY: plan files, tests
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path
from types import SimpleNamespace

from .core import Step, _active
from .gitflow import commit, default_worktree_path, pr, push, worktree
from .proc import run_proc
from .verbs import copy, edit, sh

GROUP = "ship"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "change"


def _inside(repo: Path, wt: Path, path) -> Path:
    """Map a path given relative to the repo (or absolute inside it) into the worktree."""
    p = Path(path)
    if p.is_absolute():
        try:
            p = p.relative_to(repo)
        except ValueError:
            raise ValueError(f"{path} is outside the repo {repo}") from None
    if ".." in p.parts:
        raise ValueError(f"{path} escapes the repo")
    return wt / p


def _remove_worktree(repo, wt) -> Step:
    """Cleanup that runs even after a failure; never touches the main checkout."""
    def check(a):
        r, p = Path(a["repo"]).resolve(), Path(a["wt"]).resolve()
        if p == r or r in p.parents:
            raise ValueError(f"refusing to remove the main checkout {p}")
        return r, p

    def do(a, _t):
        r, p = check(a)
        if not p.exists():
            return "nothing to remove"
        o = run_proc(["git", "-C", str(r), "worktree", "remove", "--force", str(p)])
        if o.code != 0:
            raise RuntimeError((o.err or o.out).strip())
        return f"removed {p}"

    def simulate(a):
        return f"remove worktree {check(a)[1]}"

    return Step("worktree", do, {"repo": repo, "wt": wt}, simulate=simulate, always=True,
                subject=lambda a: f"remove {a['wt']}")


def ship(repo, reason: str, edits=(), files: dict | None = None, branch: str | None = None,
         base: str = "main", merge: bool = True, deploy=(), after=(), cleanup: bool = True,
         ) -> SimpleNamespace:
    """Ship a change: expands into one step per stage, all labelled [ship].

    edits: (path, old, new) exact replaces; files: {dest_in_repo: local_src};
    both paths are relative to repo and land in a fresh sibling worktree.
    deploy: (src_in_repo, dest, host or None) copies made after the merge.
    after: commands (strings run in the worktree) or sh steps, run last.
    cleanup removes the worktree even when an earlier step failed.
    Returns .steps, .pr (the pr step) and lazy .number / .url."""
    repo = Path(repo).absolute()
    branch = branch or f"ship/{_slug(reason)}-{uuid.uuid4().hex[:6]}"
    wt = default_worktree_path(repo, branch)
    plan = _active.get()
    # sh steps built before this call already joined the plan; re-place them after the deploys.
    late = list(after)
    if plan is not None:
        plan.steps[:] = [s for s in plan.steps if not any(s is x for x in late)]
    start = len(plan.steps) if plan is not None else 0
    g = {"group": GROUP}

    worktree(repo, branch, base=f"origin/{base}", path=wt, **g)
    for path, old, new in edits:
        edit(_inside(repo, wt, path), old, new, **g)
    for dest, src in (files or {}).items():
        copy(src, _inside(repo, wt, dest), **g)
    commit(wt, reason, **g)
    push(wt, branch, **g)
    made = pr(wt, reason.splitlines()[0], reason, base=base, merge=merge, **g)
    for src, dest, host in deploy:
        copy(_inside(repo, wt, src), dest, host=host, **g)
    for item in late:
        if isinstance(item, Step):
            item.group = GROUP
            if plan is not None:
                plan.steps.append(item)
        else:
            sh(item, cwd=wt, **g)
    if cleanup:
        _remove_worktree(repo, wt).group = GROUP
    steps = plan.steps[start:] if plan is not None else []
    return SimpleNamespace(steps=steps, pr=made, number=made.number, url=made.url,
                           branch=branch, path=wt)
