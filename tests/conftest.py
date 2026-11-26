import os
import subprocess

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolate logs, trash and policy from the real home directory."""
    monkeypatch.setenv("CLAUDE_VERBS_LOG_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("CLAUDE_VERBS_TRASH", str(tmp_path / "trash"))
    monkeypatch.delenv("CLAUDE_VERBS_POLICY", raising=False)
    return tmp_path


FAKE_SSH = """#!/bin/sh
# Fake ssh: log argv, skip options and the host, run the remote command locally.
echo "ssh $*" >> "$FAKE_LOG"
while [ $# -gt 0 ]; do
  case "$1" in
    -o) shift 2 ;;
    --) shift; break ;;
    -*) shift ;;
    *) break ;;
  esac
done
shift  # the host
exec sh -c "$*"
"""

FAKE_SCP = """#!/bin/sh
# Fake scp: log argv, copy locally after stripping "host:" from the destination.
echo "scp $*" >> "$FAKE_LOG"
args=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) shift 2 ;;
    -*) shift ;;
    *) break ;;
  esac
done
src="$1"; dest="${2#*:}"
exec cp -r "$src" "$dest"
"""

FAKE_GH = """#!/bin/sh
# Fake gh: record the call, answer like the REST API.
echo "gh $*" >> "$FAKE_LOG"
case "$*" in
  *"/merge"*) echo '{"merged": true, "message": "Pull Request successfully merged"}' ;;
  *) echo '{"number": 7, "html_url": "https://github.com/acme/widgets/pull/7"}' ;;
esac
"""


@pytest.fixture
def fakes(env, monkeypatch):
    """ssh, scp and gh replaced by local scripts on PATH; calls land in fakes.log."""
    import types
    bindir = env / "fakebin"
    bindir.mkdir()
    for name, body in (("ssh", FAKE_SSH), ("scp", FAKE_SCP), ("gh", FAKE_GH)):
        f = bindir / name
        f.write_text(body)
        f.chmod(0o755)
    log = env / "fake.log"
    log.write_text("")
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_LOG", str(log))
    return types.SimpleNamespace(log=log, lines=lambda: log.read_text().splitlines())


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture
def repo(env, monkeypatch):
    """A throwaway checkout whose origin is a local bare repo that answers to a GitHub URL."""
    import types
    for k, v in (("GIT_AUTHOR_NAME", "T"), ("GIT_AUTHOR_EMAIL", "t@example.com"),
                 ("GIT_COMMITTER_NAME", "T"), ("GIT_COMMITTER_EMAIL", "t@example.com"),
                 ("GIT_CONFIG_GLOBAL", os.devnull), ("GIT_CONFIG_SYSTEM", os.devnull)):
        monkeypatch.setenv(k, v)
    bare, work = env / "origin.git", env / "widgets"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    work.mkdir()
    git(work, "init", "-q", "-b", "main")
    (work / "app.txt").write_text("hello\nworld\n")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "init")
    git(work, "remote", "add", "origin", "https://github.com/acme/widgets.git")
    git(work, "config", f"url.{bare}.insteadOf", "https://github.com/acme/widgets.git")
    git(work, "push", "-q", "origin", "main")
    return types.SimpleNamespace(work=work, bare=bare)
