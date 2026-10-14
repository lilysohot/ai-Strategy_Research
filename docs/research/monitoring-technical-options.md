# Durable market-price monitoring: technical options

This note evaluates a durable monitoring subsystem for FrontierAgent. It uses only
primary sources: product documentation, standards, and first-party API documentation.
The recommendation is intentionally narrower than a general workflow platform.

## Decision

V1 draft confirmed: start with the existing HTTP snapshot adapter and a configurable
polling interval (15 minutes proposed for the initial trial). The accepted-observation
interface separates the acquisition driver from Redis consumers, rule evaluation and Run
dispatch. WebSocket is a later supplier-validated driver upgrade, not a V1 dependency.
Snapshot sampling does not promise detection of transient threshold crossings between
checks. See [V1 scope and upgrade contracts](../design/monitoring-technical-plan.md).

Scope update (2026-10-14): the initial deployment serves only a few users on limited
resources. Use single-instance background roles, a shared system-wide Run concurrency
cap, a bounded queue, deadlines, and bounded retries. Defer per-user concurrency quotas
and quota scheduling; retain ownership isolation, per-research serialization, leases,
idempotency, quote-quality gates, and recovery. Keep user identity and usage records so
quota policies and additional workers can be introduced through additive migrations and
controlled rollout. The staged upgrade and rollback plan is in
[the monitoring technical plan](../design/monitoring-technical-plan.md#14-可执行的升级路径).

Decision revision (2026-10-14): include Redis Streams in the first implementation to
provide an inspectable consumption channel while Runs may last 30 minutes. This replaces
the earlier PostgreSQL-only transport recommendation. PostgreSQL remains the business
source of truth and the recovery journal; Redis is not the sole audit store. Monitoring
is gated by browser heartbeat leases; existing Runs may finish after the page closes.

Build the first version around Redis Streams plus PostgreSQL:

- PostgreSQL is the source of truth for monitor definitions, due times, attempts,
  observations, alert decisions, notification deliveries, and UI events.
- A small async worker pool claims due rows with `FOR UPDATE SKIP LOCKED` in a short
  transaction, writes a lease/fencing token, commits, and performs the market-data call
  outside the transaction.
- Completion uses a conditional update on the fencing token. State changes and their
  outbox/UI-event rows commit in the same transaction.
- Commit accepted observations and their outbox rows before relaying to the quote Stream.
  Commit rule decisions and trigger outbox rows before acknowledging quote consumption.
  A separate trigger Stream hands events to a durable PostgreSQL scheduling inbox;
  acknowledge that handoff without waiting for the resulting Run to finish.
- Relay and consumer receipts use stable business IDs. Reconciliation republishes
  unfinished work after transport loss; PostgreSQL `LISTEN`/`NOTIFY` remains an optional hint.
- Deliver browser updates with SSE backed by the durable UI-event table and resume from
  `Last-Event-ID`.
- Add OpenTelemetry spans and low-cardinality metrics, exportable to Prometheus. Alert on
  user-visible freshness and delivery lag rather than on every internal error.

Do not reuse FrontierAgent's current scheduler as the durability boundary. Its
`ProcessManager` is explicitly in-memory, `frontier_agent/state/event_store/sqlite.py`
is currently a no-op compatibility sink, and the Hugging Face event channel is a bounded
in-process deque that deliberately drops old text deltas under pressure. Those are useful
runtime/UI seams, but a process restart cannot reconstruct a monitor or its notification
history from them.

## PostgreSQL execution model

### Claims and leases

Use a queue-shaped table with at least `monitor_id`, `next_due_at`, `state`,
`lease_owner`, `lease_token`, `lease_expires_at`, `attempt`, and `updated_at`. A claim
transaction should select a bounded ordered batch of due rows with `FOR UPDATE SKIP
LOCKED`, update those rows with a new lease token and expiry, and return the work. Commit
before making a provider request.

PostgreSQL documents that `SKIP LOCKED` gives an inconsistent view and is inappropriate
for general reads, but is specifically useful for multiple consumers of a queue-like
table ([`SELECT` locking clause](https://www.postgresql.org/docs/current/sql-select.html#SQL-FOR-UPDATE-SHARE)).
That makes it a good dispatch primitive, not a correctness mechanism for market state.
The durable row and its conditional transitions provide correctness.

Required invariants:

1. A lease has a unique opaque token (or monotonically increasing fencing version).
   Completion must update `WHERE lease_token = :mine`; a worker whose lease expired must
   not overwrite a newer attempt.
2. Provider calls, model calls, and notification sends never happen while a row lock or
   database transaction is open.
3. Attempts are at-least-once. Side effects are idempotent through unique keys such as
   `(monitor_id, scheduled_for)`, `(decision_id, destination)`, and provider event IDs.
4. `scheduled_for` is advanced from the previous schedule boundary, not from completion
   time, so slow checks do not accumulate clock drift. An explicit misfire policy chooses
   `skip`, `latest_only`, or `catch_up`; price monitoring should normally use
   `latest_only` after an outage.
5. Backoff is persisted (`next_attempt_at`, error class, attempt count), and terminal
   failure/dead-letter state remains queryable.

An advisory lock is useful only for genuinely singleton maintenance, such as one schedule
materializer or partition sweep. PostgreSQL says advisory locks have application-defined
meaning and are not enforced by the database. Session locks survive transaction rollback
until explicitly unlocked or the session ends; transaction-level locks release at the
end of the transaction ([advisory-lock documentation](https://www.postgresql.org/docs/current/explicit-locking.html#ADVISORY-LOCKS)).
Prefer `pg_try_advisory_xact_lock` for short singleton coordination. Do not represent
every job with an advisory lock: leases are inspectable, recoverable, and replicated as
ordinary row state, while advisory locks are ephemeral server-local coordination
([advisory-lock functions](https://www.postgresql.org/docs/current/functions-admin.html#FUNCTIONS-ADVISORY-LOCKS)).

### Transactional outbox and wakeups

Insert the alert decision and its delivery/UI-event rows in the same transaction as the
monitor state change. PostgreSQL transactions make the group atomic: either every update
commits or none does ([transaction tutorial](https://www.postgresql.org/docs/current/tutorial-transactions.html)).
Independent dispatchers then claim outbox rows with the same lease pattern. This closes
the crash window between “decision committed” and “message enqueued.” It does not make an
external send exactly-once; a crash after the receiver accepted a message but before the
acknowledgement commit still causes a retry, so stable idempotency keys remain necessary.

Treat `NOTIFY` as a hint containing an outbox row ID. PostgreSQL defers notifications
until commit, folds duplicate channel/payload pairs within one transaction, limits the
default payload to less than 8,000 bytes, and recommends putting larger data in a table
and sending its key ([`NOTIFY`](https://www.postgresql.org/docs/current/sql-notify.html)).
The listener startup sequence must be: commit `LISTEN`, read the durable table, then rely
on notifications; PostgreSQL documents this ordering to close the initial race
([`LISTEN`](https://www.postgresql.org/docs/current/sql-listen.html)). A periodic poll is
still required for reconnects, failover, or dropped application connections.

## Scheduler alternatives

| Option | What the primary docs establish | Implication for FrontierAgent |
|---|---|---|
| PostgreSQL loop | `SKIP LOCKED` supports competing queue consumers; transactions and row state provide atomic, inspectable recovery. | Retained for durable state, outbox, Run scheduling and recovery; Redis Streams now handles quote and trigger transport. |
| Redis Streams + PostgreSQL | Consumer groups support delivery tracking, acknowledgement and pending-message recovery ([Streams](https://redis.io/docs/latest/develop/data-types/streams/)). | Selected transport for explicit consumption records and long-Run isolation. Requires durable source records, idempotency, retention and reconciliation; it does not replace business state. |
| Celery + beat | Celery requires a broker. `celery beat` must have only one scheduler for a schedule or it can emit duplicates, periodic tasks can overlap, and workers normally acknowledge before execution; late acknowledgement can redeliver and therefore requires idempotent tasks ([periodic tasks](https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html), [task acknowledgement](https://docs.celeryq.dev/en/stable/userguide/tasks.html)). ETA/countdown jobs are held in worker memory and are discouraged for distant scheduling ([calling tasks](https://docs.celeryq.dev/en/stable/userguide/calling.html#eta-and-countdown)). | Adds a broker and result/durability choices without removing the need for database idempotency, overlap control, and an outbox. Choose it only if FrontierAgent already standardizes on Celery for broad background-work throughput. |
| Temporal | Schedules have explicit overlap policies, catch-up windows, pause-on-failure, and backfill ([Schedules](https://docs.temporal.io/schedule)). Activity attempts may repeat; heartbeats and retry policies detect failures and carry progress between attempts ([Activity tasks](https://docs.temporal.io/tasks), [failure detection](https://docs.temporal.io/encyclopedia/detecting-activity-failures)). | Strongest option when monitoring becomes a long-lived, multi-step business process with waits, human intervention, versioned workflow logic, and cross-service recovery. It introduces a service, SDK programming model, workflow determinism constraints, and duplicate protection for Activities. Too much machinery for a fetch/evaluate/notify loop today. |

Promotion trigger for Temporal: multiple days-long workflows need signals or human gates,
cross-service compensation becomes common, or operational cost from hand-built retries,
backfills, and workflow-version migration exceeds the cost of running Temporal. Scale or
worker count alone is not a trigger; PostgreSQL competing consumers already scale the
simple queue.

## Market-data time and freshness semantics

### Redis acknowledgement and durability boundary

`XACK` removes an entry from a consumer group's pending list; it does not delete the
Stream entry or establish completion of a downstream Run
([XACK](https://redis.io/docs/latest/commands/xack/)). `XAUTOCLAIM` transfers idle pending
entries to another consumer; redelivery still requires business idempotency
([XAUTOCLAIM](https://redis.io/docs/latest/commands/xautoclaim/)).

Redis documents a potential loss window with AOF `everysec`; RDB snapshots alone can
lose more recent writes ([persistence](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/)).
The chosen design therefore journals accepted observations in PostgreSQL before Stream
publication and preserves unfinished-work receipts for replay. No claim of complete
market history is made for events never received, polling gaps, or failures before the
durable acceptance boundary. Stream trimming must respect pending work and the verified
recovery window. Source publication records remain replayable until business completion
is confirmed, not merely until `XADD` returns.

### Supplier timestamps

A price has several clocks and cannot be summarized safely by one `timestamp`. Massive's
first-party US-stock trade schema distinguishes participant time (when the exchange/TRF
generated the trade), SIP time (when the SIP received it), and TRF time. Its sequence
numbers are increasing and unique per symbol but explicitly not contiguous
([stock trades](https://massive.com/docs/websocket/stocks/trades)). Its quote schema uses
the same participant/SIP distinction and says sequence values reset each trading day
([stock quotes](https://massive.com/docs/websocket/stocks/quotes)). Therefore, a numeric
gap is not by itself evidence of loss, and a sequence value is not globally unique.

Persist, at minimum:

- provider, feed/product, entitlement delay, asset class, symbol, tape/venue, event kind;
- price or bid/ask and applicable condition/correction fields;
- provider event/trade ID and `(session_date, symbol, channel, sequence)` where supplied;
- `participant_at`, `sip_at`, `provider_received_at` when supplied, and local `ingested_at`;
- the resolved market session (`pre`, `core`, `post`, `closed`, `halted` if available);
- raw provider payload or an immutable reference sufficient for audit/reprocessing.

Store instants in UTC. Resolve session boundaries with the exchange calendar and named
market timezone, including holidays and early closes; do not encode “weekdays 09:30–16:00”
as the calendar. NYSE publishes distinct pre-opening, early, core, and late sessions, and
its current calendars include holiday and special-close schedules
([NYSE trading information](https://www.nyse.com/trade/trading-information)).

Freshness should be an explicit classification, not just `now - last_price_time`:

- **fresh**: an eligible event arrived within the configured threshold for the current
  session and feed entitlement;
- **quiet**: no symbol event, but feed heartbeats/other symbols prove the connection is
  live; illiquid instruments should not be declared stale solely because they did not
  trade;
- **delayed-as-contracted**: source time reflects a known delayed feed;
- **session-closed**: absence is expected and retains the last close with its timestamp;
- **feed-stale**: provider connectivity or broad feed watermark is behind;
- **symbol-stale**: the feed is live but the symbol's quote/trade watermark violates its
  session-specific policy;
- **unknown**: missing calendar, timestamp, or entitlement metadata prevents a sound
  conclusion.

Keep quote freshness and last-trade freshness separate. A tradable NBBO can move without
a trade, while an illiquid symbol can have a valid quote and an old trade. Record both
source-to-ingest latency (`ingested_at - sip_at`) and observation age (`now - sip_at`).
Do not silently turn a delayed entitlement into a real-time SLA.

Live data can later be corrected. Massive states that canceled trades remain in the feed
and are identified through a correction field, with end-of-day aggregates updated to
reflect cancellations ([canceled-trade behavior](https://massive.com/knowledge-base/article/how-much-does-massives-feeds-handle-canceled-trades)).
The data model should append corrections/reversals and run a REST or end-of-day
reconciliation path rather than destructively replacing the original observation.

## SSE and notification recovery

The database `ui_events` row ID should be the SSE `id`. On connect, read the browser's
`Last-Event-ID`, replay `WHERE stream_id = :stream AND id > :cursor ORDER BY id`, then
tail new committed rows. The HTML standard specifies that reconnecting `EventSource`
sends `Last-Event-ID`; the `retry` field controls reconnection time, and HTTP 204 stops
reconnection ([WHATWG server-sent events](https://html.spec.whatwg.org/multipage/server-sent-events.html)).

Operational rules:

- IDs are stable database cursors, never per-process counters.
- Replayed events are safe to apply more than once; include entity version and event type.
- If retention has removed the requested cursor, return a typed `reset_required` event
  with a fresh snapshot cursor rather than pretending the stream was complete.
- Publish a snapshot/checkpoint periodically so a client need not replay an unbounded
  delta log.
- Send SSE comment heartbeats during idle periods; the standard's authoring notes suggest
  a comment roughly every 15 seconds to survive legacy proxy timeouts.
- A PostgreSQL notification only wakes the tailer. Missing it cannot lose an event because
  the durable query by ID is authoritative.

FrontierAgent's structured `DemoEvent` vocabulary can remain the presentation contract,
but durable events need a database ID, schema version, aggregate/entity version, and
causation/correlation IDs in addition to the current `session_id`, `run_id`, type, time,
and data fields.

## Prometheus and OpenTelemetry

Use OpenTelemetry at service boundaries and export to an OpenTelemetry Collector, which
can feed Prometheus and a trace backend. Python traces and metrics are stable signals in
the official implementation ([Python status](https://opentelemetry.io/docs/languages/python/));
HTTP client instrumentation is available for the repo's existing `httpx` dependency
([Python instrumentation libraries](https://opentelemetry.io/docs/languages/python/libraries/)).
Keep the existing JSONL `TraceObserver` as a local diagnostic artifact; it is not a
replacement for cross-process correlation.

Recommended measurements:

- counters: checks started/completed by `provider`, `asset_class`, and bounded `outcome`;
  retries by bounded `reason`; alerts evaluated/fired/suppressed; notification attempts
  and results; SSE reconnects, replays, resets, and dropped in-process deltas;
- histograms: queue/schedule lag, provider latency, evaluation duration, transaction
  duration, notification latency, and SSE replay batch size;
- timestamp gauges: last successful provider ingest, last successful evaluation, oldest
  pending outbox creation time, and oldest due job time;
- gauges: jobs/outbox rows by bounded state, active leases, open SSE connections, and
  provider connection state.

Prometheus recommends exporting the event timestamp and calculating age with `time()`
rather than maintaining a “time since” gauge, and warns that every label set creates a
new time series; cardinality above 100 should prompt another design
([instrumentation guidance](https://prometheus.io/docs/practices/instrumentation/)).
Never label metrics with `monitor_id`, user ID, notification ID, run ID, or generally
symbol. Put those searchable identifiers on traces/logs; use sampled exemplars if the
backend supports them.

Create one trace per scheduled check with spans for claim, provider request, normalize,
evaluate, persistence/outbox commit, and delivery. Persist `trace_id` on the attempt,
decision, and outbox row so a UI or alert can reach the trace. OpenTelemetry's common
semantic conventions provide consistent service, HTTP, database, and messaging names,
while domain fields such as market session and entitlement need a small versioned
FrontierAgent convention ([semantic conventions](https://opentelemetry.io/docs/concepts/semantic-conventions/)).

Alert on consequences: source/ingest freshness during an expected session, oldest due-job
lag, oldest pending delivery age, sustained provider errors, and SSE reset rates.
Prometheus recommends paging on user-visible symptoms and allowing slack for brief blips
([alerting guidance](https://prometheus.io/docs/practices/alerting/)); its `for` clause
requires a condition to remain active before firing and `keep_firing_for` reduces flapping
([alerting rules](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/)).
Apply session-aware rules so the market close does not page as stale data. Use
Alertmanager grouping and inhibition so a provider outage yields one provider incident
and suppresses its derivative per-symbol alerts
([Alertmanager](https://prometheus.io/docs/alerting/latest/alertmanager/)).

## Suggested delivery order

1. Add PostgreSQL monitor/schedule, attempt, observation, decision, outbox, delivery, and
   UI-event tables with uniqueness constraints and retention rules.
2. Implement the short claim transaction, lease fencing, `latest_only` misfire behavior,
   idempotent completion, and a reaper for expired leases.
3. Add provider normalization with multi-clock timestamps, entitlement/session metadata,
   separate trade/quote watermarks, and correction reconciliation.
4. Add transactional UI/outbox writes, poll-based dispatchers, then optional
   `LISTEN`/`NOTIFY` wakeups.
5. Serve resumable SSE with replay, snapshot reset, and heartbeat comments.
6. Instrument the flow with OpenTelemetry and Prometheus-compatible metrics; add
   session-aware freshness, schedule-lag, and delivery-lag alerts plus one external
   end-to-end canary.

This order makes every later optimization depend on durable, replayable state. Celery or
Temporal can then replace the dispatch layer without changing the market-time model,
idempotency keys, outbox semantics, or SSE recovery contract.
