import pytest

from claude_verbs import Plan, PolicyDenied, Policy, run, sh


def policy_file(tmp_path, text):
    p = tmp_path / "policy.toml"
    p.write_text(text)
    return p


def test_default_policy_requires_approval_for_gated(env):
    marker = env / "ran"
    with Plan() as plan:
        sh(f"touch {marker}", risk="gated")
    with pytest.raises(PolicyDenied):
        run(plan)
    assert not marker.exists()


def test_approval_string_satisfies_gate(env):
    marker = env / "ran"
    with Plan() as plan:
        sh(f"touch {marker}", risk="gated", approval="reviewed by owner")
    run(plan)
    assert marker.exists()


def test_empty_approval_does_not_count(env):
    with Plan() as plan:
        sh("true", risk="gated", approval="  ")
    with pytest.raises(PolicyDenied):
        run(plan)


def test_denied_plan_runs_nothing_even_earlier_steps(env):
    marker = env / "first"
    pol = policy_file(env, '[[rules]]\naction="deny"\nmatch="forbidden"\n')
    with Plan() as plan:
        sh(f"touch {marker}")
        sh("echo forbidden")
    with pytest.raises(PolicyDenied):
        run(plan, policy=pol)
    assert not marker.exists()


def test_deny_beats_allow_and_approval(env):
    pol = policy_file(
        env,
        '[[rules]]\naction="allow"\nmatch="danger"\n'
        '[[rules]]\naction="deny"\nmatch="danger"\n',
    )
    with Plan() as plan:
        sh("echo danger", approval="yes please")
    with pytest.raises(PolicyDenied):
        run(plan, policy=pol)


def test_class_deny_cannot_be_waived_by_allow_rule(env):
    pol = policy_file(
        env,
        '[classes]\ngated="deny"\n[[rules]]\naction="allow"\nmatch=".*"\n',
    )
    with Plan() as plan:
        sh("true", risk="gated", approval="x")
    with pytest.raises(PolicyDenied):
        run(plan, policy=pol)


def test_policy_checks_run_time_values(env):
    pol = policy_file(env, '[[rules]]\naction="deny"\nmatch="secret"\n')
    marker = env / "second"
    with Plan() as plan:
        first = sh("printf 'sec%s' ret")
        sh(first.out.map(str.strip).fmt("echo {}"))
        sh(f"touch {marker}")
    with pytest.raises(PolicyDenied) as exc:
        run(plan, policy=pol)
    # the first step is allowed (its text has no match); the second is denied
    # only once its value is known, and nothing after it runs
    statuses = [r.status for r in exc.value.report.results]
    assert statuses[0] == "ok" and statuses[1] == "failed"
    assert not marker.exists()


def test_policy_path_from_environment(env, monkeypatch):
    pol = policy_file(env, '[[rules]]\naction="deny"\nmatch="nope"\n')
    monkeypatch.setenv("CLAUDE_VERBS_POLICY", str(pol))
    with Plan() as plan:
        sh("echo nope")
    with pytest.raises(PolicyDenied):
        run(plan)


def test_builtin_default_denies_recursive_rm(env):
    with Plan() as plan:
        sh("rm -rf /tmp/whatever")
    with pytest.raises(PolicyDenied):
        run(plan)


def test_invalid_policy_action_is_rejected(env):
    pol = policy_file(env, '[[rules]]\naction="maybe"\nmatch="x"\n')
    with pytest.raises(ValueError):
        Policy.load(pol)
