import test from 'node:test'
import assert from 'node:assert/strict'

import {
  createSpaceSync,
  parseSpaceCursor,
  type SpaceStreamRequest,
  type SpaceSyncState,
  type SyncTiming,
} from './sync.ts'
import type {
  Delivery,
  LinkRun,
  SnapshotQuery,
  SpaceSnapshot,
} from '../api/superLink.ts'
import type { SpaceStreamCallbacks } from './stream.ts'
import type { RunControlRecord } from '../types.ts'

const SPACE = 'space-1'
const EPOCH = 'epoch-1'

function cursor(seq: number, epoch = EPOCH): string {
  return `sl1:${SPACE}:${epoch}:${seq}`
}

function run(id: string, status = 'queued'): LinkRun {
  return {
    run_id: id,
    session_id: 'session-1',
    status,
    pipeline_id: 'single',
    created_at: '2026-11-20T00:00:00Z',
    finalization: null,
    dispatch: null,
  }
}

function delivery(id: string): Delivery {
  return {
    message_id: id,
    phase: 'delivered',
    sender_id: 'participant-1',
    recipient_id: 'participant-2',
    request_id: 'request-1',
    revises_message_id: null,
    published_at: '2026-11-20T00:00:00Z',
    inspection: null,
    source_run: null,
    recipient_run: null,
    feedback: null,
  }
}

function pending(id: string): RunControlRecord {
  return { control_id: id, run_id: 'run-1', kind: 'approval', status: 'pending', request: {} }
}

function action(id: string): { id: string; actor_id: string; request: Record<string, unknown>; result: Record<string, unknown>; created_at: string } {
  return { id, actor_id: 'user-1', request: {}, result: {}, created_at: '2026-11-20T00:00:00Z' }
}

interface SnapshotOptions {
  epoch?: string
  runs?: LinkRun[]
  runsNext?: string | null
  runsTotal?: number
  deliveries?: Delivery[]
  deliveriesNext?: string | null
  pending?: RunControlRecord[]
  actions?: ReturnType<typeof action>[]
  activeRunIds?: string[]
  controlState?: 'active' | 'paused' | 'stopping' | 'stopped'
  controlVersion?: number
}

function snapshot(seq: number, options: SnapshotOptions = {}): SpaceSnapshot {
  const runs = options.runs ?? []
  return {
    schema_version: 1,
    cursor: cursor(seq, options.epoch),
    as_of: '2026-11-20T00:00:01Z',
    durability_scope: 'committed_records',
    space: {
      space_id: SPACE,
      goal: '共同研究目标',
      goal_version: 1,
      paused: false,
      control_state: options.controlState ?? 'active',
      control_version: options.controlVersion ?? 0,
      delivery_cutoff: null,
      can_control: true,
      automatic_budget: { used: 0, limit: 20, remaining: 20 },
    },
    participants: [
      { participant_id: 'participant-1', session_id: 'session-1', role: 'team', available: true },
    ],
    runs: {
      items: runs,
      total: options.runsTotal ?? runs.length,
      next_after: options.runsNext ?? null,
    },
    deliveries: {
      items: options.deliveries ?? [],
      total: options.deliveries?.length ?? 0,
      next_after: options.deliveriesNext ?? null,
    },
    pending_interventions: {
      items: options.pending ?? [],
      total: options.pending?.length ?? 0,
      next_after: null,
    },
    actions: {
      items: options.actions ?? [],
      total: options.actions?.length ?? 0,
      next_after: null,
    },
    active_run_ids: options.activeRunIds ?? runs.filter((r) => r.status === 'running').map((r) => r.run_id),
    capabilities: { replay: true, live_output: 'local_owner_only' },
  }
}

interface PendingSnapshot {
  query: SnapshotQuery
  resolve: (value: SpaceSnapshot) => void
  reject: (error: unknown) => void
}

class FakeStream {
  readonly options: SpaceStreamRequest
  stopped = false

