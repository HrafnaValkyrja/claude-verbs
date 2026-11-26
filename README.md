# claude-verbs

Write what you want done as one Python file of verbs. The runner executes it top to bottom as checked shell steps, stops at the first failure, and hands back one compact report.

Built for agent sessions that spend most of their turns on shell plumbing: one plan, one run, one report.

Status: v0.1.0. Core, remote hosts, git change flow, `ship`, risk policy, run log. See [PLAN.md](PLAN.md) and [CHANGELOG.md](CHANGELOG.md).

## Install

    pip install .            # Python >= 3.10, no runtime dependencies on 3.11+

## Example

`plan.py`:

```python
from claude_verbs import sh, write, edit

write("app.conf", "port = 8080\n", creates="app.conf")   # skipped on a rerun
edit("app.conf", "8080", "9090")                          # old text must occur exactly once
size = sh("wc -c app.conf")
sh(size.out.map(str.split).map(lambda p: p[0]).fmt("echo size={}"))  # lazy: resolved at run time
sh("grep -q 7070 app.conf")                               # fails, so the run stops here
sh("echo never runs")
```

    $ claude-verbs run plan.py          # or: python3 -m claude_verbs run plan.py

```
run d6612395: 4 ok, 1 failed, 1 skipped
 1 ok            write app.conf  (0.00s)
 2 ok            edit app.conf  (0.00s)
 3 ok            sh wc -c app.conf  (0.00s)
 4 ok            sh echo size=12  (0.00s)
 5 failed        sh grep -q 7070 app.conf  (0.00s)  - exit 1
 6 skipped       sh echo never runs  (0.00s)  - not reached
```

`--verbose` (`run(..., verbose=True)`) shows every ok step's output; by default only failed steps print theirs.

Exit code: 0 ok, 1 a step failed, 2 policy denied or bad input. Add `--dry` to simulate: verbs that can simulate (`edit`, `write`, `copy`, `trash`, git verbs) check their preconditions and change nothing; the rest are reported `not-simulated`, never "ok".

## Interface

```python
Plan(steps=None)                          # context manager; steps made inside are collected
run(plan, dry=False, *, policy=None, log_dir=None, raise_on_fail=True) -> Report
sh(cmd, cwd=None, env=None, host=None, *, timeout=300, connect_timeout=10, **opts)
                                          # host=: over ssh -o BatchMode=yes, cwd/env shell-quoted
copy(src, dest, host=None, **opts)        # local copy, or scp to host:dest (plain remote paths only)
edit(path, old, new, **opts)              # exact, unique replace
write(path, text, **opts)                 # atomic; creates parent dirs
trash(path, **opts)                       # to the trash dir; step output is an item id
restore(item_id, trash_directory=None)    # put it back, never overwrites
worktree(repo, branch, base="origin/main", path=None)   # sibling worktree; refuses the main checkout
commit(path, message, author=None, all=True)
push(path, branch)
pr(repo_path, title, body="", base="main", merge=False, method="squash")  # gh REST; lazy .number .url
ship(repo, reason, edits=(), files=None, branch=None, base="main", merge=True,
     deploy=(), after=(), cleanup=True)   # the whole chain, one report line per stage
```

Options on every verb: `risk="safe|care|gated"`, `approval="why"`, `when=`, `creates=`, `unless=`, `ok_codes=(0,)` (for `sh`), `show=True` (print this step's output even when it succeeded), `retries=N` with `retry_delay=` seconds, `timeout=` (default 300s; `run(..., default_timeout=)` changes the default for custom steps). A later step can use an earlier step's `.ok`, `.out`, `.err`, `.code` as a lazy reference (`.map(fn)`, `.fmt("..{}..")`); using one in `if` or an f-string at plan time raises, because the value does not exist yet.

## Ship a change

```python
from claude_verbs import ship
ship("~/code/widgets", "Say moon, not world",
     edits=[("app.txt", "world", "moon")],
     deploy=[("app.txt", "/srv/app/app.txt", "web1")],   # (file in repo, dest, host or None)
     after=["echo restarted"])
```

```
run 3f9a1c20: 8 ok
 1 ok            [ship] worktree add /code/widgets-ship-say-moon-not-world-a1b2c3 ...
 2 ok            [ship] edit /code/widgets-ship-say-moon-not-world-a1b2c3/app.txt
 3 ok            [ship] commit /code/widgets-ship-say-moon-not-world-a1b2c3 Say moon, not world
 4 ok            [ship] push /code/widgets-ship-say-moon-not-world-a1b2c3 ship/say-moon-not-world-a1b2c3
 5 ok            [ship] pr /code/widgets-ship-say-moon-not-world-a1b2c3 Say moon, not world
 6 ok            [ship] copy /code/widgets-ship-say-moon-not-world-a1b2c3/app.txt web1:/srv/app/app.txt
 7 ok            [ship] sh echo restarted
 8 ok            [ship] worktree remove /code/widgets-ship-say-moon-not-world-a1b2c3
```

(timings trimmed). If a stage fails, later stages are `skipped` but the worktree removal still runs. `--dry` shows the same chain; `edit` and `copy` are checked against the files earlier steps would create, and `after` commands are `not-simulated`.

## Measured: four real tasks, replayed

Four changes an agent had made by hand in one day (a script fix shipped to two hosts; a stale-row fix shipped and checked on two hosts; two long-running agents switched to another model through their terminal panes; a config file plus a code change with a live check) were rewritten as plans of 19 to 32 lines and run end to end against a throwaway repository with fake `ssh`, `scp` and `gh` (nothing live touched).

| | by hand | as plans |
|---|---|---|
| tool calls, all four tasks | 37 | 21 (17 without a separate `--dry` pass) |
| of which reading code to find the cause | 13 | 13 |
| mechanical calls (worktree, edit, commit, push, PR, merge, deploy, verify, message) | 24 | 8 |

A plan removes plumbing, not thinking: the reading stays. Each plan run gave one report of 12 to 18 lines.

## Risk policy

Each step has a risk class. A TOML file (`--policy`, `policy=`, or `$CLAUDE_VERBS_POLICY`; built-in default otherwise) says what each class needs and adds regex rules over the step's command or path:

```toml
[classes]
gated = "approval"        # allow | approval | deny

[[rules]]
action = "deny"           # deny always wins
verb = "sh"               # optional
match = "curl .*\\| *sh"
```

Order: any deny wins; then approval rules; then allow rules (waive a class's approval); then the class. `approval="..."` on a step satisfies "approval". Checked once before anything runs and again on each step's run-time values. Deletes go through `trash`; the default policy denies `rm -r`/`rm -f`.

## Logs

Every run appends JSONL to `~/.local/state/claude-verbs/runs/` (override: `log_dir=`, `--log-dir`, `$CLAUDE_VERBS_LOG_DIR`).

## Layout
- `claude_verbs/core.py`: steps, lazy references, runner, report
- `claude_verbs/policy.py`: risk policy
- `claude_verbs/runlog.py`: JSONL run log
- `claude_verbs/verbs.py`: generic verbs (`sh`, `copy`, `edit`, `write`, `trash`)
- `claude_verbs/cli.py`: command line
- site adapters: separate packages with verbs for one deployment; the core never imports them

## Tests

    pip install pytest && pytest
