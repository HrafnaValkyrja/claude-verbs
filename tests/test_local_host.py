import socket
from pathlib import Path

from claude_verbs import Plan, run
from claude_verbs.proc import is_local, local_path
from claude_verbs.verbs import copy, sh


def test_is_local_names():
    me = socket.gethostname()
    assert is_local("localhost") and is_local(me) and is_local(me.upper()) and is_local(me.split(".")[0])
    assert not is_local("some-other-host-xyz") and not is_local(f"bob@{me}")


def test_sh_on_own_host_runs_here_without_ssh(monkeypatch, tmp_path):
    import claude_verbs.verbs as V
    monkeypatch.setattr(V, "ssh_argv", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ssh used")))
    with Plan() as p:
        sh("pwd", host=socket.gethostname(), cwd=str(tmp_path))
    r = run(p)
    assert [x.status for x in r.results] == ["ok"] and r.results[0].out.strip() == str(tmp_path)


def test_copy_to_own_host_is_local(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    src = tmp_path / "a.txt"; src.write_text("hi")
    with Plan() as p:
        copy(src, "sub/b.txt", host="localhost")
    assert [x.status for x in run(p).results] == ["ok"]
    assert (tmp_path / "sub/b.txt").read_text() == "hi"
    assert local_path("x") == str(tmp_path / "x")
