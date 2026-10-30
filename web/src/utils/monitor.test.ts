import test from 'node:test'
import assert from 'node:assert/strict'

import { activeMonitorRunId, autoAnalysisBindingIssue, monitorConditionLabel, monitorModeLabel } from './monitor.ts'

test('monitor labels distinguish persistent conditions from crossings', () => {
  assert.equal(monitorConditionLabel('up', 'continuous'), '大于等于')
  assert.equal(monitorConditionLabel('down', 'crossing'), '下穿')
  assert.equal(monitorConditionLabel('range', 'continuous'), '处于区间')
  assert.equal(monitorModeLabel('crossing'), '穿越时触发')
  assert.equal(monitorModeLabel('single'), '单次触发')
})

test('auto analysis requires a confirmed main account and a capital plan', () => {
  assert.match(autoAnalysisBindingIssue(null, null, 'loading') ?? '', /正在核对/)
  assert.match(autoAnalysisBindingIssue(null, null, 'error') ?? '', /无法确认/)
  assert.match(
    autoAnalysisBindingIssue({ account_id: null, primary_plan_id: null }, null, 'ready') ?? '',
    /未绑定主账户/,
  )
  assert.match(
    autoAnalysisBindingIssue({ account_id: 'account-1', primary_plan_id: null }, null, 'ready') ?? '',
    /未配置规划资金/,
  )
  // 主计划不再是必要条件：绑定规划资金即可开启自动分析。
  assert.equal(
    autoAnalysisBindingIssue(
      { account_id: 'account-1', primary_plan_id: null },
      'capital-1',
      'ready',
    ),
    null,
  )
  assert.equal(
    autoAnalysisBindingIssue(
      { account_id: 'account-1', primary_plan_id: 'plan-1' },
      'capital-1',
      'ready',
    ),
    null,
  )
})

test('activeMonitorRunId selects the newest dispatching monitor run', () => {
  assert.equal(activeMonitorRunId([
    { run_id: 'run-new', status: 'dispatching' },
    { run_id: 'run-old', status: 'completed' },
  ]), 'run-new')
})

test('activeMonitorRunId ignores completed history and events without runs', () => {
  assert.equal(activeMonitorRunId([
    { run_id: 'run-old', status: 'completed' },
    { run_id: null, status: 'pending' },
  ]), null)
})
