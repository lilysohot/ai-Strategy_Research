import test from 'node:test'
import assert from 'node:assert/strict'

import type { Turn } from '@/types'
import { dedupeAssistantTurns, sameRunId } from './chat.ts'

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
