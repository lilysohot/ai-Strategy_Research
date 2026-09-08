# 06 · Plan / todo board

Type: task
Status: pending
Blocked by: (none)

**Goal** (plan P2.4): port the TUI `Plan` tab.

**Unblocked**: pre-requisite #1 confirmed `todo_write` is in `apodex/profiles/react.yaml:18`.

**Work**: parse todo steps/status from `todo_write` tool results in the trajectory; emit
`plan_updated` `{steps: [{id, content, status}]}`; render `components/PlanPanel.vue` with
status icons and a `done/total` header; empty state `no plan yet`. Read-only.

**Acceptance**: steps and progress track the agent's todo list; empty state when unused.

## Comments
