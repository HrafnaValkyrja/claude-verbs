# claude-verbs

Write what you want done as one Python file of verbs. The runner executes it top to bottom as checked shell steps, stops at the first failure, and hands back one compact report.

Built for agent sessions that spend most of their turns on shell plumbing: one plan, one run, one report.

Status: design.

## Layout (planned)
- `hive/core.py`: steps, stop-on-fail, report, risk gate, dry mode
- `hive/run.py`: `python3 -m hive.run plan.py [--dry]`
- `hive/verbs/`: generic verbs (sh, edit, trash, git/ship, unit, job)
- site adapters: separate packages with verbs for one deployment (hosts, nodes, limits)

Generic core; site-specific verbs live in adapters, not the core.
