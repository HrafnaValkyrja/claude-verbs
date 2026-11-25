import subprocess, sys, textwrap
from claude_verbs import Plan, sh, run


def test_nested_plan_steps_join_the_outer_plan():
    with Plan() as outer:
        sh("true")
        with Plan():
            sh("echo inner")
    assert len(outer.steps) == 2
    assert run(outer).ok


def test_cli_refuses_a_plan_with_no_steps(tmp_path):
    p = tmp_path / "empty.py"
    p.write_text("x = 1\n")
    r = subprocess.run([sys.executable, "-m", "claude_verbs", "run", str(p), "--log-dir", str(tmp_path)],
                       capture_output=True, text=True)
    assert r.returncode == 2
    assert "no steps" in (r.stdout + r.stderr)


def test_cli_runs_a_plan_file_that_opens_its_own_plan(tmp_path):
    p = tmp_path / "own.py"
    p.write_text(textwrap.dedent("""
        from claude_verbs import Plan, sh
        with Plan() as plan:
            sh("echo hi")
    """))
    r = subprocess.run([sys.executable, "-m", "claude_verbs", "run", str(p), "--log-dir", str(tmp_path)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "1 ok" in r.stdout
