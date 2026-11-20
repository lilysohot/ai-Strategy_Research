# Super-link communication and runtime adapters

This package implements P1 and the first runtime/inspection/queue slice in the
[communication plan](../../docs/plan/super-link-communication-foundation.md).
It exposes host adapters and an initial independent collaboration page, not an
A2A endpoint. Importing the package starts no consumers. `SERVER_SUPER_LINK_ENABLED=false`
is the default: ordinary runs do not query this schema or use these adapters.
When explicitly enabled, the API lifespan starts the coordination loop; existing
workflows and AgentBus remain unchanged. Owner-only diagnostic/recovery HTTP APIs
are available when enabled. `/super-link` has its own list/create/detail pages,
separate from the ordinary Single/Team mode selector.

## Contract

Call `service` functions inside a caller-owned `AsyncSession` transaction.
They flush but never commit; an exception must roll back the transaction.
Before the caller commits, it must call `events.seal_changes(session)` after the
last business write. `business_service.business_transaction` is the shared seal
point for HTTP write paths; `store` committing helpers and
`dispatch_outbox.stop_queued_run` seal inside their own transaction.

| Operation | Guarantee on commit | Does not imply |
|---|---|---|
| `create_pair` | One space, two new exclusive sessions; owner/creation-key retries return the same pair | Existing sessions were migrated, or either agent ran |
| `register` | Immutable text content and source identity saved; same Run/key returns the original message, changed content conflicts | Publication or delivery |
| `publish` | Successful source Run and archived native-continuity hash; runtime-bound runs require parent-observed process exit; V2 snapshots selected evidence; publication/outbox atomic | Semantic completeness or inspector approval |
| `receive` | Exactly one durable transport receipt in `awaiting_check`; repeats are no-ops | Execution acceptance, adoption, FIFO position or a new Run |
| `inbox` | Owner-scoped host query of received messages | Permission to inject unreviewed content into an agent |

`SenderBinding` comes from the trusted host, never from model-supplied owner
fields. The service verifies space ownership, participant/session association,
Run ownership and role/pipeline identity. Recipients stay inside the same space.
Replies must refer to a published, received message sent in the opposite
direction; they retain the original `request_id`. A request may span many Runs;
the foundation does not yet implement its business resolution lifecycle.

`DeliveryContent` V1 permits bounded nonblank text and `requests_execution`
(default false), preserving its original digest. V2 adds at most four explicit
UTF-8 output references (`rel_path`, `sha256`), each at most 64,000 bytes. After
exit, the parent verifies the artifact index, containment and actual byte hash,
then stores immutable text snapshots in the same publication transaction. Unknown
versions/fields, missing or changed files block publication. Binary documents and
automatic URL fetching are not supported. Private native continuity never crosses
the interface; ordinary file references grant no access to peer history.

Goal versions and pause state gate inspection, admission and launch. Owner controls
and their independent UI are implemented in `controls.py` and `SuperLinkControls.vue`.
Goal editing remains outside this slice.

## Persistence and transport

Dedicated tables live in `models.Base`, separate from `server.store.Base`.
Foreign keys refer to existing users, sessions and Runs. New participants use
new sessions, so ordinary sessions gain no collaboration records or dependencies.
The optional migration has its own version table, `super_link_alembic_version`;
the legacy migration head and readiness metadata do not change.

After the legacy database is prepared, an operator can explicitly install the
optional tables in the selected environment with:

```bash
uv run --no-sync alembic -c server/super_link/alembic.ini upgrade head
```

This command has only been exercised against the isolated test database for this
batch. It is not run on server startup. Stopping collaboration must retain its
records; the destructive Alembic downgrade is not a feature-disable mechanism.
`sl_0006_events` chains after `sl_0005_controls`; event rows reference
`super_link_event_heads.space_id` rather than the space row, so sealing does not
reintroduce a Space/head lock cycle.

Event capture is transactional: stage drafts during the business write, call
`events.seal_changes(session)` after the last write, then commit immediately.
`read_events(user_id, space_id, after, limit)` is owner-scoped, returns only
`(after, observed_head]`, and reports cursors for T03. The Redis notifier scans
unnotified rows and only advances `notified_at` after successful publication.

Construct `transport.Delivery(redis, sessions, namespace=...)` explicitly with an
async SQLAlchemy sessionmaker and a Redis client. Configure bounded Redis socket
timeouts in that client when adding a worker. Production namespace must start
with `super-link:`; tests use fresh `test:super-link:` namespaces. The dedicated
consumer group is `super-link-receivers-v1`.

