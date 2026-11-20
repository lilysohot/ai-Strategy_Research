/**
 * Super-link space state machine (SSE-T04).
 *
 * Contract: take one consistent snapshot, subscribe to `/events` with that
 * cursor, and treat every fact as an invalidation hint rather than as the new
 * state. Facts advance the cursor; the affected views are re-read from the
 * snapshot endpoint and merged so that already-loaded history survives.
 *
 * This module is deliberately framework-free: `useSpaceSync.ts` binds it to
 * Vue, the auth token and `fetch`. Everything here can be exercised with fake
 * snapshots, a fake stream and fake timers — which is how stale responses,
 * reconnects and resyncs are tested without a server.
 */

import type {
  Delivery,
  LinkRun,
  Participant,
  RecoveryRecord,
  SnapshotPage,
  SnapshotQuery,
  Space,
  SpaceSnapshot,
} from '../api/superLink.ts'
import type { RunControlRecord } from '../types.ts'
import type {
  SpaceControlEvent,
  SpaceFact,
  SpaceStreamCallbacks,
  SpaceStreamHandle,
  StreamCloseInfo,
} from './stream.ts'

export type SyncStatus =
  | 'idle'
  | 'loading'
  | 'live'
  | 'reconnecting'
  | 'resyncing'
  | 'unavailable'
  | 'auth_required'
  | 'not_found'
  | 'stopped'

/** Lists that support "load older" in T04. Pending approvals always replace. */
export type ListKind = 'runs' | 'deliveries' | 'actions'
export type InvalidateView =
  | 'space'
  | 'participants'
  | 'runs'
  | 'deliveries'
  | 'interventions'
  | 'actions'

export interface SyncList<T> {
  items: T[]
  total: number
  next_after: string | null
  loadedMore: boolean
}

export interface SpaceSyncState {
  status: SyncStatus
  /** True when the last confirmed state is not live but still displayed. */
  stale: boolean
  error: string
  cursor: string | null
  epoch: string | null
  seq: number
  asOf: string | null
  space: Space | null
  participants: Participant[]
  runs: SyncList<LinkRun>
  deliveries: SyncList<Delivery>
  pendingInterventions: SyncList<RunControlRecord>
  actions: SyncList<RecoveryRecord>
  activeRunIds: string[]
  /** The user is reading older pages; live merges are deferred. */
  history: boolean
  hasUpdates: boolean
  /** Local time of the last accepted snapshot, not a business timestamp. */
  updatedAt: number | null
}

export interface SpaceCursorParts {
  spaceId: string
  epoch: string
  seq: number
}

export interface SyncTiming {
  setTimeout?: (handler: () => void, ms: number) => unknown
  clearTimeout?: (handle: unknown) => void
  now?: () => number
  random?: () => number
}

/** The URL and auth token are bound by `useSpaceSync`; the engine owns the rest. */
export interface SpaceStreamRequest {
  after: string
  callbacks: SpaceStreamCallbacks
}

export interface SpaceSyncDeps {
  spaceId: string
  loadSnapshot: (query: SnapshotQuery) => Promise<SpaceSnapshot>
  openStream: (options: SpaceStreamRequest) => SpaceStreamHandle
  onState: (state: SpaceSyncState) => void
  timing?: SyncTiming
}

export interface SpaceSync {
  start: () => void
  stop: () => void
  /** Manual recovery after `unavailable`; re-reads the full snapshot. */
  retry: () => void
  /** Merge all lists without leaving history (used after control actions). */
  refreshNow: () => void
  /** Leave history and rebuild the first page from a fresh snapshot. */
  returnToLatest: () => void
  loadMore: (kind: ListKind) => Promise<void>
  getState: () => SpaceSyncState
}

const FIRST_PAGE_LIMIT = 50
const REFRESH_DEBOUNCE_MS = 150
const MAX_FAILURES = 8
const BASE_BACKOFF_MS = 500
const MAX_BACKOFF_MS = 15_000

