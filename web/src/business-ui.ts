export type WorkspaceArea =
  | 'research'
  | 'profiles'
  | 'requests'
  | 'monitoring'
  | 'notifications'

export interface WorkspaceNavItem {
  id: WorkspaceArea
  label: string
  caption: string
  count?: number
}

export interface SessionPlanPreview {
  id: string
  sessionId: string
  sessionTitle: string
  name: string
  symbol: string
  market: 'CN' | 'HK' | 'US'
  direction: 'buy' | 'sell'
  planPrice: string
  targetPrice: string
  isPrimary: boolean
  status: 'draft'
}

export type SessionPlanInput = Omit<SessionPlanPreview, 'id' | 'sessionId' | 'sessionTitle' | 'status'>

export const WORKSPACE_NAV_ITEMS: readonly WorkspaceNavItem[] = [
  { id: 'research', label: '研究对话', caption: '会话与分析' },
  { id: 'profiles', label: '交易账户资料', caption: '账户、计划关系与实际记录' },
  { id: 'requests', label: '待补资料与处理结果', caption: '按会话汇总的待办与回执' },
  { id: 'monitoring', label: '监控', caption: '规则与行情状态' },
  { id: 'notifications', label: '通知', caption: '业务事件与运行结果' },
]
