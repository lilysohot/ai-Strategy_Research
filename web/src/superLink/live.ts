/**
 * Live run output for Super-link space streams (SSE-T05).
 *
 * Previews are display-only and explicitly lossy. They never advance the
 * durable space cursor and never determine run status; the archived trace at
 * `/api/runs/{id}/trace` is authoritative once a turn or run is saved.
 *
 * Pure functions keep the merge rules testable without Vue. The sync state
 * machine owns the connection lifecycle and calls ``applyPreview`` /
 * ``applyReset``; the run detail view calls ``visibleBlocks`` to avoid showing
 * a live block that the archive already contains.
 */

import type { RunTraceRecord } from '../types.ts'
import type { SpaceOutputReset, SpacePreview } from './stream.ts'

export type LiveBlockKind = 'content' | 'thinking' | 'tool' | 'notice'

export const MAX_LIVE_BLOCK_CHARS = 500_000
export const MAX_LIVE_RUNS = 8

export interface LiveTool {
  call_id: string
  name: string
  state: 'started' | 'finished'
  ok?: boolean
  skipped?: boolean
  detail?: string
  ms?: number | null
}

export interface LiveBlock {
  key: string
  kind: LiveBlockKind
  agent_id: string
  agent_kind: string
  turn: number | null
  text: string
  tool?: LiveTool
  truncated?: boolean
}

export interface RunLiveOutput {
  run_id: string
  lastSeq: number
  active: boolean
  terminalStatus?: string
  /** Fragments are missing; reload the archived trace before trusting text. */
  needsArchive: boolean
  blocks: LiveBlock[]
}

export interface LiveState {
  epoch: string | null
  runs: Record<string, RunLiveOutput>
}

export function emptyLiveState(): LiveState {
  return { epoch: null, runs: {} }
}

