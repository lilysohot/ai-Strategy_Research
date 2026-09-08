# 08 · Transcript filter / search / jump-to-report

Type: task
Status: pending
Blocked by: 02

**Goal** (plan P2.6): port TUI transcript navigation — `/filter thinking|tools|errors|report|all`,
`/find <text>`, `Ctrl-G` jump to latest final report, `Ctrl-Y` copy it.

Pure frontend; no backend change.

**Work**: filter chips over the step stream; in-transcript search with next/prev; a
"jump to final report" button plus copy.

**Acceptance**: filtering/searching behave like the terminal's.

## Comments
