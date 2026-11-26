"""claude-verbs: write what you want done as a plan of verbs; run it once; read one report."""
from .core import (Outcome, Plan, PolicyDenied, Ref, Report, RunError, Step,
                   StepFailed, StepResult, run)
from .policy import Policy
from .verbs import copy, edit, restore, sh, trash, write
from .gitflow import commit, pr, push, worktree
from .ship import ship

__version__ = "0.1.0"
__all__ = ["Outcome", "Plan", "Policy", "PolicyDenied", "Ref", "Report", "RunError",
           "Step", "StepFailed", "StepResult", "commit", "copy", "edit", "pr", "push", "restore",
           "run", "sh", "ship", "trash", "worktree",
           "write"]
