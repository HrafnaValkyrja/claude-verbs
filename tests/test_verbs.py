import pytest

from claude_verbs import Plan, StepFailed, edit, restore, run, trash, write


def test_edit_replaces_exactly_one_occurrence(env):
    f = env / "a.txt"
    f.write_text("one two three")
    with Plan() as plan:
        edit(f, "two", "2")
    run(plan)
    assert f.read_text() == "one 2 three"


def test_edit_fails_when_old_text_is_ambiguous(env):
    f = env / "a.txt"
    f.write_text("x x")
    with Plan() as plan:
        edit(f, "x", "y")
    with pytest.raises(StepFailed) as exc:
        run(plan)
    assert "2 times" in exc.value.report.results[0].detail
    assert f.read_text() == "x x"


def test_edit_fails_when_old_text_missing(env):
    f = env / "a.txt"
    f.write_text("abc")
    with Plan() as plan:
        edit(f, "zzz", "y")
    with pytest.raises(StepFailed):
        run(plan)


def test_dry_edit_reports_uniqueness_failure(env):
    f = env / "a.txt"
    f.write_text("x x")
    with Plan() as plan:
        edit(f, "x", "y")
    report = run(plan, dry=True, raise_on_fail=False)
    assert report.results[0].status == "failed"
    assert f.read_text() == "x x"


def test_write_creates_parents_and_overwrites(env):
    f = env / "deep" / "dir" / "n.txt"
    with Plan() as plan:
        write(f, "first")
        write(f, "second")
    run(plan)
    assert f.read_text() == "second"


def test_trash_moves_file_and_restore_puts_it_back(env):
    f = env / "keep.txt"
    f.write_text("precious")
    with Plan() as plan:
        step = trash(f)
    report = run(plan)
    assert not f.exists()
    item = report.results[0].out.strip()
    assert item
    assert restore(item) == f
    assert f.read_text() == "precious"


def test_trash_handles_directories(env):
    d = env / "dir"
    d.mkdir()
    (d / "x").write_text("1")
    with Plan() as plan:
        trash(d)
    report = run(plan)
    assert not d.exists()
    restore(report.results[0].out.strip())
    assert (d / "x").read_text() == "1"


def test_restore_refuses_to_overwrite(env):
    f = env / "k.txt"
    f.write_text("a")
    with Plan() as plan:
        trash(f)
    item = run(plan).results[0].out.strip()
    f.write_text("new")
    with pytest.raises(FileExistsError):
        restore(item)
    assert f.read_text() == "new"


def test_trash_missing_path_fails(env):
    with Plan() as plan:
        trash(env / "nope")
    with pytest.raises(StepFailed):
        run(plan)