const MSG_AUTH = '登录状态已失效，请重新登录'
const MSG_NOT_FOUND = '未找到这个协作空间，或你没有访问权限'
const MSG_DISABLED = 'Super-link 尚未启用，原有工作台可正常使用'
const MSG_SYNC_INTERRUPTED = '状态同步暂时中断，显示最近一次记录'
const MSG_UNAVAILABLE = '状态同步暂不可用，请稍后重试'

const ALL_VIEWS: readonly InvalidateView[] = [
  'space',
  'participants',
  'runs',
  'deliveries',
  'interventions',
  'actions',
]
const VIEW_SET: ReadonlySet<string> = new Set(ALL_VIEWS)

function emptyList<T>(): SyncList<T> {
  return { items: [], total: 0, next_after: null, loadedMore: false }
}

/** A state value with no space loaded; the view swaps in a fresh one. */
export function emptySpaceSyncState(): SpaceSyncState {
  return {
    status: 'idle',
    stale: false,
    error: '',
    cursor: null,
    epoch: null,
    seq: -1,
    asOf: null,
    space: null,
    participants: [],
    runs: emptyList(),
    deliveries: emptyList(),
    pendingInterventions: emptyList(),
    actions: emptyList(),
    activeRunIds: [],
    history: false,
    hasUpdates: false,
    updatedAt: null,
  }
}

/** Parse `sl1:<space>:<epoch>:<seq>`, optionally enforcing the space. */
export function parseSpaceCursor(
  cursor: string,
  expectedSpace?: string,
): SpaceCursorParts | null {
  if (typeof cursor !== 'string' || !cursor.startsWith('sl1:')) return null
  const parts = cursor.slice(4).split(':')
  if (parts.length !== 3) return null
  const [spaceId, epoch, seqText] = parts
  if (!spaceId || !epoch || !/^\d+$/.test(seqText)) return null
  const seq = Number(seqText)
  if (!Number.isSafeInteger(seq) || seq < 0) return null
  if (expectedSpace && spaceId !== expectedSpace) return null
  return { spaceId, epoch, seq }
}

function readError(error: unknown): {
  status: number
  detail: string
  retryAfterMs?: number
} {
  const record = (error ?? {}) as {
    status?: unknown
    detail?: unknown
    retryAfterMs?: unknown
  }
  const status = typeof record.status === 'number' ? record.status : 0
  let detail = ''
  if (typeof record.detail === 'string') {
    detail = record.detail
  } else if (record.detail && typeof record.detail === 'object') {
    const code = (record.detail as { code?: unknown }).code
    if (typeof code === 'string') detail = code
  }
  const retryAfterMs =
    typeof record.retryAfterMs === 'number' && record.retryAfterMs >= 0
      ? record.retryAfterMs
      : undefined
  return { status, detail, retryAfterMs }
}

function mergeFirstPage<T>(
  current: SyncList<T>,
  page: SnapshotPage<T>,
  key: (item: T) => string,
): SyncList<T> {
  const fresh = new Set(page.items.map(key))
  return {
    items: [...page.items, ...current.items.filter((item) => !fresh.has(key(item)))],
    total: page.total,
    next_after: current.loadedMore ? current.next_after : page.next_after,
    loadedMore: current.loadedMore,
  }
}

function appendPage<T>(
  current: SyncList<T>,
  page: SnapshotPage<T>,
  key: (item: T) => string,
): SyncList<T> {
  const seen = new Set(current.items.map(key))
  const appended = page.items.filter((item) => !seen.has(key(item)))
  return {
    items: [...current.items, ...appended],
    total: page.total,
    next_after: page.next_after,
    loadedMore: true,
  }
}

function copyState(state: SpaceSyncState): SpaceSyncState {
  return {
    ...state,
    participants: [...state.participants],
    runs: { ...state.runs, items: [...state.runs.items] },
    deliveries: { ...state.deliveries, items: [...state.deliveries.items] },
    pendingInterventions: {
      ...state.pendingInterventions,
      items: [...state.pendingInterventions.items],
    },
    actions: { ...state.actions, items: [...state.actions.items] },
    activeRunIds: [...state.activeRunIds],
  }
}

