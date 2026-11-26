"""Run one process with a timeout and a kill of its whole group.

PURPOSE: the single place a step turns into an operating-system process.
WHY: sh, copy and the git verbs share timeout and exit-code handling.
REFS: PLAN.md "Core" (timeouts), "Risk gate" (every step is a plain, logged action).
LOGS: none (the runner logs the Outcome).
READS-BY: claude_verbs.verbs, claude_verbs.gitflow
"""
from __future__ import annotations

import os
import re
import shlex
import signal
import socket
import subprocess

from .core import Outcome

DEFAULT_TIMEOUT = 300.0
SSH_OPTS = ("-o", "BatchMode=yes")
SAFE_REMOTE_PATH = re.compile(r"^[\w./@%+=,~-]+$")


def run_proc(cmd, *, shell=False, cwd=None, env: dict | None = None,
             timeout: float = DEFAULT_TIMEOUT) -> Outcome:
    proc = subprocess.Popen(
        cmd, shell=shell, cwd=cwd, text=True, start_new_session=True,
        env={**os.environ, **(env or {})}, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        out, err = proc.communicate()
        return Outcome(-9, out or "", err or "", f"timed out after {timeout:g}s")
    return Outcome(proc.returncode, out, err)


def is_local(host: str | None) -> bool:
    """True when host names this machine (localhost, or its own hostname, short or full).
    A step aimed at its own host runs here instead of ssh-ing to itself, which can fail
    host-key checks (found 11-25 when a plan written for both hosts ran on one of them).
    user@host is never treated as local: it may mean a different account."""
    if host is None:
        return True
    h = host.strip().lower()
    if "@" in h:
        return False
    me = socket.gethostname().lower()
    return h in {"localhost", "127.0.0.1", "::1", me, me.split(".")[0]}


def local_path(path) -> str:
    """A remote-style path read on this machine: ~ expands, and a relative path is
    relative to home, as scp and ssh treat it."""
    p = os.path.expanduser(str(path))
    return p if os.path.isabs(p) else os.path.join(os.path.expanduser("~"), p)


def ssh_argv(host: str, remote_cmd: str, connect_timeout: int) -> list[str]:
    """ssh never prompts (BatchMode) and gives up connecting after connect_timeout seconds.
    remote_cmd is one string for the remote shell; no local shell is involved."""
    if host.startswith("-"):
        raise ValueError(f"bad host {host!r}")
    return ["ssh", *SSH_OPTS, "-o", f"ConnectTimeout={connect_timeout}", "--", host, remote_cmd]


def remote_command(cmd: str, cwd=None, env: dict | None = None) -> str:
    """Prefix cmd with quoted env exports and a quoted cd, for the remote shell."""
    head = ""
    for k, v in (env or {}).items():
        if not re.fullmatch(r"[A-Za-z_]\w*", k):
            raise ValueError(f"bad environment variable name {k!r}")
        head += f"export {k}={shlex.quote(str(v))}; "
    if cwd is not None:
        head += f"cd {shlex.quote(str(cwd))} && "
    return head + cmd
