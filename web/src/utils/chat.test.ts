import test from 'node:test'
import assert from 'node:assert/strict'

import type { Turn } from '@/types'
import {
  attachDiscoveredRun,
  attachSubmittedRun,
  dedupeAssistantTurns,
  hasRunAnswer,
  sameRunId,
  streamBelongsToSession,
} from './chat.ts'

function turn(partial: Partial<Turn> & Pick<Turn, 'seq' | 'role'>): Turn {
  return {
    content: '',
    run_id: null,
    created_at: null,
    ...partial,
  }
}

test('dedupeAssistantTurns renders one assistant reply for a repeated run', () => {
  const turns = [
    turn({ seq: 1, role: 'user', content: '你好' }),
    turn({ seq: 2, role: 'assistant', content: '你好！', run_id: 'run-1' }),
    turn({ seq: 3, role: 'assistant', content: '你好！', run_id: 'run-1' }),
  ]

  assert.deepEqual(dedupeAssistantTurns(turns), turns.slice(0, 2))
})

test('sameRunId matches compact and canonical UUID forms', () => {
  assert.equal(
    sameRunId('550e8400e29b41d4a716446655440000', '550e8400-e29b-41d4-a716-446655440000'),
    true,
  )
  assert.equal(sameRunId('run-1', 'run-2'), false)
})

test('dedupeAssistantTurns keeps distinct assistant runs and legacy turns', () => {
  const turns = [
    turn({ seq: 1, role: 'assistant', content: 'same text', run_id: null }),
    turn({ seq: 2, role: 'assistant', content: 'same text', run_id: null }),
    turn({ seq: 3, role: 'assistant', content: 'first', run_id: 'run-1' }),
    turn({ seq: 4, role: 'assistant', content: 'second', run_id: 'run-2' }),
  ]

  assert.deepEqual(dedupeAssistantTurns(turns), turns)
})

test('streamBelongsToSession keeps the stream of the research being re-opened', () => {
  assert.equal(streamBelongsToSession('research-a', 'research-a'), true)
  // Switching research, and having no stream at all, both drop it.
  assert.equal(streamBelongsToSession('research-a', 'research-b'), false)
  assert.equal(streamBelongsToSession(null, 'research-a'), false)
  assert.equal(streamBelongsToSession('research-a', null), false)
})

test('hasRunAnswer finds the persisted answer of the run, not just any reply', () => {
  const turns = [
    turn({ seq: 1, role: 'user', content: '值得买吗', run_id: 'run-1' }),
    turn({ seq: 2, role: 'assistant', content: '早先的答复', run_id: 'run-0' }),
  ]

  // The run's own turn is still missing: the thread has to be read again.
  assert.equal(hasRunAnswer(turns, 'run-1'), false)
  assert.equal(hasRunAnswer(turns, null), false)
  assert.equal(
    hasRunAnswer(
      [...turns, turn({ seq: 3, role: 'assistant', content: '本次答复', run_id: 'run1' })],
      'run-1',
    ),
    true,
  )
})

test('attachSubmittedRun records and watches a run created outside the composer', () => {
  const turns = [turn({ seq: 4, role: 'assistant', content: '原分析', run_id: 'run-old' })]
  const calls: string[] = []
  let appended: Turn | null = null

  const attached = attachSubmittedRun(
    {
      sessionId: 'research-1',
      runId: 'run-new',
      message: '已按 48.82 买入 100，请按实际成交成本重新分析。',
    },
    'research-1',
    turns,
    {
      appendTurn(value) {
        calls.push('append')
        appended = value
      },
      rememberRun(sessionId, runId) {
        calls.push(`remember:${sessionId}:${runId}`)
      },
      watchRun(runId, sessionId) {
        calls.push(`watch:${runId}:${sessionId}`)
      },
    },
  )

  assert.equal(attached, true)
  assert.deepEqual(appended, turn({
    seq: 5,
    role: 'user',
    content: '已按 48.82 买入 100，请按实际成交成本重新分析。',
  }))
  assert.deepEqual(calls, [
    'append',
    'remember:research-1:run-new',
    'watch:run-new:research-1',
  ])
})

test('attachSubmittedRun ignores a submission after the active research changed', () => {
  let called = false
  const attached = attachSubmittedRun(
    { sessionId: 'research-old', runId: 'run-new', message: '重新分析' },
    'research-current',
    [],
    {
      appendTurn() { called = true },
      rememberRun() { called = true },
      watchRun() { called = true },
    },
  )

  assert.equal(attached, false)
  assert.equal(called, false)
})

test('attachDiscoveredRun watches an asynchronously created monitor run', () => {
  const calls: string[] = []
  const outcome = attachDiscoveredRun(
    { sessionId: 'research-1', runId: 'run-monitor' },
    'research-1',
    'run-old',
    false,
    {
      rememberRun(sessionId, runId) { calls.push(`remember:${sessionId}:${runId}`) },
      watchRun(runId, sessionId) { calls.push(`watch:${runId}:${sessionId}`) },
    },
  )

  assert.equal(outcome, 'attached')
  assert.deepEqual(calls, [
    'remember:research-1:run-monitor',
    'watch:run-monitor:research-1',
  ])
})

test('attachDiscoveredRun defers switching away from a live run', () => {
  const calls: string[] = []
  const outcome = attachDiscoveredRun(
    { sessionId: 'research-1', runId: 'run-monitor' },
    'research-1',
    'run-current',
    true,
    {
      rememberRun(sessionId, runId) { calls.push(`remember:${sessionId}:${runId}`) },
      watchRun(runId, sessionId) { calls.push(`watch:${runId}:${sessionId}`) },
    },
  )

  assert.equal(outcome, 'deferred')
  assert.deepEqual(calls, ['remember:research-1:run-monitor'])
})

test('attachDiscoveredRun does not re-open the run already on screen', () => {
  const calls: string[] = []
  const outcome = attachDiscoveredRun(
    { sessionId: 'research-1', runId: '550e8400-e29b-41d4-a716-446655440000' },
    'research-1',
    '550e8400e29b41d4a716446655440000',
    true,
    {
      rememberRun(sessionId, runId) { calls.push(`remember:${sessionId}:${runId}`) },
      watchRun(runId, sessionId) { calls.push(`watch:${runId}:${sessionId}`) },
    },
  )

  assert.equal(outcome, 'current')
  assert.equal(calls.length, 1)
})
