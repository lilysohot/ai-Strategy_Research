# 01 · Relay: merge live + replay sources

Type: task
Status: resolved
Blocked by: (none)

**Goal** (plan P1.4): make `sse_for_run` yield realtime bridge events *and* trajectory
replay concurrently, instead of replay-only.

**Why it blocks everything**: P1.1–P1.3 (bridge `wants_llm_delta`, worker `_bridge_pump`,
orchestrator `_subscribers`) are already merged, but nothing reads the subscriber queue,
so realtime events pile up and never reach the browser.

**Work**
- `server/routes/runs.py::run_events` — replace `queue = None` with `orch.subscribe(run_id)`;
  `unsubscribe` in a `finally`.
- `server/relay.py::sse_for_run` — run the live producer and `trajectory_tail` concurrently
  (`asyncio.merge` or two tasks + a channel); stop on `None` sentinel / terminal event.
- Stamp replay `assistant_delta` with `full=True` so the client can de-duplicate.

**Acceptance**: token deltas reach SSE while the run is in flight; replay and live produce
no duplicate text; reconnect via `?after=` still works.

## Answer

Done. `relay.sse_for_run` now runs live + replay concurrently; `routes.runs.run_events`
subscribes via `orch.subscribe()` and unsubscribes in a `finally`;
`orchestrator._pump_frames` publishes `event` frames and pushes the `None` sentinel in a
new `finally`.

**Bug found and fixed during implementation**: `asyncio.merge` does not exist — not even
on Python 3.12.14 (`AttributeError: module 'asyncio' has no attribute 'merge'`). The SSE
endpoint returned 500 with an empty stream. Replaced with a local `_merge_async()` helper
(queue + two pump tasks; a raising producer still counts as finished so one source cannot
hang the other).

**Verified end-to-end**: one short answer produced 118 live `assistant_delta` events
(thinking streams token-by-token: `'用户'`, `'要求'`…) plus 1 replay event with `full=true`.
Live and replay carry the same text (119 vs 118 chars) — confirming de-duplication (02) is
mandatory, not optional.

## Comments