  constructor(options: SpaceStreamRequest) {
    this.options = options
  }

  get callbacks(): SpaceStreamCallbacks {
    return this.options.callbacks
  }

  open(): void {
    this.callbacks.onOpen?.()
  }

  fact(seq: number, invalidate: string[], epoch = EPOCH): void {
    const frame = cursor(seq, epoch)
    this.callbacks.onFact({
      schema_version: 1,
      type: 'sl.run.changed',
      space_id: SPACE,
      stream_epoch: epoch,
      seq: String(seq),
      cursor: frame,
      invalidate,
    })
  }

  control(event: 'sl.auth_required' | 'sl.resync_required' | 'sl.unavailable'): void {
    this.callbacks.onControl(event, 'test')
  }

  close(reason: 'eof' | 'error' | 'http', status?: number, retryAfterMs?: number): void {
    this.callbacks.onClose?.({ reason, status, retryAfterMs })
  }
}

interface Harness {
  sync: ReturnType<typeof createSpaceSync>
  clock: FakeClock
  states: SpaceSyncState[]
  calls: SnapshotQuery[]
  streams: FakeStream[]
  take: () => PendingSnapshot
  state: () => SpaceSyncState
  flush: () => Promise<void>
}

interface FakeClock {
  timing: SyncTiming
  advance: (ms: number) => void
  pendingTimers: () => number
}

function makeClock(): FakeClock {
  let clock = 0
  let nextId = 1
  const timers = new Map<number, { at: number; fn: () => void }>()
  return {
    timing: {
      setTimeout: (fn, ms) => {
        const id = nextId
        nextId += 1
        timers.set(id, { at: clock + ms, fn })
        return id
      },
      clearTimeout: (handle) => {
        timers.delete(handle as number)
      },
      now: () => clock,
      // Deterministic zero jitter: reconnect delays are 0 unless a test
      // advances the clock past a forced Retry-After.
      random: () => 0,
    },
    advance(ms) {
      clock += ms
      for (;;) {
        const due = [...timers.entries()]
          .filter(([, timer]) => timer.at <= clock)
          .sort((a, b) => a[1].at - b[1].at)[0]
        if (!due) break
        timers.delete(due[0])
        due[1].fn()
      }
    },
    pendingTimers: () => timers.size,
  }
}

function makeHarness(): Harness {
  const clock = makeClock()
  const states: SpaceSyncState[] = []
  const calls: SnapshotQuery[] = []
  const streams: FakeStream[] = []
  const pending: PendingSnapshot[] = []

  const sync = createSpaceSync({
    spaceId: SPACE,
    loadSnapshot: (query) =>
      new Promise<SpaceSnapshot>((resolve, reject) => {
        calls.push(query)
        pending.push({ query, resolve, reject })
      }),
    openStream: (options) => {
      const stream = new FakeStream(options)
      streams.push(stream)
      return { stop: () => { stream.stopped = true } }
    },
    onState: (value) => states.push(value),
    timing: clock.timing,
  })

  return {
    sync,
    clock,
    states,
    calls,
    streams,
    take: () => {
      const next = pending.shift()
      if (!next) throw new Error('no pending snapshot request')
      return next
    },
    state: () => {
      const latest = states.at(-1)
      if (!latest) throw new Error('no state emitted yet')
      return latest
    },
    flush: async () => {
      await new Promise<void>((resolve) => setImmediate(resolve))
    },
  }
}

async function boot(harness: Harness, initial: SpaceSnapshot): Promise<FakeStream> {
  harness.sync.start()
  harness.take().resolve(initial)
  await harness.flush()
  const stream = harness.streams.at(-1)
  assert.ok(stream, 'stream should open after the first snapshot')
  stream.open()
  return stream
}

