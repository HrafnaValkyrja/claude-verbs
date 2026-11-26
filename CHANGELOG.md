# Changelog

## 0.1.0 (2026-11-25)
First release.
- Core: steps, run, report, `--dry` (honest: verbs that cannot simulate say `not-simulated`), stop on first failure, lazy references between steps, `when=`, `creates=`, `unless=`, `ok_codes=`, always-run cleanup steps, nested plans, JSONL run log.
- Risk policy: classes safe/care/gated, TOML rules, deny beats allow, checked before the run and again on run-time values; the default denies `rm -r`/`rm -f`.
- Verbs: `sh` (local or over ssh), `copy`, `edit` (exact unique replace), `write` (atomic), `trash`/`restore`, `worktree`, `commit`, `push`, `pr`, `ship`.
- Report options: `show=True` per step and `--verbose` to print ok steps' output; per-step `retries=`/`retry_delay=`; default step timeout (300s, `default_timeout=`).
- CLI: `claude-verbs run plan.py [--dry] [--verbose] [--policy] [--log-dir]`.
