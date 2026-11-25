"""Risk policy: maps a step's risk class and run-time subject to allow / approval / deny.

PURPOSE: decide, before a step executes, whether it may run.
WHY: hooks only see "run plan.py"; the runner sees each step's real values.
REFS: PLAN.md "Risk gate".
READS-BY: claude_verbs.core.run
"""
from __future__ import annotations

import os
import re
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib
from dataclasses import dataclass
from pathlib import Path

ACTIONS = ("allow", "approval", "deny")
RISKS = ("safe", "care", "gated")

DEFAULT = {
    "classes": {"safe": "allow", "care": "allow", "gated": "approval"},
    "rules": [
        # Deletes go to the trash verb, never rm -r / rm -f.
        {"action": "deny", "verb": "sh", "match": r"(^|[;&|(]\s*)rm\s+-\w*[rRf]"},
        {"action": "approval", "verb": "sh", "match": r"\bgit\s+push\b.*(--force|-f\b)"},
        {"action": "approval", "verb": "sh", "match": r"(^|[;&|(]\s*)sudo\b"},
    ],
}


@dataclass(frozen=True)
class Decision:
    action: str  # allow | approval | deny
    reason: str


class Policy:
    """Class-level defaults plus regex rules over a step's subject text.

    Precedence: any deny (class or rule) wins; then an approval rule; then an
    allow rule (waives a class-level approval); then the class action.
    """

    def __init__(self, data: dict | None = None):
        data = DEFAULT if data is None else data
        classes = {**DEFAULT["classes"], **data.get("classes", {})}
        for risk, action in classes.items():
            if risk not in RISKS:
                raise ValueError(f"unknown risk class {risk!r}")
            if action not in ACTIONS:
                raise ValueError(f"bad action {action!r} for class {risk!r}")
        rules = list(data.get("rules", []))
        for r in rules:
            if r.get("action") not in ACTIONS:
                raise ValueError(f"bad rule action {r.get('action')!r}")
            re.compile(r["match"])
        self.classes, self.rules = classes, rules

    @classmethod
    def default(cls) -> "Policy":
        return cls(DEFAULT)

    @classmethod
    def load(cls, path) -> "Policy":
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
        # A user file replaces the built-in rules; classes merge over defaults.
        data.setdefault("rules", [])
        return cls(data)

    @classmethod
    def resolve(cls, policy=None) -> "Policy":
        """Policy object, path, or None (env CLAUDE_VERBS_POLICY, else default)."""
        if isinstance(policy, Policy):
            return policy
        if policy is None:
            policy = os.environ.get("CLAUDE_VERBS_POLICY") or None
        return cls.load(Path(policy)) if policy else cls.default()

    def check(self, verb: str, risk: str, subject: str | None) -> Decision:
        """subject None means "not known yet": only class-level rules apply."""
        class_action = self.classes[risk]
        hits = []
        if subject is not None:
            for r in self.rules:
                if r.get("verb") in (None, verb) and re.search(r["match"], subject):
                    hits.append(r)
        if class_action == "deny":
            return Decision("deny", f"risk class {risk!r} is denied")
        for r in hits:
            if r["action"] == "deny":
                return Decision("deny", f"rule denies /{r['match']}/")
        for r in hits:
            if r["action"] == "approval":
                return Decision("approval", f"rule /{r['match']}/ needs approval")
        if any(r["action"] == "allow" for r in hits):
            return Decision("allow", "allowed by rule")
        if class_action == "approval":
            return Decision("approval", f"risk class {risk!r} needs approval")
        return Decision("allow", f"risk class {risk!r}")
