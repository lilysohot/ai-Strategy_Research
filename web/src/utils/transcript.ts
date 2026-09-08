/**
 * Transcript navigation helpers (P2.6 §5.5) — the web counterparts of the
 * terminal's ``/filter``, ``/find``, ``Ctrl-G`` (jump to report) and ``Ctrl-Y``
 * (copy report) commands. Pure functions over the run's step list so the
 * semantics stay unit-testable and the store stays untouched.
 */
import type { RunStep } from '../stores/runs'

export type TranscriptFilter = 'all' | 'thinking' | 'tools' | 'errors' | 'report'

/**
 * Keep the steps visible under ``filter``.
 *
 * ``report`` mirrors the terminal's "jump to final report": only the last
 * assistant text step (the answer as it stood when the run ended) qualifies —
 * intermediate narration stays hidden.
 */
export function filterSteps(steps: RunStep[], filter: TranscriptFilter): RunStep[] {
  switch (filter) {
    case 'thinking':
      return steps.filter((s) => s.kind === 'thinking')
    case 'tools':
      return steps.filter((s) => s.kind === 'tool')
    case 'errors':
      return steps.filter((s) => s.kind === 'tool' && s.status === 'error')
    case 'report': {
      for (let i = steps.length - 1; i >= 0; i--) {
        if (steps[i].kind === 'text') return [steps[i]]
      }
      return []
    }
    default:
      return steps
  }
}

/**
 * Ids of steps whose visible text contains ``query`` (case-insensitive), in
 * display order — the anchor list the find bar's prev/next buttons walk.
 * Tool steps match on their name; an empty query never matches.
 */
export function findMatches(steps: RunStep[], query: string): number[] {
  const needle = query.trim().toLowerCase()
  if (!needle) return []
  const hits: number[] = []
  for (const s of steps) {
    const haystack =
      s.kind === 'tool' ? (s.name ?? '') : (s.content ?? '')
    if (haystack.toLowerCase().includes(needle)) hits.push(s.id)
  }
  return hits
}

/** The final report text (last assistant text step), or '' when there is none. */
export function reportText(steps: RunStep[]): string {
  for (let i = steps.length - 1; i >= 0; i--) {
    if (steps[i].kind === 'text') return steps[i].content ?? ''
  }
  return ''
}
