"""Steps, plans, lazy references and the runner.

PURPOSE: build inert steps, then run them with policy checks, stop-on-fail,
         dry mode, a compact report and a run log.
WHY: one plan, one run, one report instead of many shell tool calls.
REFS: PLAN.md "From prior art" (build-then-run, honest dry run, lazy refs).
LOGS: see claude_verbs.runlog.
READS-BY: claude_verbs.verbs, claude_verbs.cli
"""
from __future__ import annotations

import contextvars
import os
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .policy import Decision, Policy
from .runlog import RunLog

_active: contextvars.ContextVar["Plan | None"] = contextvars.ContextVar("plan", default=None)
TAIL_LINES = 200


class RunError(Exception):
    def __init__(self, report: "Report", message: str | None = None):
        self.report = report
        super().__init__(message or str(report))


class StepFailed(RunError):
    pass


class PolicyDenied(RunError):
    pass


class RefUnavailable(Exception):
    """A lazy reference points at a value that does not exist (yet)."""


class Ref:
    """A value that exists only at run time (a field of an earlier step).

    Plan-time use as a bool or in an f-string is an error: branching on a
    result while building the plan is the trap lazy references avoid.
    """

    def __init__(self, resolver: Callable[[], Any], desc: str):
        self._resolver, self._desc = resolver, desc

    def resolve(self):
        return self._resolver()

    def map(self, fn: Callable[[Any], Any]) -> "Ref":
        return Ref(lambda: fn(self.resolve()), f"{self._desc}.map()")

    def fmt(self, template: str) -> "Ref":
        return self.map(lambda v: template.format(v))

    def _plan_time(self, *_):
        raise TypeError(
            f"{self!r} is only known at run time; use .map(fn) / .fmt('..{{}}..'), "
            "or pass it as an argument or when=, instead of testing or formatting it"
        )

    __bool__ = __str__ = __format__ = _plan_time

    def __repr__(self):
        return f"<Ref {self._desc}>"


def _resolve(v):
    if isinstance(v, Ref):
        return v.resolve()
    if isinstance(v, (list, tuple)):
        return type(v)(_resolve(x) for x in v)
    if isinstance(v, dict):
        return {k: _resolve(x) for k, x in v.items()}
    return v


@dataclass
class Outcome:
    code: int = 0
    out: str = ""
    err: str = ""
    detail: str = ""


@dataclass
class StepResult:
    index: int
    label: str
    verb: str
    status: str  # ok | failed | skipped | not-simulated
    code: int | None = None
    out: str = ""
    err: str = ""
    detail: str = ""
    duration: float = 0.0
    dry: bool = False


class Step:
    """One inert action. Nothing happens until run().

    do(args, timeout) -> Outcome | str | None executes it; simulate(args) -> str
    describes it without side effects (None means "cannot simulate");
    subject(args) -> str is the text policy rules match against.
    """

    def __init__(self, verb: str, do: Callable, args: dict | None = None, *,
                 risk: str = "care", simulate: Callable | None = None,
                 subject: Callable | None = None, when=None, creates=None,
                 unless=None, approval=None, timeout: float | None = None,
                 ok_codes=(0,)):
        if risk not in ("safe", "care", "gated"):
            raise ValueError(f"risk must be safe|care|gated, not {risk!r}")
        self.verb, self.risk, self.args = verb, risk, args or {}
        self._do, self._simulate = do, simulate
        self._subject = subject or (lambda a: " ".join(str(v) for v in a.values()))
        self.when, self.creates, self.unless = when, creates, unless
        self.approval, self.timeout, self.ok_codes = approval, timeout, tuple(ok_codes)
        self.result: StepResult | None = None
        self.can_simulate = simulate is not None
        plan = _active.get()
        if plan is not None:
            plan.steps.append(self)

    # lazy references to this step's run-time outcome
    def _field(self, name: str, live_only: bool) -> Ref:
        def get():
            r = self.result
            if r is None or r.status == "not-simulated":
                raise RefUnavailable(f"{self.verb} step has no value for {name}")
            if live_only and r.dry:
                raise RefUnavailable(f"{self.verb} step was only simulated; no {name}")
            return {"ok": r.status == "ok", "code": r.code, "out": r.out, "err": r.err}[name]
        return Ref(get, f"{self.verb}#{name}")

    @property
    def ok(self) -> Ref:
        return self._field("ok", False)

    @property
    def out(self) -> Ref:
        return self._field("out", True)

    @property
    def err(self) -> Ref:
        return self._field("err", True)

    @property
    def code(self) -> Ref:
        return self._field("code", True)

    def label(self, args: dict | None = None) -> str:
        try:
            text = self._subject(args if args is not None else _resolve(self.args))
        except Exception:
            text = "..."
        text = " ".join(str(text).split())
        return f"{self.verb} {text[:60] + ('...' if len(text) > 60 else '')}".strip()

    def __repr__(self):
        return f"<Step {self.label()}>"


class Plan:
    """An ordered list of steps; also a context manager that collects steps
    created inside it (the CLI wraps plan files in one)."""

    def __init__(self, steps=None):
        self.steps: list[Step] = list(steps or [])
        self._token = None

    def __enter__(self):
        self._outer = _active.get(None)
        self._token = _active.set(self)
        return self

    def __exit__(self, *exc):
        _active.reset(self._token)
        # A plan opened inside another (e.g. a plan file that opens its own Plan under the CLI's)
        # is a group of the outer one, never a second plan that silently doesn't run.
        if self._outer is not None:
            self._outer.steps.extend(self.steps)


