# 11 · /revert

Type: task
Status: pending
Blocked by: 07

**Goal** (plan P6.3): port TUI `/revert`.

**Depends on 07** for the `source` discriminator, because the terminal rule is strict:
revert **only** `source=tool` changes. `source=scan` entries must be shown but refused, with
an explanation — otherwise reverting would destroy unrelated user work that happened to land
in the same window.

**Work**: `POST /api/runs/{id}/revert {paths}`; reject `scan` paths with an explicit error;
UI greys them out with the explanation.

**Acceptance**: tool-attributable changes revert cleanly; scan-only changes are refused with a
clear reason.

## Comments
