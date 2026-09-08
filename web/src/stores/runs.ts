/**
 * Run-stream store (T3.1 skeleton): owns the SSE subscription for the run the
 * user is currently watching, and exposes its timeline as reactive state.
 *
 * Why the cursor lives here and not in the component: a reconnect has to resume
 * from the last trajectory line, so the cursor must survive the component being
 * re-created (route re-entry, HMR, a panel collapsed and reopened). The store
 * outlives all of those; a component-local ref would replay from zero.
 *
 * Setup-store syntax (rather than the options object) because the live stream
 * handle must stay a plain, non-reactive value — letting Pinia deeply proxy an
 * object holding a ReadableStream reader is a good way to get surprising
 * behaviour out of the reactivity system.
 *
 * Only the skeleton wiring lives here: timeline rendering and the status bar are
 * T3.3/T3.5.
 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { runs as runsApi } from '../api'
import { openRunStream, type SseError, type SseStreamHandle } from '../sse'
import type { ApprovalDecisionValue, RunStatus, SseEvent } from '../types'
import {
  buildApprovalRequest,
  isApprovalResolvedFor,
  type ApprovalRequest,
} from '../utils/approval'
import { interruptInFlight, toolStepStatus, type StepStatus } from '../utils/activity'
import { accumulateUsage, mergeRunMeta, type RunMeta, type UsageTotals } from '../utils/statusbar'
import { useAuthStore } from './auth'

export interface TimelineEntry {
  event: SseEvent
  /** Client-side arrival order, for stable list keys. */
  id: number
}

/**
 * One visible step of the run's reasoning, in arrival order.
 *
 * The chat view renders these instead of only the accumulated answer so the
 * path the agent took — reasoning, intermediate text, tool calls — stays
 * visible the way it is in the terminal, rather than collapsing to the final
 * reply. ``tool`` steps mutate in place: a started call becomes done/error when
 * its result lands.
 */
export interface RunStep {
  id: number
  kind: 'thinking' | 'text' | 'tool'
  turn?: number
  /** Reasoning text (``thinking``) or assistant text (``text``). */
  content?: string
  /** Tool step fields. */
  name?: string
  status?: StepStatus
  input?: unknown
  output?: unknown
  ms?: number
  /** Correlation id pairing a started call with its result. */
  callId?: string
  /** When the call started (epoch ms) — live ``Date.now()``, replay from ``ts``. */
  startedAt?: number
}

export type ConnectionState =
  | 'idle'
  | 'connecting'
  | 'open'
  | 'reconnecting'
  | 'error'
  | 'closed'

