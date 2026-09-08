/**
 * Plan-board state derived from the run's task-board tool calls (P2.4,
 * cli-web-parity.md §5.2 — as corrected: the data source is add_task /
 * update_task, not a todo tool).
 *
 * The board is a pure fold over the already-collected tool steps, so it
 * survives reconnects and replays exactly like the rest of the step-derived
 * UI: same events in, same board out, no extra server state.
 */

export type PlanTaskStatus = 'open' | 'in_progress' | 'resolved' | 'cancelled'

export interface PlanTask {
  id: string
  description: string
  status: PlanTaskStatus
}

/** The subset of RunStep the fold needs (keeps this module vue/pinia-free). */
export interface PlanSourceStep {
  name?: unknown
  input?: unknown
  output?: unknown
}

const RESOLUTIONS: ReadonlySet<string> = new Set([
  'open',
  'in_progress',
  'resolved',
  'cancelled',
])

/** ``Added ['t1', 't2'].`` — the ids of the usable items, in item order. */
function parseAddedIds(output: unknown): string[] {
  if (typeof output !== 'string') return []
  const m = /Added\s*\[([^\]]*)\]/.exec(output)
  if (!m) return []
  const ids: string[] = []
  for (const match of m[1].matchAll(/['"]([^'"]+)['"]/g)) {
    ids.push(match[1])
  }
  return ids
}

/** Usable ``{description}`` strings, in order — mirrors the tool's own filter. */
function descriptionsOf(input: unknown): string[] {
  const tasks = (input as { tasks?: unknown } | null | undefined)?.tasks
  if (!Array.isArray(tasks)) return []
  const out: string[] = []
  for (const raw of tasks) {
    if (typeof raw === 'string') {
      const s = raw.trim()
      if (s) out.push(s)
      continue
    }
    if (raw && typeof raw === 'object') {
      const s = String((raw as { description?: unknown }).description ?? '').trim()
      if (s) out.push(s)
    }
  }
  return out
}

export function buildPlan(steps: PlanSourceStep[]): PlanTask[] {
  const byId = new Map<string, PlanTask>()
  const rowByDesc = new Map<string, PlanTask>()
  let fallbackSeq = 0

  for (const step of steps) {
    if (typeof step.name !== 'string') continue

    if (step.name === 'add_task') {
      const descriptions = descriptionsOf(step.input)
      const ids = parseAddedIds(step.output)
      for (let i = 0; i < descriptions.length; i++) {
        const desc = descriptions[i]
        const existing = rowByDesc.get(desc)
        if (existing) continue // dedup re-decomposition, like the tool itself
        // Usable items zip with the Added ids in order; a missing entry
        // (unparseable output) still needs a stable row key.
        const id = ids[i] ?? `p${++fallbackSeq}`
        const task: PlanTask = { id, description: desc, status: 'open' }
        byId.set(id, task)
        rowByDesc.set(desc, task)
      }
      continue
    }

    if (step.name === 'update_task') {
      const updates = (step.input as { updates?: unknown } | null | undefined)?.updates
      if (!Array.isArray(updates)) continue
      for (const raw of updates) {
        if (!raw || typeof raw !== 'object') continue
        const { id, resolution } = raw as { id?: unknown; resolution?: unknown }
        if (typeof id !== 'string' || typeof resolution !== 'string') continue
        if (!RESOLUTIONS.has(resolution)) continue
        const task = byId.get(id)
        if (task) task.status = resolution as PlanTaskStatus
      }
    }
  }
  return [...byId.values()]
}

/** Completed = resolved only; cancelled items stay out of the done count. */
export function planDoneCount(tasks: PlanTask[]): number {
  return tasks.filter((t) => t.status === 'resolved').length
}
