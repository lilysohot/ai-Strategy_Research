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
