"""Generic verbs: sh (local or over ssh), copy, edit, write, trash (+ restore).

PURPOSE: the everyday actions a plan is made of, each an inert Step.
WHY: edits are exact and unique, writes are atomic, deletes are recoverable.
REFS: PLAN.md "Generic verbs".
LOGS: none of its own (the runner logs every step).
READS-BY: plan files, tests
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from .core import Step, vfs
from .proc import DEFAULT_TIMEOUT, SAFE_REMOTE_PATH, SSH_OPTS, is_local, local_path, remote_command, run_proc, ssh_argv


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o7777 if path.exists() else None
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def sh(cmd: str, cwd=None, env: dict | None = None, host: str | None = None, *,
       timeout: float = DEFAULT_TIMEOUT, connect_timeout: int = 10, **opts) -> Step:
    """Run a shell command, here or on host over ssh (BatchMode, never prompts).

    With host, cwd and env apply on the remote side and are shell-quoted; cmd is
    shell text for the remote shell. A remote command is risk "care"."""
    def do(a, _timeout):
        limit = _timeout if _timeout is not None else timeout
        if a["host"] is None:
            return run_proc(a["cmd"], shell=True, cwd=a["cwd"], env=a["env"], timeout=limit)
        if is_local(a["host"]):   # aimed at this machine: run here, with remote-style cwd
            cwd = local_path(a["cwd"]) if a["cwd"] is not None else os.path.expanduser("~")
            return run_proc(a["cmd"], shell=True, cwd=cwd, env=a["env"], timeout=limit)
        remote = remote_command(a["cmd"], a["cwd"], a["env"])
        return run_proc(ssh_argv(a["host"], remote, connect_timeout), timeout=limit)

    opts.setdefault("risk", "care")
    opts.setdefault("timeout", timeout)
    return Step("sh", do, {"cmd": cmd, "cwd": cwd, "env": env, "host": host},
                subject=lambda a: a["cmd"], **opts)


def edit(path, old: str, new: str, **opts) -> Step:
    """Replace old with new in a file; old must occur exactly once."""
    def check(a, read=lambda p: p.read_text()):
        p = Path(a["path"])
        text = read(p)
        n = text.count(a["old"])
        if not a["old"]:
            raise ValueError("old text is empty")
        if n != 1:
            raise ValueError(f"old text found {n} times in {p}, need exactly 1")
        return p, text

    def do(a, _t):
        p, text = check(a)
        _atomic_write(p, text.replace(a["old"], a["new"], 1))
        return f"edited {p}"

    def simulate(a):
        v = vfs()
        p, text = check(a, v.read)
        v.write(p, text.replace(a["old"], a["new"], 1))
        return f"edit {p} (1 match)"

    return Step("edit", do, {"path": path, "old": old, "new": new}, simulate=simulate,
                subject=lambda a: str(a["path"]), **opts)


def write(path, text: str, **opts) -> Step:
    """Write text to a file (creating parent dirs), replacing it atomically."""
    def check(a):
        p = Path(a["path"])
        if p.is_dir():
            raise IsADirectoryError(str(p))
        return p

    def do(a, _t):
        _atomic_write(check(a), a["text"])
        return f"wrote {a['path']}"

    def simulate(a):
        p, v = check(a), vfs()
        verb = "overwrite" if v.exists(p) else "create"
        v.write(p, a["text"])
        return f"{verb} {p} ({len(a['text'])} chars)"

    return Step("write", do, {"path": path, "text": text}, simulate=simulate,
                subject=lambda a: str(a["path"]), **opts)


def trash_dir() -> Path:
    env = os.environ.get("CLAUDE_VERBS_TRASH")
    return Path(env) if env else Path.home() / ".local/share/claude-verbs/trash"


def trash(path, **opts) -> Step:
    """Move a file or directory into the trash (never rm). The step's output
    is an item id; restore(item_id) puts it back."""
    def check(a):
        p = Path(a["path"]).absolute()
        if not (p.exists() or p.is_symlink()):
            raise FileNotFoundError(str(p))
        return p

    def do(a, _t):
        p = check(a)
        item = f"{time.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"
        box = trash_dir() / item
        box.mkdir(parents=True)
        shutil.move(str(p), str(box / "payload"))
        (box / "info.json").write_text(json.dumps(
            {"id": item, "original": str(p), "trashed_at": time.time()}))
        return item

    def simulate(a):
        return f"move {check(a)} to trash"

    return Step("trash", do, {"path": path}, simulate=simulate,
                subject=lambda a: str(a["path"]), **opts)


def restore(item_id: str, trash_directory=None) -> Path:
    """Put a trashed item back where it came from. Never overwrites."""
    box = Path(trash_directory) if trash_directory else trash_dir()
    box = box / item_id
    info = json.loads((box / "info.json").read_text())
    dest = Path(info["original"])
    if dest.exists() or dest.is_symlink():
        raise FileExistsError(f"{dest} exists; refusing to overwrite")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(box / "payload"), str(dest))
    shutil.rmtree(box)
    return dest


def copy(src, dest, host: str | None = None, *, timeout: float = DEFAULT_TIMEOUT,
         connect_timeout: int = 10, **opts) -> Step:
    """Copy a file (or directory) from here to dest, or to dest on host over scp.

    The remote path must be plain (letters, digits and ./@%+=,~-): scp hands it
    to a remote shell, so anything else is refused rather than half-quoted."""
    def check(a):
        if a["host"] is not None:
            if a["host"].startswith("-"):
                raise ValueError(f"bad host {a['host']!r}")
            if not SAFE_REMOTE_PATH.match(str(a["dest"])):
                raise ValueError(f"remote path {str(a['dest'])!r} has characters scp would reinterpret")

    def do(a, _timeout):
        check(a)
        s = Path(a["src"])
        if not s.exists():
            raise FileNotFoundError(str(s))
        limit = _timeout if _timeout is not None else timeout
        if a["host"] is None or is_local(a["host"]):
            d = Path(a["dest"] if a["host"] is None else local_path(a["dest"]))
            d.parent.mkdir(parents=True, exist_ok=True)
            if s.is_dir():
                shutil.copytree(s, d, dirs_exist_ok=True)
            else:
                shutil.copy2(s, d)
            return f"copied {s} to {d}"
        argv = ["scp", "-q", *SSH_OPTS, "-o", f"ConnectTimeout={connect_timeout}"]
        if s.is_dir():
            argv.append("-r")
        argv += ["--", str(s), f"{a['host']}:{a['dest']}"]
        return run_proc(argv, timeout=limit)

    def simulate(a):
        check(a)
        v, s = vfs(), Path(a["src"])
        if not v.exists(s):
            raise FileNotFoundError(str(s))
        if a["host"] is not None:
            return f"copy {s} to {a['host']}:{a['dest']}"
        try:
            v.write(a["dest"], v.read(s))
        except (OSError, ValueError):
            v.write(a["dest"], None)
        return f"copy {s} to {a['dest']}"

    opts.setdefault("risk", "care")
    return Step("copy", do, {"src": src, "dest": dest, "host": host}, simulate=simulate,
                subject=lambda a: f"{a['src']} {a['host'] + ':' if a['host'] else ''}{a['dest']}",
                **opts)
