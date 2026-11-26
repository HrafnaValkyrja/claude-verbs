"""claude-verbs: write what you want done as a plan of verbs; run it once; read one report."""
from .core import (Outcome, Plan, PolicyDenied, Ref, Report, RunError, Step,
                   StepFailed, StepResult, run)
from .policy import Policy
from .verbs import edit, restore, sh, trash, write

__version__ = "0.1.0"
__all__ = ["Outcome", "Plan", "Policy", "PolicyDenied", "Ref", "Report", "RunError",
           "Step", "StepFailed", "StepResult", "edit", "restore", "run", "sh", "trash",
           "write"]