export const useRunStreamStore = defineStore('runStream', () => {
  const authStore = useAuthStore()

  const runId = ref<string | null>(null)
  const status = ref<RunStatus | 'idle'>('idle')
  const timeline = ref<TimelineEntry[]>([])
  /** Last trajectory line consumed — the reconnect cursor. */
  const cursor = ref(0)
  const connection = ref<ConnectionState>('idle')
  const lastError = ref<string | null>(null)
  /** Answer text assembled from streamed deltas for the active run. */
  const answer = ref('')
  /** Ordered reasoning/tool steps for the active run. */
  const steps = ref<RunStep[]>([])
  // — status bar (§5.6): run facts + wall clock + token totals —
  const meta = ref<RunMeta>({})
  /** Epoch ms of run_started (live or replay) and of the terminal event. */
  const startedAtMs = ref<number | null>(null)
  const endedAtMs = ref<number | null>(null)
  const usage = ref<UsageTotals>({ prompt: 0, completion: 0, total: 0, cacheRead: 0, cacheWrite: 0 })
  /** Count of steer_queued frames (§6.2) — shown in the status bar. */
  const steerQueued = ref(0)
  /**
   * The approval the dialog must show (P3.2, §6.1), or null when none is
   * pending. Set by ``approval_requested`` and cleared by the matching
   * ``approval_resolved`` — a worker-side gate timeout also emits the latter
   * (fail-closed to reject), so the dialog never stays stuck.
   */
  const pendingApproval = ref<ApprovalRequest | null>(null)
  /**
   * Failed-run reason (§5.7: failures must be traceable). The live SSE carries the
   * outcome but not the *why* — only the persisted run row holds it — so on terminal
   * we reconcile against ``GET /api/runs/{id}`` and also capture any error text a
   * ``run_failed`` frame happened to carry.
   */
  const errorMessage = ref<string | null>(null)
  /** Run working-tree root (§6.4 P2): where inputs/outputs live for this run. */
  const runDir = ref<string | null>(null)

  // Plain (non-reactive) handle to the open stream.
  let handle: SseStreamHandle | null = null
  let nextId = 0
  let nextStepId = 0
  /**
   * Turns whose text arrived as live token fragments. The trajectory replay later
   * re-emits the same turn as one whole record; without this set the answer would
   * be rendered twice (once streamed, once replayed).
   */
  const streamedTurns = new Set<number>()
  /** Turns whose usage has been added to the totals (replay dedup). */
  const usageTurns = new Set<number>()

  const isStreaming = computed(
    () => connection.value === 'connecting' || connection.value === 'open' || connection.value === 'reconnecting',
  )

  /**
   * Open a tool step, reusing an existing one when the same call id arrives
   * twice (a reconnect replays events, and the cursor may resend a frame).
   */
  function upsertToolStep(event: SseEvent): RunStep | undefined {
    const callId = event.tool_call_id
    if (callId) {
      const existing = steps.value.find((s) => s.kind === 'tool' && s.id >= 0 && s.callId === callId)
      if (existing) return existing
    }
    const step: RunStep = {
      id: nextStepId++,
      kind: 'tool',
      turn: event.turn,
      name: typeof event.tool_name === 'string' ? event.tool_name : (event.name ?? 'tool'),
      status: 'running',
      input: event.input,
      callId,
      // Live events are stamped at emit time; replayed ones carry the original
      // trajectory ``ts`` (epoch seconds) so elapsed time stays truthful.
      startedAt: typeof event.ts === 'number' ? event.ts * 1000 : Date.now(),
    }
    steps.value.push(step)
    return step
  }

  /**
   * Append a fragment to the last step of ``kind`` for ``turn``, or open a new one.
   *
   * Live deltas arrive one token at a time, so they must fold into a single
   * growing block instead of each becoming its own step.
   */
  function appendStep(kind: RunStep['kind'], turn: number | undefined, chunk: string): void {
    for (let i = steps.value.length - 1; i >= 0; i--) {
      const step = steps.value[i]
      if (step.kind === kind && step.turn === turn) {
        step.content = (step.content ?? '') + chunk
        return
      }
    }
    steps.value.push({ id: nextStepId++, kind, turn, content: chunk })
  }

  /** Apply one event's effect on the run's visible state. */
  function applyEvent(event: SseEvent): void {
    switch (event.type) {
      case 'run_started':
        status.value = 'running'
        // Status-bar facts: live copy carries pipeline/model/context limit
        // (bridge run_meta), the replayed copy adds tool_names. Fold both.
        meta.value = mergeRunMeta(meta.value, event)
        if (startedAtMs.value === null && typeof event.ts === 'number') {
          startedAtMs.value = event.ts * 1000
        }
        break
      case 'assistant_delta': {
        if (status.value !== 'running') status.value = 'running'
        // Two producers feed this event type and they carry the SAME text:
        //   * live  — one event per token fragment (`text` / `thinking_text`)
        //   * replay — one whole-turn record (`content` / `thinking`, full=true)
        // Dropping the replay copy of any turn already streamed live is what
        // stops the answer from appearing twice.
        const replay = event.full === true
        const turn = event.turn ?? -1
        if (replay && streamedTurns.has(turn)) break

        const thinking = replay ? (event.thinking ?? '') : (event.thinking_text ?? '')
        const text = replay ? (event.content ?? '') : (event.text ?? '')

        if (!replay && (text || thinking)) streamedTurns.add(turn)

        // Per-turn usage rides only on the replayed whole-turn record; count
        // each turn once even if a reconnect replays it again.
        if (replay && event.usage && !usageTurns.has(turn)) {
          usageTurns.add(turn)
          usage.value = accumulateUsage(usage.value, event.usage)
        }

        // Reasoning comes before the visible reply of that turn.
        if (thinking) appendStep('thinking', event.turn, thinking)
        if (text) {
          answer.value += text
          appendStep('text', event.turn, text)
        }
        break
      }
      case 'tool_started':
        if (status.value !== 'running') status.value = 'running'
        upsertToolStep(event)
        break
      case 'tool_finished': {
        if (status.value !== 'running') status.value = 'running'
        const step = upsertToolStep(event)
        if (step) {
          // skipped beats ok: a never-ran call (cap, rejection, safety block)
          // is not a clean success even though the bridge stamps ok: true.
          step.status = toolStepStatus(event)
          step.output = event.output
          step.ms = typeof event.ms === 'number' ? event.ms : undefined
        }
        break
      }
      case 'steer_queued':
        // §6.2: the redacted text rides on the timeline entry; the status bar
        // only shows the count.
        steerQueued.value += 1
        break
      case 'approval_requested':
        // §6.1: park the request for the dialog; the run stays "running".
        pendingApproval.value = buildApprovalRequest(event)
        break
      case 'approval_resolved':
        if (isApprovalResolvedFor(pendingApproval.value, event)) {
          pendingApproval.value = null
        }
        break
      case 'run_completed':
        status.value = 'completed'
        endedAtMs.value = typeof event.ts === 'number' ? event.ts * 1000 : Date.now()
        break
      case 'run_failed':
        status.value = 'failed'
        endedAtMs.value = typeof event.ts === 'number' ? event.ts * 1000 : Date.now()
        if (event.error) errorMessage.value = event.error
        interruptInFlight(steps.value)
        break
      case 'run_stopped':
        status.value = 'stopped'
        endedAtMs.value = typeof event.ts === 'number' ? event.ts * 1000 : Date.now()
        interruptInFlight(steps.value)
        break
      default:
        break
    }
  }

  /** Reconcile the status when the stream ends without a terminal frame. */
  function settleStatus(): void {
    if (status.value === 'running' || status.value === 'queued') {
      status.value = 'completed'
    }
  }

  function close(): void {
    if (handle) {
      handle.stop()
      handle = null
    }
    if (connection.value !== 'error') connection.value = 'idle'
  }

  /**
   * Subscribe to a run's event stream, resuming from ``after`` when given.
   *
   * Calling this while another stream is open replaces it — one run watched at a
   * time is the product shape, and leaking the old stream would keep a dead
   * fetch alive for the whole session.
   */
  function watch(id: string, after?: number): void {
    close()
    runId.value = id
    status.value = 'queued'
    timeline.value = []
    answer.value = ''
    // Only reset the step buffer on a fresh subscribe: a reconnect passes
    // ``after`` and would otherwise re-append frames it had already rendered.
    if (!after) {
      steps.value = []
      nextStepId = 0
      streamedTurns.clear()
      usageTurns.clear()
      meta.value = {}
      usage.value = { prompt: 0, completion: 0, total: 0, cacheRead: 0, cacheWrite: 0 }
      steerQueued.value = 0
      pendingApproval.value = null
      errorMessage.value = null
      runDir.value = null
      startedAtMs.value = null
      endedAtMs.value = null
    }
    lastError.value = null
    cursor.value = typeof after === 'number' ? after : 0
    nextId = 0
    connection.value = 'connecting'

    handle = openRunStream({
      url: runsApi.eventsUrl(id),
      // Getter, so a token refreshed mid-run is used by the next reconnect.
      token: () => authStore.token,
      after: cursor.value,
      onOpen: () => {
        connection.value = 'open'
        lastError.value = null
      },
      onCursor: (value) => {
        cursor.value = value
      },
      onEvent: (event) => {
        timeline.value.push({ event, id: nextId++ })
        applyEvent(event)
      },
      onError: (err: SseError) => {
        lastError.value = err.message
        connection.value = 'error'
      },
      onDone: (reason) => {
        handle = null
        if (reason === 'completed') {
          connection.value = 'closed'
          settleStatus()
        } else if (reason === 'aborted') {
          connection.value = 'idle'
        } else {
          connection.value = 'error'
        }
        // The stream is best-effort and never carries a failed run's *reason*
        // (only the persisted row does), so reconcile against the authoritative
        // run view before declaring the outcome final (§5.7 / §6.4 P2).
        void reconcile()
      },
    })
  }

  /** Re-open the current stream from the saved cursor (manual "retry"). */
  function retry(): void {
    if (runId.value) watch(runId.value, cursor.value)
  }

  /**
   * Reconcile the watched run against ``GET /api/runs/{id}`` (§6.4 P2 + §5.7).
   *
   * Two things the live stream cannot give us:
   *   * a failed run's *reason* — it lives only on the persisted row; and
   *   * the run's working-tree root, so the detail view can show where the
   *     outputs/inputs actually landed.
   * Fire-and-forget from ``onDone``: it only enriches an already-finished run.
   */
  async function reconcile(): Promise<void> {
    if (!runId.value) return
    try {
      const summary = await runsApi.get(runId.value)
      if (runDir.value === null) runDir.value = summary.run_dir ?? null
      if (summary.status) status.value = summary.status as RunStatus
      const reason = summary.error || (summary.stopped_by ? `已停止（${summary.stopped_by}）` : null)
      if (reason) errorMessage.value = reason
      if (summary.usage) {
        usage.value = accumulateUsage(usage.value, summary.usage)
      }
    } catch {
      // Non-fatal: the SSE outcome already stands; the detail view simply lacks
      // the run directory, and a failed run keeps its banner-less status.
    }
  }

  async function stop(): Promise<void> {
    if (!runId.value) return
    try {
      await runsApi.stop(runId.value)
    } catch {
      // A 409 ("run not running") means it already finished; the stream carries
      // the terminal frame either way, so there is nothing to surface.
    }
  }

  /**
   * Answer the pending approval (P3.2, §6.1). The dialog is cleared by the
   * worker's ``approval_resolved`` echo — the authoritative signal — not here,
   * so a failed POST (409 race, network) leaves the dialog up for a retry.
   * The hard-denial overlay lives server-side: a decision that fsguard would
   * veto is dropped there and the request simply stays pending.
   */
  async function approve(
    approvalId: string,
    decision: ApprovalDecisionValue,
    replacementCommand?: string,
  ): Promise<void> {
    if (!runId.value) return
    await runsApi.approve(runId.value, approvalId, decision, replacementCommand)
  }

  function reset(): void {
    close()
    runId.value = null
    status.value = 'idle'
    timeline.value = []
    steps.value = []
    nextStepId = 0
    streamedTurns.clear()
    usageTurns.clear()
    meta.value = {}
    usage.value = { prompt: 0, completion: 0, total: 0, cacheRead: 0, cacheWrite: 0 }
    steerQueued.value = 0
    pendingApproval.value = null
    errorMessage.value = null
    runDir.value = null
    startedAtMs.value = null
    endedAtMs.value = null
    cursor.value = 0
    answer.value = ''
    lastError.value = null
    connection.value = 'idle'
  }

  return {
    runId,
    status,
    timeline,
    steps,
    cursor,
    connection,
    lastError,
    answer,
    meta,
    usage,
    steerQueued,
    pendingApproval,
    errorMessage,
    runDir,
    startedAtMs,
    endedAtMs,
    isStreaming,
    watch,
    retry,
    stop,
    approve,
    close,
    reset,
    applyEvent,
  }
})
