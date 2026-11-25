import json

import pytest

from claude_verbs import Plan, StepFailed, run, sh, write


def test_runs_steps_in_order_and_reports_one_line_each(env):
    with Plan() as plan:
        sh("echo one")
        sh("echo two")
    report = run(plan)
    assert [r.status for r in report.results] == ["ok", "ok"]
    lines = str(report).splitlines()
    assert sum("sh echo" in line for line in lines) == 2


def test_steps_are_inert_until_run(env):
    target = env / "made.txt"
    with Plan() as plan:
        write(target, "x")
    assert not target.exists()
    run(plan)
    assert target.read_text() == "x"


def test_stops_on_first_failure_and_raises(env):
    marker = env / "never"
    with Plan() as plan:
        sh("exit 3")
        sh(f"touch {marker}")
    with pytest.raises(StepFailed) as exc:
        run(plan)
    assert not marker.exists()
    statuses = [r.status for r in exc.value.report.results]
    assert statuses == ["failed", "skipped"]
    assert exc.value.report.results[0].code == 3


def test_ok_codes_accept_nonzero(env):
    with Plan() as plan:
        sh("exit 1", ok_codes=(0, 1))
        sh("echo after")
    report = run(plan)
    assert [r.status for r in report.results] == ["ok", "ok"]


def test_raise_can_be_turned_off(env):
    with Plan() as plan:
        sh("false")
    report = run(plan, raise_on_fail=False)
    assert not report.ok


def test_report_shows_full_output_only_for_failing_step(env):
    with Plan() as plan:
        sh("printf 'PASSING-%s' OUTPUT")
        sh("echo FAILING-OUTPUT; echo boom >&2; exit 2")
    report = run(plan, raise_on_fail=False)
    text = str(report)
    assert "FAILING-OUTPUT" in text and "boom" in text
    assert "PASSING-OUTPUT" not in text


def test_timeout_kills_step(env):
    with Plan() as plan:
        sh("sleep 5", timeout=0.3)
    report = run(plan, raise_on_fail=False)
    assert report.results[0].status == "failed"
    assert "timed out" in report.results[0].detail
    assert report.results[0].duration < 3


def test_lazy_reference_passes_output_to_later_step(env):
    with Plan() as plan:
        first = sh("echo hello")
        sh(first.out.map(str.strip).fmt("echo got-{}"))
    report = run(plan)
    assert report.results[1].out.strip() == "got-hello"


def test_when_ref_skips_on_run_time_value(env):
    with Plan() as plan:
        bad = sh("exit 1", ok_codes=(0, 1))
        sh("echo cond", when=bad.code.map(lambda c: c == 0))
        sh("echo yes", when=bad.code.map(lambda c: c == 1))
    report = run(plan)
    assert [r.status for r in report.results] == ["ok", "skipped", "ok"]


def test_plan_time_truthiness_of_a_reference_is_an_error(env):
    with Plan():
        first = sh("echo hi")
        with pytest.raises(TypeError):
            if first.ok:
                pass
        with pytest.raises(TypeError):
            f"{first.out}"


def test_creates_skips_when_path_exists(env):
    present = env / "present"
    present.write_text("")
    with Plan() as plan:
        sh(f"touch {env / 'ran'}", creates=present)
    report = run(plan)
    assert report.results[0].status == "skipped"
    assert not (env / "ran").exists()


def test_creates_runs_when_path_missing(env):
    out = env / "out"
    with Plan() as plan:
        sh(f"touch {out}", creates=out)
    run(plan)
    assert out.exists()
    # a second run is a no-op
    report = run(plan)
    assert report.results[0].status == "skipped"


def test_unless_skips_when_probe_succeeds(env):
    with Plan() as plan:
        sh(f"touch {env / 'ran'}", unless="true")
        sh(f"touch {env / 'ran2'}", unless="false")
    report = run(plan)
    assert [r.status for r in report.results] == ["skipped", "ok"]
    assert not (env / "ran").exists() and (env / "ran2").exists()


def test_dry_run_changes_nothing_and_is_honest(env):
    from claude_verbs import edit

    target = env / "f.txt"
    target.write_text("alpha")
    marker = env / "marker"
    with Plan() as plan:
        edit(target, "alpha", "beta")
        sh(f"touch {marker}")
    report = run(plan, dry=True)
    assert target.read_text() == "alpha"
    assert not marker.exists()
    assert [r.status for r in report.results] == ["ok", "not-simulated"]
    assert "not-simulated" in str(report)
    assert report.dry


def test_dry_run_marks_steps_depending_on_unknown_output(env):
    with Plan() as plan:
        first = sh("echo x")
        write(env / "o.txt", first.out)
    report = run(plan, dry=True)
    assert [r.status for r in report.results] == ["not-simulated", "not-simulated"]
    assert not (env / "o.txt").exists()


def test_run_log_is_jsonl(env):
    with Plan() as plan:
        sh("echo logged")
    report = run(plan)
    lines = [json.loads(x) for x in report.log_path.read_text().splitlines()]
    kinds = [x["event"] for x in lines]
    assert kinds[0] == "run_start" and kinds[-1] == "run_end"
    assert any(x["event"] == "step" and x["status"] == "ok" for x in lines)
    assert report.log_path.parent == env / "runs"


def test_log_dir_argument_wins(env):
    with Plan() as plan:
        sh("true")
    report = run(plan, log_dir=env / "elsewhere")
    assert report.log_path.parent == env / "elsewhere"