- `relay()` publishes up to 100 pending message IDs, with no DB transaction held
  across Redis I/O. Pending records are re-announced after 60 seconds by default.
- `consume()` reads/reclaims up to 25 notifications. Durable receipt commits
  before ACK. A database failure leaves the notification pending.
- Duplicate IDs, consumer restart, lost ACKs and Redis loss do not duplicate
  receipts. Invalid transport IDs are discarded; invalid durable content is
  quarantined with a stable reason, without dispatching work.
- Redis carries IDs only. Content, reply relationships and receipt state remain
  in PostgreSQL. Redis failure does not alter a completed source Run.

The opt-in lifespan starts separate cancellable tasks for transport, finalization
recovery, inspection and admission. Slow inspection does not hold those other lanes.
Configure `SERVER_SUPER_LINK_REDIS_URL` to the existing
Redis service and a dedicated `SERVER_SUPER_LINK_NAMESPACE` (default `super-link:v1`).
Do not enable before the optional migrations, through `sl_0006_events`, are
installed. Normal dispatch must also be enabled. No migration runs at startup.
The existing dispatch envelope carries a host-written Super-link marker; when
disabled, marked queued work is held without accessing optional tables. The
marker is stripped before the task reaches the worker.
Redis retries never authorize rerunning a model or repeating external side effects.

## Runtime and coordination boundary

- The worker receives a run-bound capability socket. Only the Single agent or
  Team coordinator gets `register_super_link_delivery`; the tool also checks the
  execution role. Parent-side identity and peer validation reject forged owners,
  cross-space recipients and calls after termination. The tool only registers.
- The parent records process exit separately from `run_finished`. Publication
  waits for successful termination, saved native continuity and final evidence.
  The immutable archive alone is insufficient: the session's active continuity
  head must identify this Run and match its payload digest before publication.
  A CAS conflict retains the barrier instead of releasing the next queued Run.
  A failed launch or execution never publishes; a missing archive/evidence stays
  pending with a reason. Recovery retries the original artifacts and conversation
  dump using the saved expected-head CAS, then retries publication idempotently.
  Without an exit witness, recovery holds the run for investigation, never infers
  safe publication from a terminal frame alone.
- Inspection has its own records and receives the goal, delivery, fixed evidence,
  persisted source Run task, participant roles and host-owned responsibility
  constraints. It cannot dispatch. Role metadata is not a claim that a particular
  tool/data source is available; unsupported capability claims need evidence.
  The first evaluator uses a tool-free call to the
  owner's OpenAI-compatible configuration (or configured OpenAI server default).
  Unknown providers, timeouts and malformed answers remain `incomplete`.
  Inspection attempts retain inputs, a key-free model configuration snapshot,
  outcome and timing. Claims have a 90-second lease, with a 60-second call bound;
  an expired attempt cannot overwrite its successor. Technical failures retry
  up to three total attempts, with exponential backoff starting at 30 seconds
  and capped at 300 seconds. Configuration errors require explicit recovery.
  A model's business `block`/`incomplete` is feedback, not a technical retry.
  Deterministic pre-model validation failures also create a blocked review; they
  cannot permanently occupy the first inspection batch.
- Only `pass`/`caveat` plus an explicit execution request can be admitted. The
  coordinator rechecks goal/content/evidence and owner, then atomically creates
  one Run, execution mapping and existing RunDispatch. It writes no human turn.
  Caveats remain in the receiving task. Default automatic acceptance budget is
  20 Runs per space (`SERVER_SUPER_LINK_MAX_AUTOMATIC_RUNS`), shared by execution
  and correction Runs; reaching it holds
  subsequent admission. This is a temporary infrastructure limit, not strategy.
  Held/failed admissions persist a reason and a 30-second retry time. Admission
  and completion recovery process never-attempted/least-recently-attempted due
  entries first so an unrepairable batch cannot starve other spaces. This changes
  background retry scheduling, not the established per-session Run execution order.
  Automatic Runs use the existing key-free model snapshot builder for audit.
- Per-session FIFO uses `(Run.created_at, Run.id)`; same-timestamp entries use
  the UUID tie-break. It includes human/monitor/collaboration sources and delayed
  retries. Any preceding unfinished finalization holds subsequent execution.
  Different participant sessions remain independent; Team internals may parallel.
  Legacy direct human submissions for bound sessions enter the durable outbox.
