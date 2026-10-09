import type { Turn } from '@/types'

/** Compare UUIDs across the API's compact and canonical string forms. */
export function sameRunId(left: string | null | undefined, right: string | null | undefined): boolean {
  if (!left || !right) return false
  return left.replaceAll('-', '').toLowerCase() === right.replaceAll('-', '').toLowerCase()
}

/**
 * The server identifies the assistant turn created by a run with its run id.
 * Keep only one rendered turn for that id so a repeated backfill cannot create
 * two identical assistant bubbles in the transcript.
 */
export function dedupeAssistantTurns(turns: readonly Turn[]): Turn[] {
  const seenRunIds = new Set<string>()
  return turns.filter((turn) => {
    if (turn.role !== 'assistant' || !turn.run_id) return true
    const normalizedRunId = turn.run_id.replaceAll('-', '').toLowerCase()
    if (seenRunIds.has(normalizedRunId)) return false
    seenRunIds.add(normalizedRunId)
    return true
  })
}

/**
 * Whether the live run stream is still attached to the research on screen.
 *
 * A run belongs to exactly one research, so a switch that leaves that research
 * must drop the stream. The reverse has to hold too: selecting the research we
 * are already streaming into — which the rail does on every click, including on
 * the active item — must NOT drop it, or the thread is left with the persisted
 * turns alone and a running research looks empty.
 */
export function streamBelongsToSession(
  streamSessionId: string | null,
  sessionId: string | null,
): boolean {
  return streamSessionId !== null && streamSessionId === sessionId
}

/**
 * Whether the transcript already carries the persisted answer of ``runId``.
 *
 * The assistant turn is written when the run ends, so a run that finished while
 * its research was off screen has no live stream left to render it: the answer
 * is only visible after the turns are read again. Callers use this to tell "the
 * answer is already on screen" from "re-read is still required".
 */
export function hasRunAnswer(turns: readonly Turn[], runId: string | null): boolean {
  if (!runId) return false
  return turns.some((turn) => turn.role === 'assistant' && sameRunId(turn.run_id, runId))
}
