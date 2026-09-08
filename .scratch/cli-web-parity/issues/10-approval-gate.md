# 10 · Human-in-the-loop approval gate

Type: task
Status: pending
Blocked by: 09

**Goal** (plan P3.2): port the TUI approval prompt for writes / commands requiring confirmation.

**Blocker resolved**: pre-requisite #3 found approvals are owned by `TerminalObserver` in the
apodex session (`apodex/task_runner.py:248`). The web worker runs `BenchmarkSession`
directly, so there is **nothing to reuse** — a new approval observer must be attached in the
worker and it must suspend until the decision arrives over the stdin channel from 09.

**Work**: `approval_requested` / `approval_resolved` events; `POST /api/runs/{id}/approve`
with `decision: once|reject|session_bash|session_all|persist` + optional replacement command;
`components/ApprovalDialog.vue`.

**Non-negotiable safety** (inherited from TUI):
- Default focus is **Reject**; high-risk actions require typing `yes`.
- Hard denials are **not** overridable by "allow all".
- Native runtime is not an OS sandbox — the dialog must say so.
- Approval waits need a timeout so the worker cannot block forever.

**Acceptance**: writes trigger the dialog; reject is the default; hard denials still refuse.

## Comments