@dataclass
class Report:
    run_id: str
    dry: bool
    results: list[StepResult] = field(default_factory=list)
    log_path: Path | None = None

    @property
    def ok(self) -> bool:
        return all(r.status != "failed" for r in self.results)

    def render(self) -> str:
        counts: dict[str, int] = {}
        for r in self.results:
            counts[r.status] = counts.get(r.status, 0) + 1
        head = (f"run {self.run_id}{' (dry)' if self.dry else ''}: "
                + ", ".join(f"{n} {s}" for s, n in counts.items()))
        lines = [head]
        for r in self.results:
            line = f"{r.index:>2} {r.status:<13} {r.label}  ({r.duration:.2f}s)"
            if r.detail:
                line += f"  - {r.detail}"
            lines.append(line)
            if r.status == "failed":
                text = "\n".join(x for x in (r.out.rstrip(), r.err.rstrip()) if x)
                tail = text.splitlines()
                if len(tail) > TAIL_LINES:
                    lines.append(f"   | ... {len(tail) - TAIL_LINES} earlier lines in the run log")
                    tail = tail[-TAIL_LINES:]
                lines += [f"   | {x}" for x in tail]
        return "\n".join(lines)

    __str__ = render


def _approved(approval) -> bool:
    return isinstance(approval, str) and bool(approval.strip())


def _gate(policy: Policy, step: Step, args: dict | None, approval) -> str | None:
    """Returns a refusal message, or None when the step may run."""
    subject = None
    if args is not None:
        try:
            subject = step._subject(args)
        except Exception:
            subject = None
    d: Decision = policy.check(step.verb, step.risk, subject)
    if d.action == "deny":
        return f"policy denied: {d.reason}"
    if d.action == "approval" and not _approved(approval):
        return f'policy needs approval="...": {d.reason}'
    return None


def _static(step: Step):
    """Args and approval if they hold no run-time references, else (None, ref)."""
    try:
        return _resolve(step.args), _resolve(step.approval)
    except RefUnavailable:
        return None, step.approval


def run(plan, dry: bool = False, *, policy=None, log_dir=None,
        raise_on_fail: bool = True) -> Report:
    """Run a Plan (or list of Steps). Policy is checked on every step before
    anything executes (class level, plus values known at plan time) and again
    on each step's run-time values. First failure stops the run."""
    steps = list(plan.steps if isinstance(plan, Plan) else plan)
    pol = Policy.resolve(policy)
    for s in steps:
        s.result = None
    run_id = uuid.uuid4().hex[:8]
    report = Report(run_id, dry)

    for i, s in enumerate(steps, 1):
        args, approval = _static(s)
        refusal = _gate(pol, s, args, approval if args is not None else "deferred")
        if refusal:
            report.results.append(StepResult(i, s.label(args), s.verb, "failed", detail=refusal))
            raise PolicyDenied(report, f"{refusal} (step {i}: {s.label(args)}); nothing was run")
    report.results.clear()

    log = RunLog(run_id, log_dir)
    report.log_path = log.path
    log.event("run_start", dry=dry, steps=len(steps))
    failure: type[RunError] | None = None

    def record(i, s, status, t0, args=None, outcome: Outcome | None = None, detail="", code=None):
        o = outcome or Outcome()
        r = StepResult(i, s.label(args), s.verb, status,
                       code=o.code if outcome else code, out=o.out, err=o.err,
                       detail=detail or o.detail, duration=time.monotonic() - t0, dry=dry)
        s.result = r
        report.results.append(r)
        log.event("step", index=i, verb=s.verb, label=r.label, status=status, code=r.code,
                  out=r.out, err=r.err, detail=r.detail, duration=round(r.duration, 3))
        return r

    for i, s in enumerate(steps, 1):
        if failure:
            record(i, s, "skipped", time.monotonic(), detail="not reached")
            continue
        t0 = time.monotonic()
        try:
            cond = s.when() if callable(s.when) else _resolve(s.when)
            if s.when is not None and not cond:
                record(i, s, "skipped", t0, detail="when is false")
                continue
            creates = _resolve(s.creates)
            if creates is not None and Path(creates).exists():
                record(i, s, "skipped", t0, detail=f"creates: {creates} exists")
                continue
            args = _resolve(s.args)
            approval = _resolve(s.approval)
        except RefUnavailable as e:
            if dry:
                record(i, s, "not-simulated", t0, detail=f"depends on a run-time value ({e})")
            else:
                failure = StepFailed
                record(i, s, "failed", t0, detail=str(e))
            continue
        refusal = _gate(pol, s, args, approval)
        if refusal:
            failure = PolicyDenied
            record(i, s, "failed", t0, args, detail=refusal)
            continue
        if dry:
            if s._simulate is None:
                record(i, s, "not-simulated", t0, args, detail="verb cannot simulate")
                continue
            try:
                record(i, s, "ok", t0, args, detail=f"would: {s._simulate(args)}", code=0)
            except Exception as e:
                failure = StepFailed
                record(i, s, "failed", t0, args, detail=f"dry: {e}")
            continue
        if s.unless is not None:
            probe = subprocess.run(_resolve(s.unless), shell=True, capture_output=True)
            if probe.returncode == 0:
                record(i, s, "skipped", t0, args, detail="unless: probe succeeded")
                continue
        try:
            res = s._do(args, s.timeout)
            o = res if isinstance(res, Outcome) else Outcome(0, res or "")
            if o.code in s.ok_codes:
                record(i, s, "ok", t0, args, o)
            else:
                failure = StepFailed
                record(i, s, "failed", t0, args, o, detail=o.detail or f"exit {o.code}")
        except Exception as e:
            failure = StepFailed
            record(i, s, "failed", t0, args, detail=str(e) or type(e).__name__)

    log.event("run_end", ok=report.ok)
    if failure and raise_on_fail:
        raise failure(report)
    return report