export function createSpaceSync(deps: SpaceSyncDeps): SpaceSync {
  const { spaceId, loadSnapshot, openStream, onState, timing = {} } = deps
  const setTimer =
    timing.setTimeout ?? ((handler: () => void, ms: number) => setTimeout(handler, ms))
  const clearTimer =
    timing.clearTimeout ?? ((handle: unknown) => clearTimeout(handle as ReturnType<typeof setTimeout>))
  const now = timing.now ?? (() => Date.now())
  const random = timing.random ?? Math.random

  const state = emptySpaceSyncState()
  let stopped = true
  let generation = 0
  let stream: SpaceStreamHandle | null = null
  let streamToken = 0
  let streamOpen = false

  let dirty = new Set<InvalidateView>()
  let refreshTimer: unknown = null
  let retryTimer: unknown = null
  let fullRequestSeq = 0
  let latestFullRequest = 0
  let replaceSeq = 0
  const moreSeq: Record<ListKind, number> = { runs: 0, deliveries: 0, actions: 0 }
  let attempts = 0
  let refreshFailures = 0
  let resyncInFlight = false

  const alive = (gen: number) => !stopped && gen === generation

  function emit() {
    onState(copyState(state))
  }

  function clearTimers() {
    if (refreshTimer !== null) {
      clearTimer(refreshTimer)
      refreshTimer = null
    }
    if (retryTimer !== null) {
      clearTimer(retryTimer)
      retryTimer = null
    }
  }

  function closeStream() {
    streamToken += 1
    if (stream) {
      stream.stop()
      stream = null
    }
    streamOpen = false
  }

  function shutdown(status: 'auth_required' | 'not_found' | 'unavailable', message: string) {
    closeStream()
    clearTimers()
    dirty = new Set()
    resyncInFlight = false
    state.status = status
    state.stale = state.space !== null
    state.error = message
    emit()
  }

  function delayFor(attempt: number, forced?: number): number {
    if (forced !== undefined) return forced
    const ceiling = Math.min(MAX_BACKOFF_MS, BASE_BACKOFF_MS * 2 ** attempt)
    return Math.floor(random() * ceiling)
  }

  function scheduleRefresh(delay = REFRESH_DEBOUNCE_MS) {
    if (stopped || refreshTimer !== null) return
    refreshTimer = setTimer(() => {
      refreshTimer = null
      void refreshDirty()
    }, delay)
  }

  function requeue(scopes: Set<InvalidateView>) {
    for (const scope of scopes) dirty.add(scope)
  }

  function normalizeScopes(raw: unknown): Set<InvalidateView> {
    const scopes = new Set<InvalidateView>()
    if (Array.isArray(raw)) {
      for (const item of raw) {
        if (typeof item === 'string' && VIEW_SET.has(item)) {
          scopes.add(item as InvalidateView)
        }
      }
    }
    if (scopes.size === 0) {
      // A fact without hints still means committed state changed; refresh the
      // views that change most often rather than silently ignoring it.
      scopes.add('space')
      scopes.add('runs')
      scopes.add('deliveries')
    }
    return scopes
  }

  function snapshotCursor(snapshot: SpaceSnapshot): SpaceCursorParts | null {
    if (!snapshot || snapshot.schema_version !== 1) return null
    if (!snapshot.space || snapshot.space.space_id !== spaceId) return null
    return parseSpaceCursor(snapshot.cursor, spaceId)
  }

  function applyReplace(snapshot: SpaceSnapshot, parsed: SpaceCursorParts) {
    state.cursor = snapshot.cursor
    state.epoch = parsed.epoch
    state.seq = parsed.seq
    state.asOf = snapshot.as_of
    state.space = snapshot.space
    state.participants = [...snapshot.participants]
    state.runs = {
      items: [...snapshot.runs.items],
      total: snapshot.runs.total,
      next_after: snapshot.runs.next_after,
      loadedMore: false,
    }
    state.deliveries = {
      items: [...snapshot.deliveries.items],
      total: snapshot.deliveries.total,
      next_after: snapshot.deliveries.next_after,
      loadedMore: false,
    }
    state.pendingInterventions = {
      items: [...snapshot.pending_interventions.items],
      total: snapshot.pending_interventions.total,
      next_after: snapshot.pending_interventions.next_after,
      loadedMore: false,
    }
    state.actions = {
      items: [...snapshot.actions.items],
      total: snapshot.actions.total,
      next_after: snapshot.actions.next_after,
      loadedMore: false,
    }
    state.activeRunIds = [...snapshot.active_run_ids]
    state.history = false
    state.hasUpdates = false
    state.updatedAt = now()
    replaceSeq += 1
    dirty = new Set()
  }

  function applyRefresh(snapshot: SpaceSnapshot, parsed: SpaceCursorParts, scopes: Set<InvalidateView>) {
    if (parsed.seq > state.seq) {
      state.cursor = snapshot.cursor
      state.epoch = parsed.epoch
      state.seq = parsed.seq
    }
    state.asOf = snapshot.as_of
    state.updatedAt = now()
    if (scopes.has('space')) {
      state.space = snapshot.space
    }
    if (scopes.has('participants')) {
      state.participants = [...snapshot.participants]
    }
    if (scopes.has('runs')) {
      state.runs = mergeFirstPage(state.runs, snapshot.runs, (run) => run.run_id)
      state.activeRunIds = [...snapshot.active_run_ids]
    }
    if (scopes.has('deliveries')) {
      state.deliveries = mergeFirstPage(
        state.deliveries,
        snapshot.deliveries,
        (delivery) => delivery.message_id,
      )
    }
    if (scopes.has('interventions')) {
      // Pending approvals are a live queue, not history: replace the page so a
      // resolved item never lingers just because it was loaded earlier.
      state.pendingInterventions = {
        items: [...snapshot.pending_interventions.items],
        total: snapshot.pending_interventions.total,
        next_after: snapshot.pending_interventions.next_after,
        loadedMore: false,
      }
    }
    if (scopes.has('actions')) {
      state.actions = mergeFirstPage(
        state.actions,
        snapshot.actions,
        (action) => action.id,
      )
    }
  }

  function syntheticSnapshotError(): Error {
    return Object.assign(new Error('snapshot contract mismatch'), { status: 503 })
  }

  async function loadInitial(gen: number): Promise<void> {
    const request = ++fullRequestSeq
    latestFullRequest = request
    state.status = state.space ? 'reconnecting' : 'loading'
    state.error = ''
    emit()
    try {
      const snapshot = await loadSnapshot({ limit: FIRST_PAGE_LIMIT })
      if (!alive(gen) || request !== latestFullRequest) return
      const parsed = snapshotCursor(snapshot)
      if (!parsed) throw syntheticSnapshotError()
      applyReplace(snapshot, parsed)
      attempts = 0
      refreshFailures = 0
      resyncInFlight = false
      state.status = 'live'
      state.stale = false
      state.error = ''
      emit()
      openStreamConnection()
    } catch (error) {
      if (!alive(gen)) return
      handleSnapshotFailure(error, true)
    }
  }

  function handleSnapshotFailure(error: unknown, initial: boolean) {
    const info = readError(error)
    if (info.status === 401 || info.status === 403) {
      shutdown('auth_required', MSG_AUTH)
      return
    }
    if (info.status === 404) {
      shutdown(
        'not_found',
        info.detail === 'super_link_disabled' ? MSG_DISABLED : MSG_NOT_FOUND,
      )
      return
    }
    if (info.status === 400 || info.status === 410) {
      if (!initial) {
        requestResync()
        return
      }
    }
    if (info.status === 429 || info.status === 503 || info.status === 0) {
      scheduleReconnect(info.retryAfterMs)
      return
    }
    shutdown('unavailable', MSG_UNAVAILABLE)
  }

  function scheduleReconnect(forcedDelay?: number) {
    if (stopped || retryTimer !== null) return
    attempts += 1
    if (attempts > MAX_FAILURES) {
      state.status = 'unavailable'
      state.stale = state.space !== null
      state.error = MSG_UNAVAILABLE
      emit()
      return
    }
    if (state.space) {
      state.status = 'reconnecting'
      state.stale = true
      state.error = MSG_SYNC_INTERRUPTED
    } else {
      state.status = 'loading'
      state.error = MSG_SYNC_INTERRUPTED
    }
    emit()
    retryTimer = setTimer(() => {
      retryTimer = null
      reconnectNow()
    }, delayFor(attempts - 1, forcedDelay))
  }

  function reconnectNow() {
    if (stopped || resyncInFlight) return
    if (!state.space || !state.cursor) {
      void loadInitial(generation)
      return
    }
    openStreamConnection()
  }

  function openStreamConnection() {
    if (stopped || !state.cursor) return
    closeStream()
    const gen = generation
    const token = ++streamToken
    const guarded = <T extends unknown[]>(handler: (...args: T) => void) =>
      (...args: T) => {
        if (alive(gen) && token === streamToken) handler(...args)
      }
    const callbacks: SpaceStreamCallbacks = {
      onFact: guarded(handleFact),
      onControl: guarded(handleControl),
      onOpen: guarded(handleOpen),
      onClose: guarded((info: StreamCloseInfo) => {
        stream = null
        handleStreamClosed(info)
      }),
    }
    try {
      stream = openStream({ after: state.cursor, callbacks })
    } catch (error) {
      stream = null
      handleStreamClosed({ reason: 'error', cause: error })
    }
  }

  function handleOpen() {
    streamOpen = true
    attempts = 0
    refreshFailures = 0
    if (state.space) {
      state.status = 'live'
      state.stale = false
      state.error = ''
    }
    if (dirty.size > 0 && !state.history) scheduleRefresh(0)
    emit()
  }

  function handleStreamClosed(info: StreamCloseInfo) {
    streamOpen = false
    if (stopped) return
    if (info.reason === 'http') {
      if (info.status === 401 || info.status === 403) {
        shutdown('auth_required', MSG_AUTH)
        return
      }
      if (info.status === 404) {
        shutdown('not_found', MSG_NOT_FOUND)
        return
      }
      if (info.status === 400 || info.status === 410) {
        requestResync()
        return
      }
      if (info.status === 429) {
        scheduleReconnect(info.retryAfterMs)
        return
      }
    }
    // EOF (including the 5-minute max age), network errors and 5xx all mean
    // "reconnect from the last cursor"; none of them is a business failure.
    scheduleReconnect(info.retryAfterMs)
  }

  function handleControl(event: SpaceControlEvent, _reason: string) {
    if (event === 'sl.auth_required') {
      shutdown('auth_required', MSG_AUTH)
      return
    }
    if (event === 'sl.resync_required') {
      requestResync()
      return
    }
    closeStream()
    scheduleReconnect()
  }

  function handleFact(fact: SpaceFact) {
    if (state.status === 'auth_required' || state.status === 'not_found') return
    if (fact.schema_version !== 1) return
    if (fact.space_id !== spaceId) return
    if (typeof fact.cursor !== 'string') return
    const parsed = parseSpaceCursor(fact.cursor, spaceId)
    if (!parsed) return
    if (fact.stream_epoch !== undefined && fact.stream_epoch !== parsed.epoch) return
    if (fact.seq !== undefined && Number(fact.seq) !== parsed.seq) return
    if (state.epoch && parsed.epoch !== state.epoch) {
      requestResync()
      return
    }
    if (parsed.seq <= state.seq) return

    state.cursor = fact.cursor
    state.epoch = parsed.epoch
    state.seq = parsed.seq
    const scopes = normalizeScopes(fact.invalidate)
    for (const scope of scopes) dirty.add(scope)
    if (state.history) {
      if (!state.hasUpdates) {
        state.hasUpdates = true
        emit()
      }
      return
    }
    scheduleRefresh()
  }

  async function refreshDirty(): Promise<void> {
    if (stopped || resyncInFlight) return
    if (!state.space || !state.cursor) return
    if (state.history) {
      if (dirty.size > 0 && !state.hasUpdates) {
        state.hasUpdates = true
        emit()
      }
      return
    }
    if (dirty.size === 0) return
    const scopes = new Set(dirty)
    dirty = new Set()
    await loadRefresh(scopes, false)
  }

  async function loadRefresh(scopes: Set<InvalidateView>, force: boolean): Promise<void> {
    if (!state.cursor) return
    const gen = generation
    const request = ++fullRequestSeq
    latestFullRequest = request
    try {
      const snapshot = await loadSnapshot({
        min_cursor: state.cursor,
        limit: FIRST_PAGE_LIMIT,
      })
      if (!alive(gen) || request !== latestFullRequest) return
      const parsed = snapshotCursor(snapshot)
      if (!parsed) {
        requestResync()
        return
      }
      if (state.epoch && parsed.epoch !== state.epoch) {
        requestResync()
        return
      }
      if (parsed.seq < state.seq) {
        // A slow response that predates the current cursor is discarded whole.
        if (!force) {
          requeue(scopes)
          scheduleRefresh()
        }
        return
      }
      applyRefresh(snapshot, parsed, scopes)
      refreshFailures = 0
      state.status = 'live'
      state.stale = false
      state.error = ''
      if (force && dirty.size === 0) state.hasUpdates = false
      emit()
    } catch (error) {
      if (!alive(gen)) return
      const info = readError(error)
      if (info.status === 401 || info.status === 403) {
        shutdown('auth_required', MSG_AUTH)
        return
      }
      if (info.status === 404) {
        shutdown(
          'not_found',
          info.detail === 'super_link_disabled' ? MSG_DISABLED : MSG_NOT_FOUND,
        )
        return
      }
      if (info.status === 400 || info.status === 410) {
        requeue(scopes)
        requestResync()
        return
      }
      requeue(scopes)
      refreshFailures += 1
      if (refreshFailures >= MAX_FAILURES) {
        shutdown('unavailable', MSG_UNAVAILABLE)
        return
      }
      state.stale = state.space !== null
      state.error = MSG_SYNC_INTERRUPTED
      emit()
      scheduleRefresh(
        info.retryAfterMs ?? Math.min(MAX_BACKOFF_MS, BASE_BACKOFF_MS * 2 ** (refreshFailures - 1)),
      )
    }
  }

  function requestResync() {
    if (stopped || resyncInFlight) return
    resyncInFlight = true
    closeStream()
    clearTimers()
    dirty = new Set()
    state.status = 'resyncing'
    state.stale = state.space !== null
    state.error = ''
    emit()
    void runResync()
  }

  async function runResync(): Promise<void> {
    const gen = generation
    const request = ++fullRequestSeq
    latestFullRequest = request
    try {
      const snapshot = await loadSnapshot({ limit: FIRST_PAGE_LIMIT })
      if (!alive(gen) || request !== latestFullRequest) return
      const parsed = snapshotCursor(snapshot)
      if (!parsed) throw syntheticSnapshotError()
      applyReplace(snapshot, parsed)
      resyncInFlight = false
      attempts = 0
      refreshFailures = 0
      state.status = 'live'
      state.stale = false
      state.error = ''
      emit()
      openStreamConnection()
    } catch (error) {
      if (!alive(gen)) return
      resyncInFlight = false
      const info = readError(error)
      if (info.status === 401 || info.status === 403) {
        shutdown('auth_required', MSG_AUTH)
        return
      }
      if (info.status === 404) {
        shutdown(
          'not_found',
          info.detail === 'super_link_disabled' ? MSG_DISABLED : MSG_NOT_FOUND,
        )
        return
      }
      attempts += 1
      if (attempts > MAX_FAILURES) {
        shutdown('unavailable', MSG_UNAVAILABLE)
        return
      }
      state.status = 'reconnecting'
      state.stale = state.space !== null
      state.error = MSG_SYNC_INTERRUPTED
      emit()
      retryTimer = setTimer(() => {
        retryTimer = null
        if (!stopped && !resyncInFlight) requestResync()
      }, delayFor(attempts - 1, info.retryAfterMs))
    }
  }

  function start(): void {
    if (!stopped) return
    stopped = false
    generation += 1
    state.status = 'loading'
    state.stale = false
    state.error = ''
    emit()
    void loadInitial(generation)
  }

  function stop(): void {
    if (stopped) return
    stopped = true
    generation += 1
    resyncInFlight = false
    closeStream()
    clearTimers()
    dirty = new Set()
    state.status = 'stopped'
    state.error = ''
    emit()
  }

  function retry(): void {
    if (stopped) {
      start()
      return
    }
    if (resyncInFlight) return
    if (state.status === 'auth_required' || state.status === 'not_found') return
    attempts = 0
    refreshFailures = 0
    void loadInitial(generation)
  }

  function refreshNow(): void {
    if (stopped || resyncInFlight || !state.space || !state.cursor) return
    const scopes = new Set<InvalidateView>(ALL_VIEWS)
    void loadRefresh(scopes, true)
  }

  async function returnToLatest(): Promise<void> {
    if (stopped || resyncInFlight || !state.space) return
    state.history = false
    state.hasUpdates = false
    emit()
    const gen = generation
    const request = ++fullRequestSeq
    latestFullRequest = request
    try {
      const snapshot = await loadSnapshot({ limit: FIRST_PAGE_LIMIT })
      if (!alive(gen) || request !== latestFullRequest) return
      const parsed = snapshotCursor(snapshot)
      if (!parsed) {
        requestResync()
        return
      }
      applyReplace(snapshot, parsed)
      if (streamOpen) {
        state.status = 'live'
        state.stale = false
        state.error = ''
      } else {
        state.status = 'reconnecting'
        state.stale = true
        state.error = MSG_SYNC_INTERRUPTED
      }
      emit()
      if (!streamOpen) scheduleReconnect()
    } catch (error) {
      if (!alive(gen)) return
      handleSnapshotFailure(error, false)
    }
  }

  async function loadMoreList(kind: ListKind): Promise<void> {
    if (stopped || resyncInFlight || !state.space) return
    const current =
      kind === 'runs'
        ? state.runs
        : kind === 'deliveries'
          ? state.deliveries
          : state.actions
    if (!current.next_after) return

    const gen = generation
    const request = ++moreSeq[kind]
    const replaceMark = replaceSeq
    const query: SnapshotQuery = { limit: FIRST_PAGE_LIMIT }
    if (kind === 'runs') query.runs_after = current.next_after ?? undefined
    else if (kind === 'deliveries') query.deliveries_after = current.next_after ?? undefined
    else query.actions_after = current.next_after ?? undefined

    try {
      const snapshot = await loadSnapshot(query)
      if (!alive(gen) || request !== moreSeq[kind]) return
      if (replaceMark !== replaceSeq) return
      const parsed = snapshotCursor(snapshot)
      if (!parsed) return
      if (state.epoch && parsed.epoch !== state.epoch) {
        requestResync()
        return
      }
      if (kind === 'runs') {
        state.runs = appendPage(state.runs, snapshot.runs, (run) => run.run_id)
      } else if (kind === 'deliveries') {
        state.deliveries = appendPage(
          state.deliveries,
          snapshot.deliveries,
          (delivery) => delivery.message_id,
        )
      } else {
        state.actions = appendPage(state.actions, snapshot.actions, (action) => action.id)
      }
      state.history = true
      state.updatedAt = now()
      state.error = ''
      emit()
    } catch (error) {
      if (!alive(gen)) return
      const info = readError(error)
      if (info.status === 401 || info.status === 403) {
        shutdown('auth_required', MSG_AUTH)
        return
      }
      state.error = '加载更早记录失败，请稍后重试'
      emit()
    }
  }

  return {
    start,
    stop,
    retry,
    refreshNow,
    returnToLatest: () => {
      void returnToLatest()
    },
    loadMore: (kind) => loadMoreList(kind),
    getState: () => copyState(state),
  }
}
