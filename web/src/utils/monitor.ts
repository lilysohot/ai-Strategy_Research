import type { ResearchLink, WatchEvent } from '@/types'

export type MonitorBindingState = 'loading' | 'ready' | 'error'

export function monitorConditionLabel(direction: unknown, mode: unknown): string {
  if (mode === 'continuous') {
    return direction === 'up' ? '大于等于' : direction === 'down' ? '小于等于' : '处于区间'
  }
  return direction === 'up' ? '上穿' : direction === 'down' ? '下穿' : '进入区间'
}

export function monitorModeLabel(mode: unknown): string {
  return mode === 'crossing' ? '穿越时触发' : mode === 'continuous' ? '每轮达标触发' : '单次触发'
}

/**
 * Explain why this research cannot safely create an automatic-analysis watch.
 *
 * 绑定口径（2026-10-27）：主计划不再是必要条件——会话绑定**规划资金**即可开启
 * 自动分析；计划口径由规划资金下的实际买卖价格供给。
 */
export function autoAnalysisBindingIssue(
  link: Pick<ResearchLink, 'account_id' | 'primary_plan_id'> | null,
  capitalPlanId: string | null,
  state: MonitorBindingState,
): string | null {
  if (state === 'loading') return '正在核对当前研究的账户与规划资金，请稍候。'
  if (state === 'error') return '暂时无法确认当前研究的账户绑定，只能设置“仅提醒”。请刷新后重试。'
  if (!link?.account_id) {
    return '当前研究未绑定主账户，只能设置“仅提醒”。请先在账户与计划中绑定主账户。'
  }
  if (!capitalPlanId) {
    return '当前研究未配置规划资金，只能设置“仅提醒”。请先在会话资金中创建规划资金。'
  }
  return null
}

/** Return the newest monitor-created run that still needs a live UI attachment. */
export function activeMonitorRunId(
  events: readonly Pick<WatchEvent, 'run_id' | 'status'>[],
): string | null {
  return events.find((event) => event.status === 'dispatching' && event.run_id)?.run_id ?? null
}
