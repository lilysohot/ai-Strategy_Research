# 07 · Diff tab (read-only first)

Type: task
Status: pending
Blocked by: (none)

**Goal** (plan P2.5): port the TUI `Diff` tab — unified diff of what the agent changed.

**Critical semantics to preserve**: baseline is the content **before the session first
touched the file**. Two sources:
- `tool` — file tools declare their target, so the change is attributable.
- `scan` — non-read-only `bash` declares nothing; a before/after tree scan detects the
  change but **cannot attribute it** (a user editor or dev server writing in the same window
  is indistinguishable). Show only; never auto-revert.

**Work**: `GET /api/runs/{id}/diff` → `{files: [{path, status, hunks, additions, deletions, source}]}`;
`components/DiffPanel.vue`; tab hidden when there are no changes.

**Acceptance**: diffs correct against the baseline above; `source` distinguishable (needed by 11).

## Comments
