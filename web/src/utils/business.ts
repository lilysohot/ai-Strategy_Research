export type BusinessUseCase = 'general_reading' | 'plan_analysis' | 'holding_cost'

export type TradeDirection = '' | 'buy' | 'sell'

export interface BusinessDraft {
  accountName: string
  currency: string
  capitalBasis: string
  totalCapital: string
  availableCapital: string
  asOf: string
  symbol: string
  market: string
  direction: TradeDirection
  planPrice: string
  planPriceLow: string
  planPriceHigh: string
  targetPrice: string
  riskBudget: string
  riskBudgetUnit: 'amount' | 'percent'
  positionLimit: string
  timeWindow: string
  invalidation: string
  purchased: boolean
  actualPrice: string
  useCase: BusinessUseCase
}

export type BusinessDraftErrors = Partial<Record<keyof BusinessDraft, string>>

const DECIMAL_TEXT = /^(?:0|[1-9]\d*)(?:\.\d+)?$/

export function isDecimalText(value: string): boolean {
  return value === '' || DECIMAL_TEXT.test(value)
}

function requireDecimal(
  draft: BusinessDraft,
  errors: BusinessDraftErrors,
  key: keyof BusinessDraft,
  message: string,
): void {
  const value = draft[key]
  if (typeof value === 'string' && !value.trim()) errors[key] = message
}

function validateDecimalFields(draft: BusinessDraft, errors: BusinessDraftErrors): void {
  const fields: Array<keyof BusinessDraft> = [
    'totalCapital',
    'availableCapital',
    'planPrice',
    'planPriceLow',
    'planPriceHigh',
    'targetPrice',
    'riskBudget',
    'positionLimit',
    'actualPrice',
  ]
  for (const key of fields) {
    const value = draft[key]
    if (typeof value === 'string' && !isDecimalText(value.trim())) {
      errors[key] = '请输入非负十进制文本，不使用千分位或科学计数法'
    }
  }
}

/**
 * Browser-side guidance only. The server-side purpose contract remains the
 * authority and may return more precise field errors.
 */
export function validateBusinessDraft(draft: BusinessDraft): BusinessDraftErrors {
  const errors: BusinessDraftErrors = {}
  validateDecimalFields(draft, errors)

  if (!draft.accountName.trim()) errors.accountName = '请为账户填写一个可识别名称'
  if (!draft.currency.trim()) errors.currency = '请选择币种'
  if (!draft.capitalBasis.trim()) errors.capitalBasis = '请说明资金口径'
  if (!draft.asOf.trim()) errors.asOf = '请选择数据时点'

  if (draft.useCase === 'plan_analysis' || draft.useCase === 'holding_cost') {
    if (!draft.symbol.trim()) errors.symbol = '请填写标的'
    if (!draft.market.trim()) errors.market = '请选择市场'
    if (!draft.direction) errors.direction = '请选择方向'
  }

  if (draft.useCase === 'plan_analysis') {
    const hasSinglePrice = !!draft.planPrice.trim()
    const hasRange = !!draft.planPriceLow.trim() && !!draft.planPriceHigh.trim()
    if (!hasSinglePrice && !hasRange) {
      errors.planPrice = '请填写计划价，或同时填写价格区间上下限'
    }
    requireDecimal(draft, errors, 'targetPrice', '计划分析需要目标价')
  }

  if (draft.useCase === 'holding_cost') {
    requireDecimal(draft, errors, 'totalCapital', '持仓成本计算需要总资金')
    requireDecimal(draft, errors, 'availableCapital', '持仓成本计算需要可用资金')
    if (!draft.purchased) errors.purchased = '请选择“已买入”并填写真实成交信息'
    requireDecimal(draft, errors, 'actualPrice', '已买入时需要真实成交价')
  }

  if (draft.purchased) {
    requireDecimal(draft, errors, 'actualPrice', '已买入时实际成交价不能为空')
  }

  return errors
}

export function countDraftErrors(errors: BusinessDraftErrors): number {
  return Object.keys(errors).length
}
