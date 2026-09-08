# 04 · Status bar upgrade

Type: task
Status: pending
Blocked by: 01

**Goal** (plan P2.2): match the TUI status bar — `阶段 · 耗时 · workflow · model ·
context · tools · queued`.

**Work**: `components/StatusBar.vue`. Sources: phase from lifecycle events; elapsed from a
client timer; workflow/model/tools from `run_started`; queued from the local steer queue
(needs 09); context remaining from cumulative usage vs window.

**Blocker note**: `context 余量` needs a usage/context-window figure from the backend; must
match the T2.11 `aggregate_usage` accounting, not a second ad-hoc calculation.

**Acceptance**: all fields populated and consistent with the usage page.

## Comments
