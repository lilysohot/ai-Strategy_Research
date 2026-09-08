# 05 · Files tab: in-app preview

Type: task
Status: pending
Blocked by: (none)

**Goal** (plan P2.3): port the TUI `Files` tab — read-only preview of deliverables, not
just a download list (`ArtifactPanel.vue` is list+download only today).

**Work**: `GET /api/runs/{id}/artifacts/preview?path=` returning
`{kind: text|image|binary|unsupported, content?, truncated}`; server-side type detection,
size/line truncation. **Must reuse the existing `resolve_artifact_path()`** — no new path
resolution, to keep the traversal guard single-sourced.

**Acceptance**: text/markdown/code/images preview inline; binaries offer download.

## Comments
