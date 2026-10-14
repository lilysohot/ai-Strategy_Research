import type { RunStatus } from '../types'

export type VisibleRunStatus = RunStatus | 'idle'

export function isActiveRunStatus(status: VisibleRunStatus): boolean {
  return status === 'queued' || status === 'running'
}

export function isTerminalRunStatus(status: VisibleRunStatus): boolean {
  return status === 'completed' || status === 'failed' || status === 'stopped'
}

/**
 * Merge a status read from the run-detail endpoint into the live stream state.
 *
 * A terminal SSE event can arrive just before the orchestrator commits the same
 * terminal state to the database. During that small window GET /runs/{id} still
 * returns `running`. Once the stream has ended, that stale active value must not
 * resurrect the run in the UI; a later reconciliation attempt will observe the
 * committed terminal row.
 */
export function mergeReconciledRunStatus(
  current: VisibleRunStatus,
  remote: RunStatus,
  streamEnded: boolean,
): VisibleRunStatus {
  if (streamEnded && isActiveRunStatus(remote)) {
    return isTerminalRunStatus(current) ? current : 'idle'
  }
  return remote
}
