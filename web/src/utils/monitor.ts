import type { ResearchLink, WatchEvent } from '@/types'

export type MonitorBindingState = 'loading' | 'ready' | 'error'

/** Explain why this research cannot safely create an automatic-analysis watch. */
export function autoAnalysisBindingIssue(
  link: Pick<ResearchLink, 'account_id' | 'primary_plan_id'> | null,
  state: MonitorBindingState,
): string | null {
  if (state === 'loading') return '正在核对当前研究的账户与主计划，请稍候。'
  if (state === 'error') return '暂时无法确认当前研究的账户绑定，只能设置“仅提醒”。请刷新后重试。'
  if (!link?.account_id) {
    return '当前研究未绑定主账户，只能设置“仅提醒”。请先在账户与计划中绑定主账户。'
  }
  if (!link.primary_plan_id) {
    return '当前研究未创建并选择主计划，只能设置“仅提醒”。请先在会话计划中完成主计划。'
  }
  return null
}

/** Return the newest monitor-created run that still needs a live UI attachment. */
export function activeMonitorRunId(
  events: readonly Pick<WatchEvent, 'run_id' | 'status'>[],
): string | null {
  return events.find((event) => event.status === 'dispatching' && event.run_id)?.run_id ?? null
}
