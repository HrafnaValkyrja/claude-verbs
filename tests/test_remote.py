import pytest

from claude_verbs import Plan, StepFailed, copy, edit, run, sh, write


def test_sh_host_goes_through_ssh_with_batchmode_and_timeout(fakes, env):
    d = env / "dir with space"
    d.mkdir()
    with Plan() as plan:
        s = sh("echo 'a b' && pwd", host="box", cwd=d, env={"K": "v w"})
    run(plan)
    assert s.result.out.splitlines() == ["a b", str(d)]
    call = fakes.lines()[0]
    assert "-o BatchMode=yes" in call and "-o ConnectTimeout=" in call and " box " in call


def test_sh_host_quotes_cwd_and_env(fakes, env):
    with Plan() as plan:
        s = sh('echo "$K"', host="box", env={"K": "x; echo pwned"})
    run(plan)
    assert s.result.out.strip() == "x; echo pwned"


def test_remote_failure_exit_code_is_reported(fakes):
    with Plan() as plan:
        sh("exit 3", host="box")
    with pytest.raises(StepFailed) as exc:
        run(plan)
    assert exc.value.report.results[0].code == 3


def test_remote_sh_is_care_risk(fakes):
    with Plan():
        assert sh("true", host="box").risk == "care"


def test_copy_local(env):
    src, dest = env / "a.txt", env / "sub" / "b.txt"
    src.write_text("hi")
    with Plan() as plan:
        copy(src, dest)
    run(plan)
    assert dest.read_text() == "hi"


def test_copy_to_host_uses_scp(fakes, env):
    src, dest = env / "a.txt", env / "b.txt"
    src.write_text("hi")
    with Plan() as plan:
        c = copy(src, dest, host="box")
    run(plan)
    assert dest.read_text() == "hi"
    assert c.risk == "care"
    call = fakes.lines()[0]
    assert call.startswith("scp ") and "BatchMode=yes" in call and f"box:{dest}" in call


def test_copy_to_host_rejects_unsafe_remote_path(fakes, env):
    (env / "a.txt").write_text("x")
    with Plan() as plan:
        copy(env / "a.txt", "/tmp/x; reboot", host="box")
    with pytest.raises(StepFailed):
        run(plan)
    assert fakes.lines() == []


def test_dry_edit_after_write_to_new_path_simulates(env):
    f = env / "new.txt"
    with Plan() as plan:
        write(f, "alpha beta\n")
        edit(f, "beta", "gamma")
        edit(f, "beta", "x")  # gone after the first edit
    report = run(plan, dry=True, raise_on_fail=False)
    assert [r.status for r in report.results] == ["ok", "ok", "failed"]
    assert not f.exists()


def test_dry_copy_then_edit(env):
    src = env / "a.txt"
    src.write_text("one")
    with Plan() as plan:
        copy(src, env / "b.txt")
        edit(env / "b.txt", "one", "two")
    report = run(plan, dry=True)
    assert report.ok and not (env / "b.txt").exists()