test('parseSpaceCursor validates shape, space and sequence', () => {
  assert.deepEqual(parseSpaceCursor(cursor(7), SPACE), {
    spaceId: SPACE,
    epoch: EPOCH,
    seq: 7,
  })
  assert.equal(parseSpaceCursor('sl1:space-1:epoch-1', SPACE), null)
  assert.equal(parseSpaceCursor('sl1:space-2:epoch-1:1', SPACE), null)
  assert.equal(parseSpaceCursor('sl1:space-1:epoch-1:abc', SPACE), null)
  assert.equal(parseSpaceCursor('nope', SPACE), null)
})

test('snapshot opens the stream at its cursor and facts coalesce into one refresh', async () => {
  const harness = makeHarness()
  const stream = await boot(harness, snapshot(5, { runs: [run('run-1')] }))

  assert.deepEqual(harness.calls[0], { limit: 50 })
  assert.equal(stream.options.after, cursor(5))

  stream.fact(6, ['runs'])
  stream.fact(7, ['deliveries'])
  harness.clock.advance(149)
  assert.equal(harness.calls.length, 1, 'debounce must wait')
  harness.clock.advance(1)
  assert.equal(harness.calls.length, 2)
  assert.equal(harness.calls[1].min_cursor, cursor(7))

  harness.take().resolve(
    snapshot(7, { runs: [run('run-2'), run('run-1')], deliveries: [delivery('msg-1')] }),
  )
  await harness.flush()

  const state = harness.state()
  assert.equal(state.cursor, cursor(7))
  assert.equal(state.status, 'live')
  assert.deepEqual(state.runs.items.map((r) => r.run_id), ['run-2', 'run-1'])
  assert.deepEqual(state.deliveries.items.map((d) => d.message_id), ['msg-1'])
  assert.equal(state.updatedAt, 150)
})

test('a superseded refresh is discarded whole and cannot rewind the cursor', async () => {
  const harness = makeHarness()
  const stream = await boot(harness, snapshot(5))

  stream.fact(6, ['runs'])
  harness.clock.advance(150)
  const slow = harness.take()

  stream.fact(7, ['runs'])
  harness.clock.advance(150)
  const fast = harness.take()

  // The newer request resolves first; the older one lands afterwards and must
  // not overwrite the newer state or move the cursor back to 6.
  fast.resolve(snapshot(7, { runs: [run('run-7')] }))
  await harness.flush()
  slow.resolve(snapshot(6, { runs: [run('run-6')] }))
  await harness.flush()

  const state = harness.state()
  assert.equal(state.cursor, cursor(7))
  assert.deepEqual(state.runs.items.map((r) => r.run_id), ['run-7'])
})

test('a latest response older than the stream cursor is discarded and retried', async () => {
  const harness = makeHarness()
  const stream = await boot(harness, snapshot(5))

  stream.fact(6, ['runs'])
  harness.clock.advance(150)
  harness.take().resolve(snapshot(4, { runs: [run('run-4')] }))
  await harness.flush()

  assert.deepEqual(harness.state().runs.items, [])
  // The dirty scope was re-queued, so one more refresh is scheduled.
  assert.equal(harness.clock.pendingTimers(), 1)
  harness.clock.advance(150)
  assert.equal(harness.calls.length, 3)
})

test('history defers live merges and returnToLatest rebuilds the first page', async () => {
  const harness = makeHarness()
  const stream = await boot(
    harness,
    snapshot(5, { runs: [run('run-3'), run('run-2')], runsNext: 'run-2', runsTotal: 4 }),
  )

  const loading = harness.sync.loadMore('runs')
  assert.equal(harness.state().history, false, 'history starts only after the older page lands')
  harness.take().resolve(
    snapshot(5, {
      runs: [run('run-1'), run('run-0')],
      runsTotal: 4,
      runsNext: null,
    }),
  )
  await loading
  await harness.flush()
  assert.equal(harness.state().history, true)
  assert.deepEqual(
    harness.state().runs.items.map((r) => r.run_id),
    ['run-3', 'run-2', 'run-1', 'run-0'],
  )
  assert.equal(harness.state().runs.loadedMore, true)

  // While reading history, a fact only raises the "new updates" flag.
  stream.fact(6, ['runs'])
  harness.clock.advance(150)
  assert.equal(harness.calls.length, 2, 'no snapshot while history is active')
  assert.equal(harness.state().hasUpdates, true)

  harness.sync.returnToLatest()
  harness.take().resolve(snapshot(6, { runs: [run('run-9'), run('run-8')] }))
  await harness.flush()

  const state = harness.state()
  assert.equal(state.history, false)
  assert.equal(state.hasUpdates, false)
  assert.deepEqual(state.runs.items.map((r) => r.run_id), ['run-9', 'run-8'])
})

