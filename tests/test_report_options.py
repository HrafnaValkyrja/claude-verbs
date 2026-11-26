import pytest

from claude_verbs import Outcome, Plan, Step, StepFailed, run, sh
from claude_verbs.cli import main


def test_show_prints_ok_step_output_under_its_line(env):
    with Plan() as plan:
        sh("echo hello-out", show=True)
        sh("echo hidden-out")
    text = str(run(plan))
    assert "| hello-out" in text
    assert "| hidden-out" not in text


def test_run_verbose_shows_every_ok_step(env):
    with Plan() as plan:
        sh("echo aaa")
        sh("echo bbb")
    text = run(plan, verbose=True).render()
    assert "| aaa" in text and "| bbb" in text


def test_shown_output_is_tailed(env):
    with Plan() as plan:
        sh("seq 1 500", show=True)
    text = str(run(plan))
    assert "| 500" in text and "| 1\n" not in text and "earlier lines" in text


def test_retries_until_it_passes(env):
    marker = env / "n"
    cmd = f"echo x >> {marker}; [ $(wc -l < {marker}) -ge 3 ]"
    with Plan() as plan:
        sh(cmd, retries=2, retry_delay=0)
    report = run(plan)
    assert report.results[0].status == "ok"
    assert "after 3 tries" in report.results[0].detail


def test_retries_give_up_and_fail(env):
    with Plan() as plan:
        sh("exit 4", retries=1, retry_delay=0)
    with pytest.raises(StepFailed) as e:
        run(plan)
    r = e.value.report.results[0]
    assert r.code == 4 and "after 2 tries" in r.detail


def test_no_retry_by_default(env):
    marker = env / "n"
    with Plan() as plan:
        sh(f"echo x >> {marker}; exit 1")
    with pytest.raises(StepFailed):
        run(plan)
    assert len(marker.read_text().splitlines()) == 1


def test_custom_step_gets_the_default_timeout(env):
    seen = []
    def do(a, t):
        seen.append(t)
        return "ok"
    with Plan() as plan:
        Step("mine", do, {})
        Step("mine", do, {}, timeout=5)
    run(plan, default_timeout=42)
    assert seen == [42, 5]


def test_sh_keeps_its_own_timeout(env):
    with Plan() as plan:
        sh("sleep 5", timeout=0.2)
    with pytest.raises(StepFailed) as e:
        run(plan, default_timeout=300)
    assert "timed out" in e.value.report.results[0].detail.lower() or e.value.report.results[0].code != 0


def test_cli_verbose_flag(env, tmp_path, capsys):
    p = tmp_path / "plan.py"
    p.write_text("from claude_verbs import sh\nsh('echo viaflag')\n")
    assert main(["run", str(p), "--verbose"]) == 0
    assert "| viaflag" in capsys.readouterr().out
