import subprocess
import sys


def cli(env, *args):
    import os

    e = dict(os.environ, CLAUDE_VERBS_LOG_DIR=str(env / "runs"),
             CLAUDE_VERBS_TRASH=str(env / "trash"))
    e.pop("CLAUDE_VERBS_POLICY", None)
    return subprocess.run(
        [sys.executable, "-m", "claude_verbs", *args],
        capture_output=True, text=True, env=e, timeout=30,
    )


def test_cli_runs_plan_file_and_prints_report(env):
    plan = env / "plan.py"
    plan.write_text("from claude_verbs import sh\nsh('echo from-cli')\n")
    r = cli(env, "run", str(plan))
    assert r.returncode == 0
    assert "sh echo from-cli" in r.stdout


def test_cli_exit_code_one_on_failure(env):
    plan = env / "plan.py"
    plan.write_text("from claude_verbs import sh\nsh('exit 4')\n")
    r = cli(env, "run", str(plan))
    assert r.returncode == 1
    assert "failed" in r.stdout


def test_cli_dry_flag(env):
    plan = env / "plan.py"
    marker = env / "m"
    plan.write_text(f"from claude_verbs import sh\nsh('touch {marker}')\n")
    r = cli(env, "run", str(plan), "--dry")
    assert r.returncode == 0
    assert "not-simulated" in r.stdout
    assert not marker.exists()


def test_cli_policy_flag_denies_with_exit_two(env):
    plan = env / "plan.py"
    plan.write_text("from claude_verbs import sh\nsh('echo bad')\n")
    pol = env / "p.toml"
    pol.write_text('[[rules]]\naction="deny"\nmatch="bad"\n')
    r = cli(env, "run", str(plan), "--policy", str(pol))
    assert r.returncode == 2
    assert "denied" in (r.stdout + r.stderr).lower()
