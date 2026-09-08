# 02 · Frontend: incremental render + de-duplication

Type: task
Status: claimed
Blocked by: 01

**Goal** (plan P1.5): render assistant text token-by-token as deltas arrive.

**Why it blocks**: without de-duplication the same text arrives twice (live fragments +
whole-turn replay), so the answer would be duplicated.

**Work**
- `web/src/types.ts` — extend `SseEvent` with `text`, `thinking_text`, `turn`, `full`.
- `web/src/stores/runs.ts` — accumulate `text`/`thinking_text` per `turn` into the streaming
  block; **ignore replay events with `full=True` for turns already streamed**.
- `web/src/views/ChatView.vue` — render the streaming block during the run.

**Acceptance**: answer appears progressively; reconnect/refresh does not duplicate text.

**Implemented** (types.ts streaming fields; runs.ts `appendStep` + `streamedTurns`
de-duplication, cleared on watch/reset).

- Live frames use `text` / `thinking_text`; replay uses `content` / `thinking` with
  `full: true`. Replay copies of turns present in `streamedTurns` are dropped.
- `appendStep` folds each token into the last step of the same kind+turn, so fragments
  grow one block instead of becoming separate steps.
- `answer` accumulates from both paths, so the final text is identical either way.

**Verification gap**: `vue-tsc --noEmit` and `vite build` could not be executed — the
environment started rejecting command execution (approval prompts timing out).
`read_lints` reports 0 diagnostics on both edited files. **Re-run the build before merging.**

## Comments
