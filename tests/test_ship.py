import json

import pytest

from conftest import git
from claude_verbs import (Plan, StepFailed, commit, copy, pr, push, run, sh, ship,
                          worktree)


def test_worktree_creates_sibling_on_new_branch(repo, fakes):
    with Plan() as plan:
        wt = worktree(repo.work, "feat-x")
    run(plan)
    assert wt.path.parent == repo.work.parent and wt.path != repo.work
    assert git(wt.path, "rev-parse", "--abbrev-ref", "HEAD") == "feat-x"
    assert (wt.path / "app.txt").exists()


def test_worktree_refuses_the_main_checkout(repo):
    with Plan() as plan:
        worktree(repo.work, "feat-x", path=repo.work)
    with pytest.raises(StepFailed) as exc:
        run(plan)
    assert "main checkout" in exc.value.report.results[0].detail


def test_worktree_refuses_the_checked_out_or_base_branch(repo):
    with Plan() as plan:
        worktree(repo.work, "main")
    with pytest.raises(StepFailed):
        run(plan)


def test_commit_push_and_pr_chain(repo, fakes):
    with Plan() as plan:
        wt = worktree(repo.work, "feat-y")
        sh("echo more >> app.txt", cwd=wt.path)
        commit(wt.path, "add more")
        push(wt.path, "feat-y")
        p = pr(wt.path, "Add more", "body text", merge=True)
        sh(p.number.fmt("echo pr={}"))
        done = sh(p.url.fmt("echo {}"))
    run(plan)
    assert "feat-y" in git(repo.bare, "branch", "--list")
    assert git(repo.bare, "log", "-1", "--format=%s", "feat-y") == "add more"
    assert done.result.out.strip() == "https://github.com/acme/widgets/pull/7"
    calls = fakes.lines()
    assert "repos/acme/widgets/pulls -X POST" in calls[0]
    assert "head=feat-y" in calls[0] and "base=main" in calls[0]
    assert "repos/acme/widgets/pulls/7/merge -X PUT" in calls[1]
    assert "merge_method=squash" in calls[1]


def test_commit_with_nothing_to_commit_fails(repo):
    with Plan() as plan:
        wt = worktree(repo.work, "feat-z")
        commit(wt.path, "empty")
    with pytest.raises(StepFailed):
        run(plan)


def test_ship_happy_path_report_has_one_line_per_substep(repo, fakes, env):
    src = env / "extra.txt"
    src.write_text("extra\n")
    (env / "deployed").mkdir()
    target = env / "deployed" / "app.txt"
    with Plan() as plan:
        s = ship(repo.work, "Say goodbye",
                 edits=[("app.txt", "world", "moon")], files={"docs/extra.txt": src},
                 branch="ship-1", deploy=[("app.txt", target, "box")],
                 after=["echo restarted"])
    report = run(plan)
    verbs = [r.verb for r in report.results]
    assert verbs == ["worktree", "edit", "copy", "commit", "push", "pr", "copy", "sh", "worktree"]
    assert all(r.status == "ok" for r in report.results)
    assert all("ship" in r.label for r in report.results)
    assert target.read_text() == "hello\nmoon\n"
    assert not (repo.work.parent / "widgets-ship-1").exists()
    assert git(repo.bare, "show", "ship-1:docs/extra.txt") == "extra"
    assert git(repo.work, "worktree", "list").count("\n") == 0
    assert any("merge" in c for c in fakes.lines())
    assert s.number is not None and "ship" in report.render()


def test_ship_failing_edit_stops_before_commit_and_cleans_up(repo, fakes):
    with Plan() as plan:
        ship(repo.work, "Bad edit", edits=[("app.txt", "nonexistent", "x")], branch="ship-2")
    with pytest.raises(StepFailed) as exc:
        run(plan)
    by_verb = {r.verb: r.status for r in exc.value.report.results}
    assert by_verb["edit"] == "failed"
    statuses = [(r.verb, r.status) for r in exc.value.report.results]
    assert ("commit", "skipped") in statuses and ("push", "skipped") in statuses
    assert statuses[-1] == ("worktree", "ok")  # the cleanup still ran
    assert not (repo.work.parent / "widgets-ship-2").exists()
    assert fakes.lines() == []
    assert "ship-2" not in git(repo.bare, "branch", "--list")


def test_ship_dry_run_shows_whole_chain_and_changes_nothing(repo, fakes, env):
    with Plan() as plan:
        ship(repo.work, "Dry", edits=[("app.txt", "world", "moon")], branch="ship-3",
             deploy=[("app.txt", env / "out.txt", "box")], after=["echo done"])
    report = run(plan, dry=True)
    assert [r.verb for r in report.results] == [
        "worktree", "edit", "commit", "push", "pr", "copy", "sh", "worktree"]
    statuses = {r.verb: r.status for r in report.results}
    assert statuses["edit"] == "ok" and statuses["sh"] == "not-simulated"
    assert not (repo.work.parent / "widgets-ship-3").exists()
    assert "ship-3" not in git(repo.work, "branch", "--list")
    assert fakes.lines() == [] and not (env / "out.txt").exists()


def test_ship_is_care_risk(repo):
    with Plan() as plan:
        ship(repo.work, "r", edits=[("app.txt", "hello", "hi")])
    assert {s.risk for s in plan.steps} == {"care"}