test('a failed history load reports the error without trapping the page in history', async () => {
  const harness = makeHarness()
  await boot(
    harness,
    snapshot(5, { runs: [run('run-3')], runsNext: 'run-3', runsTotal: 2 }),
  )

  const loading = harness.sync.loadMore('runs')
  harness.take().reject(Object.assign(new Error('boom'), { status: 500 }))
  await loading

  assert.equal(harness.state().history, false)
  assert.equal(harness.state().error, '加载更早记录失败，请稍后重试')
  assert.equal(harness.state().status, 'live')
})

test('refreshNow merges a fresh first page without dropping loaded history', async () => {
  const harness = makeHarness()
  await boot(
    harness,
    snapshot(5, { runs: [run('run-3'), run('run-2')], runsNext: 'run-2', runsTotal: 4 }),
  )

  harness.sync.loadMore('runs')
  harness.take().resolve(
    snapshot(5, { runs: [run('run-1'), run('run-0')], runsTotal: 4, runsNext: null }),
  )
  await harness.flush()

  harness.sync.refreshNow()
  const request = harness.take()
  assert.equal(request.query.min_cursor, cursor(5))
  request.resolve(snapshot(6, { runs: [run('run-4')], runsTotal: 5, runsNext: 'run-4' }))
  await harness.flush()

  const list = harness.state().runs
  assert.deepEqual(list.items.map((r) => r.run_id), ['run-4', 'run-3', 'run-2', 'run-1', 'run-0'])
  assert.equal(list.total, 5)
  assert.equal(list.next_after, null, 'the loaded tail wins over the first-page anchor')
  assert.equal(list.loadedMore, true)
})

test('pending approvals replace instead of lingering after resolution', async () => {
  const harness = makeHarness()
  await boot(harness, snapshot(5, { pending: [pending('control-1'), pending('control-2')] }))

  harness.sync.refreshNow()
  harness.take().resolve(snapshot(6, { pending: [pending('control-2')] }))
  await harness.flush()

  assert.deepEqual(
    harness.state().pendingInterventions.items.map((item) => item.control_id),
    ['control-2'],
  )
})

test('resync_required stops the old stream and reopens at the new cursor', async () => {
  const harness = makeHarness()
  const first = await boot(harness, snapshot(5))

  first.control('sl.resync_required')
  assert.equal(first.stopped, true)
  assert.equal(harness.state().status, 'resyncing')
  assert.equal(harness.calls.length, 2)
  assert.equal(harness.calls[1].min_cursor, undefined)

  harness.take().resolve(snapshot(9, { runs: [run('run-9')] }))
  await harness.flush()

  const second = harness.streams.at(-1)
  assert.ok(second)
  assert.notEqual(second, first)
  assert.equal(second.options.after, cursor(9))
  assert.equal(harness.state().cursor, cursor(9))
  assert.equal(harness.state().status, 'live')
})

