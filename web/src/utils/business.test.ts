import assert from 'node:assert/strict'
import test from 'node:test'

import {
  countDraftErrors,
  isDecimalText,
  type BusinessDraft,
  validateBusinessDraft,
} from './business.ts'

function draft(overrides: Partial<BusinessDraft> = {}): BusinessDraft {
  return {
    accountName: '主账户',
    currency: 'CNY',
    capitalBasis: '可交易资产',
    totalCapital: '',
    availableCapital: '',
    asOf: '2026-10-02T09:30',
    symbol: '',
    market: '',
    direction: '',
    planPrice: '',
    planPriceLow: '',
    planPriceHigh: '',
    targetPrice: '',
    riskBudget: '',
    riskBudgetUnit: 'amount',
    positionLimit: '',
    timeWindow: '',
    invalidation: '',
    purchased: false,
    actualPrice: '',
    useCase: 'general_reading',
    ...overrides,
  }
}

test('decimal values stay as exact strings', () => {
  assert.equal(isDecimalText('0.00000001'), true)
  assert.equal(isDecimalText('100000000000000000000.01'), true)
  assert.equal(isDecimalText('1e-8'), false)
  assert.equal(isDecimalText('1,000'), false)
  assert.equal(isDecimalText('-1'), false)
})

test('general reading does not require funds or a trade plan', () => {
  assert.deepEqual(validateBusinessDraft(draft()), {})
})

test('plan analysis accepts either a single price or a complete range', () => {
  const common = {
    useCase: 'plan_analysis' as const,
    symbol: '600000',
    market: 'CN',
    direction: 'buy' as const,
    targetPrice: '12.50',
  }
  assert.deepEqual(validateBusinessDraft(draft({ ...common, planPrice: '10.20' })), {})
  assert.deepEqual(
    validateBusinessDraft(draft({ ...common, planPriceLow: '9.80', planPriceHigh: '10.20' })),
    {},
  )
  assert.equal(
    validateBusinessDraft(draft({ ...common, planPriceLow: '9.80' })).planPrice,
    '请填写计划价，或同时填写价格区间上下限',
  )
})

test('holding-cost purpose requires explicit funds and real fill state', () => {
  const errors = validateBusinessDraft(
    draft({
      useCase: 'holding_cost',
      symbol: 'AAPL',
      market: 'US',
      direction: 'buy',
    }),
  )
  assert.equal(errors.totalCapital, '持仓成本计算需要总资金')
  assert.equal(errors.availableCapital, '持仓成本计算需要可用资金')
  assert.equal(errors.purchased, '请选择“已买入”并填写真实成交信息')
  assert.equal(errors.actualPrice, '已买入时需要真实成交价')
  assert.equal(countDraftErrors(errors), 4)
})
