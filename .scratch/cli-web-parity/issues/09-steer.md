# 09 · Steer (mid-run intervention)

Type: task
Status: pending
Blocked by: 01

**Goal** (plan P3.1): port TUI steer — queue guidance mid-run **without** terminating the
current LLM request or tool call.

**Work**: extend the existing worker stdin JSONL control channel with
`{"action":"steer","message":...}`; worker converts to a runtime `Intervention` at the next
safe turn boundary (mirror `apodex/steer.py` semantics). `POST /api/runs/{id}/steer`;
input stays enabled during a run; `queued` counter increments.

**Must not**: change stop semantics — stopping stays on `/control`, never a sent "stop" message.

**Acceptance**: a queued message lands at the next turn boundary; the in-flight call is not cut off.

## Comments
