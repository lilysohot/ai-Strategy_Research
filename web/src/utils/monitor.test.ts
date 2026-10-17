import test from 'node:test'
import assert from 'node:assert/strict'

import { activeMonitorRunId } from './monitor.ts'

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
