import type { WatchEvent } from '@/types'

/** Return the newest monitor-created run that still needs a live UI attachment. */
export function activeMonitorRunId(
  events: readonly Pick<WatchEvent, 'run_id' | 'status'>[],
): string | null {
  return events.find((event) => event.status === 'dispatching' && event.run_id)?.run_id ?? null
}