- Bound sessions write their own normal native continuity, including automatic
  follow-up. Ordinary watch sessions retain their original read-only continuity.
  Collaboration-origin runs cannot use the manual paused-monitor cancellation
  exception. Existing destructive-operation approval rules are unchanged.
- `read_super_link_inbox` is available only to the opted-in main Agent. At Run
  preparation the host freezes the set of published, received, pass/caveat,
  current-goal informational deliveries for that recipient. The tool lists bounded
  summaries (up to 20 per page) or reads one full delivery with fixed evidence,
  provenance and inspection notes. It cannot read queued execution requests,
  unreviewed/blocked deliveries, another recipient, private history, or messages
  that became eligible after the Run began. A later genuine Run sees new items;
  informational receipt never creates a Run. Reading is not adoption or execution;
  useful results enter the Agent's own native continuity through its normal tools.
  `super_link_inbox_access` records the visibility set; it is not a shared memory.

## Feedback and owner recovery

The coordinator consumes blocked/incomplete business decisions into at most one
correction Run per message, queued in the original sender's existing session.
The reviewer itself never dispatches. The sender can supplement, explain an
objection or finish without submitting another delivery. A new delivery may use
`revises_message_id` to retain the original request lineage; it must come from a
different Run by the same sender to the same recipient. It undergoes normal exit,
continuity, evidence and independent inspection gates. Original content and
decisions stay intact. Revisions do not automatically cancel other deliveries or
rewrite queues. Correction Runs are autonomous, not new human authorization.

Owner-authenticated routes under `/api/super-link`:

| Method/path | Purpose |
|---|---|
| `GET /capabilities` | Creation availability using existing Team/dispatch/storage gates |
| `POST /spaces` | Atomically create a pair and queue the first Team Run; body `goal`, UUID `creation_key` |
| `GET /spaces` | Owned spaces, bounded pagination |
| `GET /spaces/{id}` | Goal, participants and shared automatic Run budget |
| `GET /spaces/{id}/deliveries` | Delivery/inspection/dispatch/finalization status |
| `GET /spaces/{id}/deliveries/{message_id}` | Content, attempt inputs/outcomes and revision lineage |
| `GET /spaces/{id}/runs` | Runs in session FIFO order and recovery reasons |
| `GET /spaces/{id}/recovery-actions` | Actor, reason, idempotency key and result audit |
| `POST /spaces/{id}/recovery` | Explicit bounded recovery command |
| `POST /spaces/{id}/control` | Versioned, idempotent pause/stop/resume or explicit human continuation |
| `GET /spaces/{id}/interventions` | All live pending approvals, active runs and latest 100 control records |
| `POST /spaces/{id}/runs/{run_id}/approve` | Owner/space/pending-ID checked native approval request |
| `POST /spaces/{id}/runs/{run_id}/steer` | Native live instruction; worker adoption remains separate |

Recovery bodies require `action`, UUID `idempotency_key`, and nonblank `reason`.
`inspection_retry`, `admission_retry`, `feedback_retry` target a message;
`finalization_retry`, `abandon_finalization` target a Run via `target_id`.
`extend_budget` uses `additional_runs` (1–100, space ceiling 1000) and no target.
Retry actions grant at most three further attempts, capped at 20 cumulative
attempts per target; they never erase audit history. Admission and finalization
technical retries start with three attempts. Queue capacity/pause waits do not
consume technical-attempt budget. Replaying a command is idempotent; reusing a
key with changed content conflicts. Restore mode permits reads only; feature-off
routes return 404 before querying optional tables.

An abandoned finalization is failed, never published or reported as successful.
Abandonment requires a recorded exit witness or conservative Linux evidence that
the recorded worker process group is gone in the same boot/PID namespace. Unknown
legacy or cross-host process evidence stays blocked. Native ingestion serializes
with abandonment so a late callback cannot write old memory after queue release.
This does not implement cross-host exit reconciliation or process termination.
No command force-passes a review, fabricates exit status or rewinds continuity.

## Validation and remaining integration

