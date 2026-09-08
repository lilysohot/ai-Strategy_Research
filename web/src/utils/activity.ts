/**
 * Activity-timeline status semantics (cli-web-parity §5.3).
 *
 * Pure, dependency-free functions so they can be unit-tested with the bare
 * node runner (`node --experimental-strip-types --test`) — the web project has
 * no vitest and cannot install one offline. Keep it that way: no vue/pinia
 * imports here.
 *
 * The five states mirror the terminal's Activity widget (apodex/tui/widgets.py):
 * running → done | error | skipped, with interrupted replacing running when the
 * run ends without the call ever landing a result.
 */

/** Lifecycle state of one timeline step. */
export type StepStatus = 'running' | 'done' | 'error' | 'skipped' | 'interrupted'

/** The fields of a ``tool_finished`` SSE event that decide the final state. */
export interface ToolFinishFields {
  ok?: boolean
  /** Server-side verdict that the call never actually ran (cap, rejection, safety block). */
  skipped?: boolean
}

/**
 * Map a ``tool_finished`` event to the step's final status.
 *
 * ``skipped`` wins over ``ok``: a synthetic "never ran" result is rendered as
 * skipped even though the bridge stamps it ``ok: true`` (the call itself
 * produced no error — it simply never executed).
 */
export function toolStepStatus(event: ToolFinishFields): StepStatus {
  if (event.skipped) return 'skipped'
  return event.ok === false ? 'error' : 'done'
}

/**
 * Mark every still-running step as interrupted, in place.
 *
 * Called when the run ends without the pending tool results arriving
 * (``run_stopped`` / ``run_failed``): the calls were in flight and now will
 * never complete, which is a distinct state from a clean finish.
 *
 * Returns the number of steps changed (0 is the common no-op case).
 */
export function interruptInFlight(steps: Array<{ status?: StepStatus }>): number {
  let changed = 0
  for (const step of steps) {
    if (step.status === 'running') {
      step.status = 'interrupted'
      changed++
    }
  }
  return changed
}

/** Input keys worth surfacing in a one-line summary, in priority order. */
const SUMMARY_KEYS = [
  'command',
  'path',
  'file_path',
  'query',
  'pattern',
  'url',
  'prompt',
  'task',
  'content',
] as const

const SUMMARY_MAX = 80

/**
 * One-line summary of a tool step for the collapsed timeline row (§5.3).
 *
 * Picks the most descriptive input field (command for bash, path for file
 * tools, …), flattens newlines, and truncates. Empty string when there is
 * nothing summarizable — the row then shows just the tool name.
 */
export function stepSummary(step: { input?: unknown }): string {
  let raw: unknown
  if (typeof step.input === 'string') {
    raw = step.input
  } else if (step.input && typeof step.input === 'object') {
    const record = step.input as Record<string, unknown>
    for (const key of SUMMARY_KEYS) {
      const value = record[key]
      if (typeof value === 'string' && value.trim()) {
        raw = value
        break
      }
    }
  }
  if (typeof raw !== 'string') return ''
  const flat = raw.replace(/\s+/g, ' ').trim()
  return flat.length > SUMMARY_MAX ? `${flat.slice(0, SUMMARY_MAX)}…` : flat
}

/** Element-plus tag type for a step status (badge colour semantics). */
export type TagType = 'success' | 'warning' | 'danger' | 'info' | 'primary'

const STATUS_LABELS: Record<StepStatus, string> = {
  running: '调用中',
  done: '完成',
  error: '失败',
  skipped: '跳过',
  interrupted: '已中断',
}

const STATUS_TAG_TYPES: Record<StepStatus, TagType> = {
  running: 'warning',
  done: 'success',
  error: 'danger',
  skipped: 'info',
  interrupted: 'warning',
}

/** Chinese label for a step status ('' when the step has none yet). */
export function statusLabel(status?: StepStatus): string {
  return status ? (STATUS_LABELS[status] ?? '') : ''
}

/** Element-plus ``el-tag`` type for a step status. */
export function statusTagType(status?: StepStatus): TagType {
  return status ? (STATUS_TAG_TYPES[status] ?? 'info') : 'info'
}
