export type WorkspaceArea =
  | 'research'
  | 'profiles'
  | 'requests'
  | 'monitoring'
  | 'notifications'

export interface WorkspaceTarget {
  researchId?: string
  requestId?: string
  runId?: string
}

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
  /** 本标的规划资金（金额，十进制字符串）；计划不保存价格（2026-10-08 口径）。 */
  allocatedCapital: string
  isPrimary: boolean
  status: 'draft'
}

export type SessionPlanInput = Omit<SessionPlanPreview, 'id' | 'sessionId' | 'sessionTitle' | 'status'>

/** 会话规划资金（会话 ↔ 规划资金 1:1）：只保存资金分配，不含价格。 */
export interface SessionCapitalPlan {
  id: string
  revision: number
  allocatedCapital: string
  currency: string
  accountId: string | null
  recordState: string
}

/** 实际买卖价格（规划资金 1:N）：每笔买入/卖出各一条。 */
export interface SessionBuySellPlan {
  id: string
  revision: number
  symbol: string
  market: 'CN' | 'HK' | 'US'
  side: 'buy' | 'sell'
  price: string
  quantity: string
  tradedAt: string
  currency: string
  archived: boolean
}

export interface SessionBuySellPlanInput {
  symbol: string
  market: 'CN' | 'HK' | 'US'
  side: 'buy' | 'sell'
  price: string
  quantity: string
  tradedAt: string
  currency: string
}

export const WORKSPACE_NAV_ITEMS: readonly WorkspaceNavItem[] = [
  { id: 'research', label: '研究对话', caption: '会话与分析' },
  { id: 'profiles', label: '交易账户资料', caption: '账户、计划关系与实际记录' },
  { id: 'requests', label: '待补资料与处理结果', caption: '按会话汇总的待办与回执' },
  { id: 'monitoring', label: '监控', caption: '规则与行情状态' },
  { id: 'notifications', label: '通知', caption: '业务事件与运行结果' },
]