`tests/test_super_link.py` covers contracts on isolated SQLite.
`tests/pg/test_super_link.py` uses the repository's opt-in registered-test-database
guard and a separate `SUPER_LINK_TEST_REDIS_URL`, with a random stream namespace.
It exercises actual migration, concurrent writes, Redis failures and recovery.
Foundation transport tests use explicit test Runs. `tests/test_super_link_runtime.py`
also launches real Linux Web workers with the existing Team and Single workflows,
through the normal sandbox, tool registry, approval policy and conversation store.
Both directions run an independent inspector call, dispatch the recipient and
publish its correlated reply, then read that information-only reply in a later
real worker and verify it is retained in native memory. All those model responses are scripted at a local
endpoint, protected by `FRONTIER_LLM_LOCAL_ONLY`; they do not validate research or
inspection quality. Migration downgrade tests touch only the guarded test DB.
`tests/test_super_link_reliability.py` exercises cross-space poison/paused/full/
budget-exhausted batches, slow-model lane isolation, continuity CAS conflicts,
inbox visibility/authorization and model audit metadata. Selected regressions also
run against PostgreSQL; the new optional migration preserves existing deliveries.

`tests/test_super_link_recovery.py` adds lease/retry exhaustion, feedback/revision,
shared budget, owner isolation, monitor authority and abandonment regressions.
Real worker tests also exercise correction and independent reinspection in both
directions. PostgreSQL tests cover concurrent recovery, feedback deduplication,
late-answer fencing and ingestion/abandonment serialization. The recovery
migration preserves legacy decisions as attempt 1 with explicitly unknown inputs.

Next: cross-host orphan exit reconciliation, goal changes,
retention and binary evidence, and real
research/monitoring acceptance. Local service activation is recorded in the
communication plan §17, followed by requested service shutdown in §18. The local
enable switch is now false; the source default remains disabled as well.
A2A wire compatibility remains unimplemented.

## Independent page entry

The research navigation links to `/super-link`; detail deep links use
`/super-link/{space_id}`. Creating a space uses the current user's model settings
and creates exactly one initial human-origin Team Run, outside the automatic
follow-up budget. Pair creation, user turn and dispatch share a transaction.
Repeated creation keys replay the same result; changed goals conflict. The UI
retains the pending key and goal in user-scoped tab storage across reloads.

Participants remain normal independent sessions for runtime/continuity, but the
ordinary `/api/sessions` listing excludes them before pagination and counting.
Schema inspection supports installations without the optional tables; installed
collaboration sessions stay hidden even when the execution feature is switched
off. No legacy table migration is needed for the page entry.

The page shows both participants' runs, result/trace/artifact drawers,
formal deliveries, inspection decisions and revisions. Details poll every five
seconds; browsing older records pauses polling until refresh. Ownership failures,
feature-off and network errors are explicit. Approval, live instructions, new human
tasks, space lifecycle and bounded recovery now have their own controls. Worker
acknowledgements determine approval/adoption; no HTTP response fabricates them.
Browser tests use intercepted API fixtures;
server tests separately cover atomic creation, rollback and PostgreSQL concurrency.

## Space lifecycle controls

`pause` retains the FIFO queue and drains tasks already submitted to the native
orchestrator; those runs can still read their frozen inbox, register results and
finish. New reviews, admissions and dispatch stop. `stop` durably enters `stopping`,
cancels queued intents and repeatedly requests native cooperative termination.
It becomes `stopped` only after active runs and unresolved finalizations are gone.
An unknown remote worker is never treated as exited. A separate background lane
retries stop requests after disconnect/restart, independently of model reviews.

`resume` re-enables scheduling from paused/stopped. It does not resurrect cancelled
runs. A delivery cutoff prevents pre-stop unexecuted requests and corrections from
being automatically replayed. Existing published evidence and inspection audit
remain readable; the cutoff concerns further processing, not deleting history.
New monitor-generated runs for a stopped space are cancelled at the dispatch
adapter. This does not delete monitoring targets or shut down market-data collection.

Commands require owner authentication, `reason`, UUID `idempotency_key` and
`expected_version`. The Space row lock fences concurrent controls; retries replay
the prior audit result, changed payloads conflict, stale new commands fail. Native
dispatch rechecks pause under the same lock immediately before submit. A separate
human `continue` command atomically appends a user task and queues a new fixed-role
Run; it respects capacity/FIFO and is outside automatic-follow-up accounting.
It never rewinds an interrupted Run or automatically repeats its external actions.

The control UI does not bind either participant to the ordinary workbench's global
run store. It restores pending approvals from durable native control records,
supports rejection with replacement instructions and bounded per-run grants, and
shows real worker adoption/expiry. Lifecycle/recovery request IDs survive browser
reload under a user/space-scoped storage key. The service remains stopped locally;
apply the optional migration before a separately requested deployment/activation.
