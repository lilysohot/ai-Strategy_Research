import assert from 'node:assert/strict'
import test from 'node:test'

import { mergeReconciledRunStatus } from './runStatus.ts'

test('a stale active detail response cannot resurrect a terminal stream', () => {
  assert.equal(mergeReconciledRunStatus('stopped', 'running', true), 'stopped')
  assert.equal(mergeReconciledRunStatus('failed', 'queued', true), 'failed')
})

test('clean EOF stays settled while the terminal database write catches up', () => {
  assert.equal(mergeReconciledRunStatus('idle', 'running', true), 'idle')
})

test('a committed terminal status remains authoritative', () => {
  assert.equal(mergeReconciledRunStatus('stopped', 'completed', true), 'completed')
  assert.equal(mergeReconciledRunStatus('running', 'failed', false), 'failed')
})
