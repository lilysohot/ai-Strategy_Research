import assert from 'node:assert/strict'
import test from 'node:test'

import { dialogCoversRequest } from './inputRequest.ts'

test('plan-only requests are the dialog case', () => {
  assert.equal(
    dialogCoversRequest(['plan.allocated_capital'], { accountBound: true }),
    true,
  )
  assert.equal(
    dialogCoversRequest(
      ['plan.allocated_capital', 'plan.risk_budget_value', 'plan.target_profit_unit'],
      { accountBound: true },
    ),
    true,
  )
})

test('account facts are coverable only while the research has no account', () => {
  const remaining = ['account.total_capital', 'plan.allocated_capital']
  assert.equal(dialogCoversRequest(remaining, { accountBound: false }), true)
  // 已绑定账户时弹窗是只读的：不会再申报账户事实，交给补数中心。
  assert.equal(dialogCoversRequest(remaining, { accountBound: true }), false)
})

test('2026-10-09 实测的 8 字段请求不走弹窗', () => {
  // 研究还没有账户/计划时 worker 意图落库出的字段集。
  const remaining = [
    'account.as_of',
    'account.capital_basis',
    'account.currency',
    'account.total_capital',
    'plan.allocated_capital',
    'plan.direction',
    'plan.market',
    'plan.symbol',
  ]
  assert.equal(dialogCoversRequest(remaining, { accountBound: false }), false)
  assert.equal(dialogCoversRequest(remaining, { accountBound: true }), false)
})

test('nothing missing means the dialog has nothing to collect', () => {
  assert.equal(dialogCoversRequest([], { accountBound: false }), false)
})
