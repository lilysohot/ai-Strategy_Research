/**
 * Transcript filter/search/report unit tests (P2.6 §5.5).
 *
 * Pure logic only — the ChatView wiring (filter buttons, find bar, jump/copy)
 * is exercised manually; these tests pin the semantics the terminal commands
 * (/filter, /find, Ctrl-G, Ctrl-Y) map onto.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'

import { filterSteps, findMatches, reportText } from './transcript.ts'
import type { RunStep } from '../stores/runs'

function step(partial: Partial<RunStep> & { id: number; kind: RunStep['kind'] }): RunStep {
  return { ...partial } as RunStep
}

const SAMPLE: RunStep[] = [
  step({ id: 0, kind: 'thinking', turn: 1, content: '分析目录结构' }),
  step({ id: 1, kind: 'tool', turn: 1, name: 'bash', status: 'done' }),
  step({ id: 2, kind: 'text', turn: 1, content: '第一段回复' }),
  step({ id: 3, kind: 'tool', turn: 2, name: 'create_file', status: 'error' }),
  step({ id: 4, kind: 'thinking', turn: 2, content: '重试写入' }),
  step({ id: 5, kind: 'text', turn: 2, content: '最终报告：完成' }),
]

test('filterSteps keeps everything for "all"', () => {
  assert.equal(filterSteps(SAMPLE, 'all').length, SAMPLE.length)
})

test('filterSteps "thinking" keeps only thinking steps', () => {
  assert.deepEqual(
    filterSteps(SAMPLE, 'thinking').map((s) => s.id),
    [0, 4],
  )
})

test('filterSteps "tools" keeps only tool steps', () => {
  assert.deepEqual(
    filterSteps(SAMPLE, 'tools').map((s) => s.id),
    [1, 3],
  )
})

test('filterSteps "errors" keeps only errored tool steps', () => {
  assert.deepEqual(
    filterSteps(SAMPLE, 'errors').map((s) => s.id),
    [3],
  )
})

test('filterSteps "report" keeps only the last text step', () => {
  assert.deepEqual(
    filterSteps(SAMPLE, 'report').map((s) => s.id),
    [5],
  )
})

test('filterSteps "report" yields nothing without text steps', () => {
  const noText = SAMPLE.filter((s) => s.kind !== 'text')
  assert.deepEqual(filterSteps(noText, 'report'), [])
})

test('findMatches returns step ids in order, case-insensitive, matching tool names', () => {
  const steps: RunStep[] = [
    step({ id: 7, kind: 'text', content: 'Create the report' }),
    step({ id: 8, kind: 'tool', name: 'bash' }),
    step({ id: 9, kind: 'thinking', content: 'create_file 写入中' }),
  ]
  assert.deepEqual(findMatches(steps, 'CREATE'), [7, 9])
  assert.deepEqual(findMatches(steps, 'bash'), [8])
})

test('findMatches returns nothing for empty query or no hit', () => {
  assert.deepEqual(findMatches(SAMPLE, ''), [])
  assert.deepEqual(findMatches(SAMPLE, '不存在的字串'), [])
})

test('reportText returns the last text step content', () => {
  assert.equal(reportText(SAMPLE), '最终报告：完成')
})

test('reportText returns empty string without text steps', () => {
  assert.equal(reportText(SAMPLE.filter((s) => s.kind !== 'text')), '')
})
