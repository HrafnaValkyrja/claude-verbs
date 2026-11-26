"""Git verbs: worktree, commit, push, pr.

PURPOSE: the change flow's git steps, each an inert Step like any other verb.
WHY: work happens in a sibling worktree, never in the main checkout; pull
     requests go through the REST API because GraphQL has been flaky.
REFS: PLAN.md phase 2 and "Generic verbs".
LOGS: none of its own (the runner logs every step).
READS-BY: claude_verbs.ship, plan files, tests
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .core import Step, vfs
from .proc import DEFAULT_TIMEOUT, run_proc


def _git(path, *args, timeout=DEFAULT_TIMEOUT) -> str:
    """Run git -C path ...; return stdout (stripped) or raise with git's own message."""
    o = run_proc(["git", "-C", str(path), *args], timeout=timeout)
    if o.code != 0:
        raise RuntimeError(f"git {' '.join(args[:2])}: {(o.err or o.out).strip() or 'exit ' + str(o.code)}")
    return o.out.strip()


def default_worktree_path(repo, branch: str) -> Path:
    repo = Path(repo).absolute()
    return repo.parent / f"{repo.name}-{branch.replace('/', '-')}"


def worktree(repo, branch: str, base: str = "origin/main", path=None, **opts) -> Step:
    """Fetch base, then add a new worktree on a new branch as a sibling of repo.

    Refuses to use the repo's own checkout (path is repo or inside it), a branch
    that is the main checkout's current branch or the base branch, and a path
    that already exists. The step has .path and .branch, known at plan time."""
    wt = Path(path).absolute() if path is not None else default_worktree_path(repo, branch)

    def check(a):
        r, p = Path(a["repo"]).resolve(), Path(a["path"]).resolve()
        if p == r or r in p.parents:
            raise ValueError(f"refusing to use the main checkout: {p} is inside {r}")
        current = _git(r, "symbolic-ref", "--short", "-q", "HEAD") if _has_head(r) else ""
        if a["branch"] in (current, a["base"].split("/")[-1]):
            raise ValueError(f"refusing branch {a['branch']!r}: it is the main checkout's or the base branch")
        if p.exists():
            raise ValueError(f"{p} already exists")
        return r, p

    def do(a, timeout):
        r, p = check(a)
        remote, _, ref = a["base"].partition("/")
        if ref and remote in _git(r, "remote").split():
            _git(r, "fetch", remote, ref, timeout=timeout or DEFAULT_TIMEOUT)
        _git(r, "worktree", "add", "-b", a["branch"], str(p), a["base"])
        return str(p)

    def simulate(a):
        r, p = check(a)
        vfs().alias(p, r)
        return f"fetch {a['base']}, add worktree {p} on new branch {a['branch']}"

    st = Step("worktree", do, {"repo": repo, "branch": branch, "base": base, "path": wt},
              simulate=simulate, subject=lambda a: f"add {a['path']} {a['branch']}", **opts)
    st.path, st.branch = wt, branch
    return st


def _has_head(repo) -> bool:
    return run_proc(["git", "-C", str(repo), "rev-parse", "-q", "--verify", "HEAD"]).code == 0


def _is_repo(path) -> bool:
    return run_proc(["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"]).code == 0


def commit(path, message: str, author: str | None = None, all: bool = True, **opts) -> Step:
    """Commit in path (git add -A first when all). Fails when there is nothing to commit.
    The step's output is the short hash."""
    def do(a, timeout):
        if a["all"]:
            _git(a["path"], "add", "-A")
        cmd = ["commit", "-q", "-m", a["message"]]
        if a["author"]:
            cmd.append(f"--author={a['author']}")
        _git(a["path"], *cmd)
        return _git(a["path"], "rev-parse", "--short", "HEAD")

    def simulate(a):
        p = Path(a["path"])
        if vfs().exists(p) and not _is_repo(vfs()._real(p.absolute())):
            raise ValueError(f"{p} is not a git work tree")
        return f"commit{' -a' if a['all'] else ''} in {p}: {a['message'].splitlines()[0][:50]}"

    return Step("commit", do, {"path": path, "message": message, "author": author, "all": all},
                simulate=simulate, subject=lambda a: f"{a['path']} {a['message']}", **opts)


def push(path, branch: str, **opts) -> Step:
    """Push branch to origin and set its upstream."""
    def do(a, timeout):
        _git(a["path"], "push", "-q", "-u", "origin", a["branch"], timeout=timeout or DEFAULT_TIMEOUT)
        return f"pushed {a['branch']}"

    return Step("push", do, {"path": path, "branch": branch},
                simulate=lambda a: f"push {a['branch']} to origin",
                subject=lambda a: f"{a['path']} {a['branch']}", **opts)


def owner_repo(remote_url: str) -> str:
    """'owner/repo' from https://host/owner/repo(.git) or git@host:owner/repo(.git)."""
    m = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$", remote_url.strip())
    if not m:
        raise ValueError(f"cannot read owner/repo from remote {remote_url!r}")
    return f"{m.group(1)}/{m.group(2)}"


def _gh(*args, timeout=DEFAULT_TIMEOUT) -> dict:
    o = run_proc(["gh", "api", *args], timeout=timeout)
    if o.code != 0:
        raise RuntimeError(f"gh api {args[0]}: {(o.err or o.out).strip() or 'exit ' + str(o.code)}")
    return json.loads(o.out or "{}")


def pr(repo_path, title: str, body: str = "", base: str = "main", merge: bool = False,
       method: str = "squash", **opts) -> Step:
    """Open a pull request from repo_path's current branch via the REST API, and
    optionally merge it (squash by default). owner/repo come from the origin URL.
    The step has lazy .number, .url and .merged."""
    def do(a, timeout):
        t = timeout or DEFAULT_TIMEOUT
        slug = owner_repo(_git(a["repo_path"], "config", "--get", "remote.origin.url"))
        head = _git(a["repo_path"], "rev-parse", "--abbrev-ref", "HEAD")
        made = _gh(f"repos/{slug}/pulls", "-X", "POST", "-f", f"title={a['title']}",
                   "-f", f"body={a['body']}", "-f", f"head={head}", "-f", f"base={a['base']}",
                   timeout=t)
        merged = False
        if a["merge"]:
            res = _gh(f"repos/{slug}/pulls/{made['number']}/merge", "-X", "PUT",
                      "-f", f"merge_method={a['method']}", timeout=t)
            merged = bool(res.get("merged"))
            if not merged:
                raise RuntimeError(f"PR #{made['number']} was not merged: {res.get('message', res)}")
        return json.dumps({"number": made["number"], "url": made["html_url"], "merged": merged})

    def simulate(a):
        return (f"open PR '{a['title'][:50]}' into {a['base']}"
                + (f" and merge ({a['method']})" if a["merge"] else ""))

    st = Step("pr", do, {"repo_path": repo_path, "title": title, "body": body, "base": base,
                         "merge": merge, "method": method},
              simulate=simulate, subject=lambda a: f"{a['repo_path']} {a['title']}", **opts)
    data = st.out.map(json.loads)
    st.number, st.url, st.merged = (data.map(lambda d: d["number"]), data.map(lambda d: d["url"]),
                                    data.map(lambda d: d["merged"]))
    return st
