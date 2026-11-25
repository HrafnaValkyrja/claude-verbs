"""JSONL run log.

PURPOSE: append one JSON object per event of a run to a file.
WHY: every run stays auditable after the report scrolls away.
REFS: PLAN.md "a log of every run".
LOGS: <dir>/<utc-stamp>-<run id>.jsonl; dir = arg, else CLAUDE_VERBS_LOG_DIR,
      else ~/.local/state/claude-verbs/runs.
READS-BY: claude_verbs.core.run
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

MAX_TEXT = 20_000


def default_dir() -> Path:
    env = os.environ.get("CLAUDE_VERBS_LOG_DIR")
    return Path(env) if env else Path.home() / ".local/state/claude-verbs/runs"


class RunLog:
    def __init__(self, run_id: str, directory=None):
        self.path: Path | None = None
        try:
            d = Path(directory) if directory else default_dir()
            d.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
            self.path = d / f"{stamp}-{run_id}.jsonl"
            self.path.touch()
        except OSError:
            self.path = None  # logging must never break a run

    def event(self, kind: str, **fields) -> None:
        if self.path is None:
            return
        fields = {k: (v[:MAX_TEXT] if isinstance(v, str) else v) for k, v in fields.items()}
        rec = {"event": kind, "ts": round(time.time(), 3), **fields}
        try:
            with open(self.path, "a") as fh:
                fh.write(json.dumps(rec, default=str) + "\n")
        except OSError:
            pass
