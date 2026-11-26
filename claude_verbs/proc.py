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
