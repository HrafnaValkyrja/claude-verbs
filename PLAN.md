# claude-verbs: plan

## The goal, not the first step
An agent should spend its turns on thinking, not on shell plumbing. Measured on one agent over 7 days: 5,611 tool calls, of which about 2,000 were bare shell or throwaway inline scripts, and the most common multi-step recipes (ship a change, message a peer, drive a terminal pane, restart a service) took 3 to 10 calls each.

Done means:
1. An agent writes what it wants as one Python file of verbs, runs it once, and reads one short report.
2. A task that took 5 to 15 tool calls takes 1 to 2.
3. Nothing gets less safe: every step is still a plain, logged shell action, failures stop the run, and risky steps are gated by rules in code.
4. Anyone running Claude Code (or any agent with a shell) can install it and write their own verbs.

Measure: tool calls and turns per task, before and after, on real tasks replayed. Also errors per task.

## Scope (all of it, so it doesn't narrow)
- **Core**: step model, runner, report, dry run, stop-on-fail, retries, timeouts, parallel groups, outputs passed between steps, a log of every run.
- **Risk gate**: each verb declares a risk class (safe / care / gated); a site policy file decides what gated steps need (a stated approval, a flag, refusal). Deletes go to a trash, never `rm`.
- **Generic verbs**: `sh`, `edit` (exact replace), `write`, `trash`, `git` family (branch/worktree, commit, push, PR, merge), `ship` (the whole change flow), `unit` (systemd), `job` (long-running in tmux), `http`, `wait_for` (a condition, with timeout), `ask_user` (stops the run with a question).
- **Agent integration**: a Claude Code skill and a short CLAUDE.md snippet that teach the agent to write plans; optionally an MCP tool `run_plan` so the plan goes in one call.
- **Adapters**: separate packages add site verbs (e.g. messaging, panes, status lights, memory). The core never imports them.
- **Learning loop**: the runner notices repeated `sh(...)` patterns across runs and suggests a new verb.
- **Open source hygiene**: license, README with one real example, tests in CI, no site data in the repo.

Not in scope: a new language (it's Python), an LLM in the execution path (a model may only suggest a verb when a line fails to parse).

## Phases
0. **Prior art** (before any code): how others did this: Python task runners and shell libraries (invoke, plumbum, sh, doit, Fabric, just), agent tool-call batching, Claude Code skills/hooks. Take what fits; write down why ours differs.
1. **Core**, test first: step, runner, report, dry run, stop-on-fail, risk gate, run log. Verbs: `sh`, `edit`, `write`, `trash`.
2. **Change flow**: `git` family and `ship`, tested against a throwaway repo.
3. **First site adapter** (kept private): messaging peers, driving agent panes (incl. model switches and dialogs), a hold switch, status lights, memory wrappers, units on several hosts.
4. **Replay**: redo real tasks from the agent's own log as plans (a script fix shipped to two hosts, a model switch, a repo setup). Count calls before/after. This is the proof.
5. **Adoption**: skill + MCP tool; other agents (including smaller models) use it; watch whether their call counts drop.
6. **Public polish**: README example, license, CI, first tagged release.

## Decisions taken
- Python, not a DSL: agents are most fluent in it, and conditions/loops/variables come free.
- Deterministic; no model executes anything.
- Core is generic and public; site verbs are adapters.
- License: MIT (simple, common for tooling).

## Narrowing check
At each phase start, reread "The goal" and "Scope" above and ask: am I building the next phase, or only the next function? If a phase starts to shrink to "just make the test pass", stop and reread.

## From prior art (phase 0, 11-25)
- Build, small. Nothing existing does all of this; the closest (an experimental JS code mode inside one agent) has no dry run, risk classes or report. Use it as a baseline arm in the replay.
- Build then run: verbs create inert steps; `run(plan)` checks policy and dry-runs before anything executes (plumbum's split).
- Dry run is honest: each verb declares whether it can simulate; the report marks "NOT SIMULATED" otherwise (Ansible).
- No plan-time branching on results (pyinfra's trap): conditions on a step's output use lazy references (`when=step.ok`, `step.out`) resolved at run time.
- Fail by default; `ok_codes=` for exceptions. Stop-on-fail needs no flag.
- Resume cheaply: opt-in `creates=` / `unless=` per step, so a rerun skips what's done (doit).
- Policy is a TOML file keyed on risk class, deny beats allow, checked by the runner on run-time values (hooks only see `run plan.py`, so the runner enforces).
- The report is the product: one line per step; full output only for the failing step.
- The skill tells the agent: use a plan for 3+ dependent steps; a single call stays a normal tool call.
- Savings are proved by our own replay, not quoted from others.
- The learning loop proposes verbs; a human or the owning agent decides.
Sources: research notes kept by the maintainer.
