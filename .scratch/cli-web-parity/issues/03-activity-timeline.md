# 03 · Activity timeline (terminal-style)

Type: task
Status: pending
Blocked by: 01

**Goal** (plan P2.1): port the TUI `Activity` tab — one row per tool call with
`status icon + name + duration + summary`, expandable to full input/output/call-id.

**Work**: `components/ActivityPanel.vue`; wire `tool_started`/`tool_finished`
(`tool_call_id`, `input`, `output`, `ms`, ok/error). Running rows count up client-side
(backend only supplies the terminal `ms`). Status set: running/done/error/skipped/interrupted.

**Acceptance**: every tool call visible with args, result, duration; failures distinguished.

## Comments