export function cloneLive(live: LiveState): LiveState {
  const runs: Record<string, RunLiveOutput> = {}
  for (const [runId, run] of Object.entries(live.runs)) {
    runs[runId] = {
      ...run,
      blocks: run.blocks.map((block) => ({
        ...block,
        ...(block.tool ? { tool: { ...block.tool } } : {}),
      })),
    }
  }
  return { epoch: live.epoch, runs }
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function asTurn(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function isKind(value: unknown): value is LiveBlockKind {
  return (
    value === 'content' ||
    value === 'thinking' ||
    value === 'tool' ||
    value === 'notice'
  )
}

function newRun(runId: string): RunLiveOutput {
  return {
    run_id: runId,
    lastSeq: 0,
    active: true,
    needsArchive: false,
    blocks: [],
  }
}

function pruneRuns(live: LiveState): void {
  const ids = Object.keys(live.runs)
  if (ids.length <= MAX_LIVE_RUNS) return
  const removable = ids.filter((id) => {
    const run = live.runs[id]
    return !run.active && !run.needsArchive
  })
  const ordered = [...removable, ...ids.filter((id) => !removable.includes(id))]
  for (const id of ordered) {
    if (Object.keys(live.runs).length <= MAX_LIVE_RUNS) break
    delete live.runs[id]
  }
}

function appendText(block: LiveBlock, text: string): void {
  if (!text || block.truncated) return
  const room = MAX_LIVE_BLOCK_CHARS - block.text.length
  if (room <= 0) {
    block.truncated = true
    return
  }
  block.text += text.slice(0, room)
  if (text.length > room) block.truncated = true
}

function findBlock(
  run: RunLiveOutput,
  key: string,
  kind: LiveBlockKind,
  agentId: string,
  agentKind: string,
  turn: number | null,
): LiveBlock {
  const existing = run.blocks.find((block) => block.key === key)
  if (existing) return existing
  const block: LiveBlock = {
    key,
    kind,
    agent_id: agentId,
    agent_kind: agentKind,
    turn,
    text: '',
  }
  run.blocks.push(block)
  return block
}

/**
 * Merge one preview frame. Returns true when the live model changed.
 *
 * A per-run sequence gap means at least one fragment was lost. The affected
 * run is cleared and marked for archive reload; the current frame becomes the
 * new baseline. Text is never appended across a gap.
 */
export function applyPreview(
  live: LiveState,
  preview: SpacePreview,
  expectedSpaceId: string,
): boolean {
  if (asString(preview.space_id) !== expectedSpaceId) return false
  const runId = asString(preview.run_id)
  const epoch = asString(preview.output_epoch)
  const seq = preview.output_seq
  if (!runId || !epoch || typeof seq !== 'number' || !Number.isInteger(seq) || seq < 1) {
    return false
  }

  let changed = false
  if (live.epoch !== epoch) {
    // A reset may arrive before the connection's first preview, while the
    // epoch is still null. Keep those repair markers: wiping them here would
    // hide the gap and let the first frame look like a complete baseline.
    const carried = live.epoch === null ? live.runs : {}
    live.epoch = epoch
    live.runs = carried
    changed = true
  }

  let run = live.runs[runId]
  if (!run) {
    run = newRun(runId)
    live.runs[runId] = run
    changed = true
  } else {
    if (seq <= run.lastSeq) return changed // duplicate / late frame
    if (seq !== run.lastSeq + 1 && run.lastSeq !== 0) {
      // Only a true gap matters. A fresh run (lastSeq 0) accepts any baseline,
      // which is what a reset or a connection's first frame looks like.
      run.blocks = []
      run.needsArchive = true
      changed = true
    }
  }
  run.lastSeq = seq
  // The cache bound applies to every accepted frame, not only to resets.
  const finish = (value: boolean): boolean => {
    pruneRuns(live)
    return value
  }

  const kind = preview.kind
  if (kind === 'terminal') {
    run.active = false
    run.terminalStatus = asString(preview.status)
    return finish(true)
  }

  if (!isKind(kind)) return finish(changed)
  const member = preview.member ?? {}
  const agentId = asString(member.agent_id)
  const agentKind = asString(member.agent_kind)
  const turn = asTurn(preview.turn)
  const key = asString(preview.block_key)

  if (kind === 'content' || kind === 'thinking') {
    if (!key || !preview.text) return finish(changed)
    const block = findBlock(run, key, kind, agentId, agentKind, turn)
    appendText(block, preview.text)
    return finish(true)
  }

  if (kind === 'tool') {
    if (!key || !preview.tool) return finish(changed)
    const block = findBlock(run, key, 'tool', agentId, agentKind, turn)
    const tool = preview.tool
    block.tool = {
      call_id: asString(tool.call_id),
      name: asString(tool.name),
      state: tool.state === 'finished' ? 'finished' : 'started',
      ...(tool.ok !== undefined ? { ok: Boolean(tool.ok) } : {}),
      ...(tool.skipped !== undefined ? { skipped: Boolean(tool.skipped) } : {}),
      ...(tool.detail !== undefined ? { detail: asString(tool.detail) } : {}),
      ...(tool.ms !== undefined ? { ms: tool.ms } : {}),
    }
    return finish(true)
  }

  // notice
  if (!key || !preview.text) return finish(changed)
  const block = findBlock(run, key, 'notice', agentId, agentKind, turn)
  block.text = preview.text
  return finish(true)
}

/** A preview gap occurred; keep the run card but rebuild its text from archive. */
export function applyReset(
  live: LiveState,
  reset: SpaceOutputReset,
  expectedSpaceId: string,
): boolean {
  if (asString(reset.space_id) !== expectedSpaceId) return false
  const runIds = Array.isArray(reset.run_ids)
    ? reset.run_ids.filter((id): id is string => typeof id === 'string' && !!id)
    : []
  if (runIds.length === 0) return false

  for (const runId of runIds) {
    const existing = live.runs[runId]
    live.runs[runId] = {
      ...(existing ?? newRun(runId)),
      lastSeq: 0,
      needsArchive: true,
      blocks: [],
    }
  }
  pruneRuns(live)
  return true
}

/** Archive reload finished; terminal previews can be released. */
export function markArchiveLoaded(live: LiveState, runId: string): boolean {
  const run = live.runs[runId]
  if (!run) return false
  if (!run.active) {
    delete live.runs[runId]
    return true
  }
  if (!run.needsArchive) return false
  run.needsArchive = false
  return true
}

export function clearLive(live: LiveState): boolean {
  if (live.epoch === null && Object.keys(live.runs).length === 0) return false
  live.epoch = null
  live.runs = {}
  return true
}

function memberKey(agentId: unknown, agentKind: unknown): string {
  const kind = asString(agentKind)
  // Single runs have no sub-agent source in the live bridge (empty member),
  // while the archived trajectory is annotated as single/<trajectory>. Both
  // describe the same agent, so the member id must not split the identity.
  if (!kind || kind === 'single') return 'single'
  return `${kind}|${asString(agentId)}`
}

function archivedTurns(records: RunTraceRecord[]): Map<string, number> {
  const turns = new Map<string, number>()
  for (const record of records) {
    const turn = asTurn(record.turn)
    if (turn === null) continue
    if (record.t !== 'llm' && record.t !== 'result' && record.t !== 'compaction') {
      continue
    }
    const key = memberKey(record.agent_id, record.agent_kind)
    const current = turns.get(key)
    if (current === undefined || turn > current) turns.set(key, turn)
  }
  return turns
}

/**
 * Hide live blocks whose member/turn already exists in the archive.
 *
 * A saved turn is final, so showing the live fragment next to it would
 * duplicate text. Tool blocks additionally match the archived tool name when
 * the archive exposed one.
 */
export function visibleBlocks(
  run: RunLiveOutput | undefined | null,
  records: RunTraceRecord[],
): LiveBlock[] {
  if (!run) return []
  const turns = archivedTurns(records)
  const archivedTools = new Set<string>()
  for (const record of records) {
    if (record.t !== 'llm' || !Array.isArray(record.tool_calls)) continue
    for (const call of record.tool_calls) {
      if (call.name) {
        const key = memberKey(record.agent_id, record.agent_kind)
        const turn = asTurn(record.turn)
        archivedTools.add(turn === null ? `${key}|${call.name}` : `${key}|${call.name}|${turn}`)
      }
    }
  }

  return run.blocks.filter((block) => {
    const key = memberKey(block.agent_id, block.agent_kind)
    const archived = turns.get(key)
    if (block.kind === 'tool') {
      if (block.tool?.name) {
        const exact =
          block.turn === null
            ? `${key}|${block.tool.name}`
            : `${key}|${block.tool.name}|${block.turn}`
        if (archivedTools.has(exact)) return false
      }
      if (block.turn !== null && archived !== undefined && archived > block.turn) {
        return false
      }
      return true
    }
    if (block.turn !== null && archived !== undefined && archived >= block.turn) {
      return false
    }
    return true
  })
}

/**
 * The run detail view polls while the run is active. Normal (non-space) mode
 * must never depend on the space-only flags: Vue supplies absent Booleans as
 * false, so a single mode flag keeps the legacy polling behaviour intact.
 */
export function shouldPollRunDetail(input: {
  liveMode: boolean
  liveActive: boolean
  globalRunning: boolean
}): boolean {
  return input.liveMode ? input.liveActive : input.globalRunning
}

export function blockMemberLabel(block: LiveBlock): string {
  if (block.agent_kind === 'coordinator') return '主 Agent'
  if (block.agent_kind === 'subagent') {
    return block.agent_id ? `成员 · ${block.agent_id}` : '成员'
  }
  if (block.agent_kind) return block.agent_kind
  return '单 Agent'
}
