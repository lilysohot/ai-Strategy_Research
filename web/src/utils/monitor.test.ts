import test from 'node:test'
import assert from 'node:assert/strict'

import { activeMonitorRunId, autoAnalysisBindingIssue } from './monitor.ts'

test('auto analysis requires a confirmed main account and primary plan', () => {
  assert.match(autoAnalysisBindingIssue(null, 'loading') ?? '', /正在核对/)
  assert.match(autoAnalysisBindingIssue(null, 'error') ?? '', /无法确认/)
  assert.match(
    autoAnalysisBindingIssue({ account_id: null, primary_plan_id: null }, 'ready') ?? '',
    /未绑定主账户/,
  )
  assert.match(
    autoAnalysisBindingIssue({ account_id: 'account-1', primary_plan_id: null }, 'ready') ?? '',
    /未创建并选择主计划/,
  )
  assert.equal(
    autoAnalysisBindingIssue(
      { account_id: 'account-1', primary_plan_id: 'plan-1' },
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