test('EOF reconnects from the last cursor and replay restores offline changes', async () => {
  const harness = makeHarness()
  const first = await boot(harness, snapshot(5, { runs: [run('run-1')] }))

  first.close('eof')
  assert.equal(harness.state().status, 'reconnecting')
  assert.equal(harness.state().stale, true)

  harness.clock.advance(0)
  const second = harness.streams.at(-1)
  assert.ok(second)
  assert.notEqual(second, first)
  assert.equal(second.options.after, cursor(5))
  second.open()
  assert.equal(harness.state().status, 'live')

  // The server replays everything committed while the page was away.
  second.fact(6, ['runs'])
  harness.clock.advance(150)
  harness.take().resolve(snapshot(6, { runs: [run('run-2'), run('run-1')], runsTotal: 2 }))
  await harness.flush()

  assert.deepEqual(
    harness.state().runs.items.map((r) => r.run_id),
    ['run-2', 'run-1'],
  )
  assert.equal(harness.state().cursor, cursor(6))
})

test('429 honours Retry-After before reconnecting', async () => {
  const harness = makeHarness()
  const first = await boot(harness, snapshot(5))

  first.close('http', 429, 5000)
  harness.clock.advance(4999)
  assert.equal(harness.streams.length, 1, 'must not reconnect early')
  harness.clock.advance(1)
  assert.equal(harness.streams.length, 2)
})

test('repeated failures stop at unavailable and manual retry reloads the snapshot', async () => {
  const harness = makeHarness()
  const first = await boot(harness, snapshot(5))

  let stream = first
  for (let attempt = 0; attempt < 9; attempt += 1) {
    stream.close('error')
    harness.clock.advance(0)
    stream = harness.streams.at(-1) ?? stream
  }
  assert.equal(harness.state().status, 'unavailable')

  harness.sync.retry()
  // Existing data is still shown while the snapshot is re-read.
  assert.equal(harness.state().status, 'reconnecting')
  harness.take().resolve(snapshot(7, { runs: [run('run-7')] }))
  await harness.flush()
  assert.equal(harness.state().status, 'live')
  assert.equal(harness.state().cursor, cursor(7))
})

test('auth_required stops retries; unavailable controls keep data and reconnect', async () => {
  const authHarness = makeHarness()
  const authStream = await boot(authHarness, snapshot(5))
  authStream.control('sl.auth_required')
  assert.equal(authHarness.state().status, 'auth_required')
  authHarness.clock.advance(60_000)
  assert.equal(authHarness.streams.length, 1)
  authHarness.sync.retry()
  assert.equal(authHarness.streams.length, 1, 'auth failures need a real re-login')

  const unavailableHarness = makeHarness()
  const unavailableStream = await boot(unavailableHarness, snapshot(5, { runs: [run('run-1')] }))
  unavailableStream.control('sl.unavailable')
  assert.equal(unavailableStream.stopped, true)
  assert.equal(unavailableHarness.state().stale, true)
  assert.deepEqual(
    unavailableHarness.state().runs.items.map((r) => r.run_id),
    ['run-1'],
  )
  unavailableHarness.clock.advance(0)
  assert.equal(unavailableHarness.streams.length, 2)
})

test('stop releases the stream and ignores late facts and snapshots', async () => {
  const harness = makeHarness()
  const stream = await boot(harness, snapshot(5))
  const cursorBefore = harness.state().cursor

  harness.sync.stop()
  assert.equal(stream.stopped, true)
  assert.equal(harness.state().status, 'stopped')

  stream.fact(6, ['runs'])
  harness.clock.advance(10_000)
  assert.equal(harness.state().cursor, cursorBefore)
  assert.equal(harness.state().status, 'stopped')
  assert.equal(harness.calls.length, 1)
})

test('a fact never changes control state before the snapshot confirms it', async () => {
  const harness = makeHarness()
  const stream = await boot(harness, snapshot(5, { controlState: 'active', controlVersion: 0 }))

  stream.fact(6, ['space'])
  assert.equal(harness.state().space?.control_state, 'active')
  assert.equal(harness.state().space?.control_version, 0)

  harness.clock.advance(150)
  harness.take().resolve(
    snapshot(6, { controlState: 'stopped', controlVersion: 1, runs: [run('run-1', 'running')] }),
  )
  await harness.flush()
  assert.equal(harness.state().space?.control_state, 'stopped')
  assert.equal(harness.state().space?.control_version, 1)
})
