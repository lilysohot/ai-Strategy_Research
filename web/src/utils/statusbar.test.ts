/**
 * Unit tests for the status-bar helpers (cli-web-parity §5.6).
 *
 * Same runner as activity.test.ts — bare node, no vitest:
 *
 *   node --experimental-strip-types --test web/src/utils/statusbar.test.ts
 */
import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  accumulateUsage,
  formatElapsed,
  mergeRunMeta,
  type RunMeta,
  type UsageTotals,
} from './statusbar.ts'

test('mergeRunMeta keeps known fields and drops empties', () => {
  const meta = mergeRunMeta(
    {},
    {
      pipeline_id: 'stateful-react-agent',
      model_name: 'gpt-x',
      tool_names: ['bash', 'read_file'],
      max_turns: 60,
      context_limit: 120000,
    },
  )
  assert.deepEqual(meta, {
    pipelineId: 'stateful-react-agent',
    modelName: 'gpt-x',
    toolNames: ['bash', 'read_file'],
    maxTurns: 60,
    contextLimit: 120000,
  })
})

test('mergeRunMeta fills later-arriving fields without clobbering', () => {
  // The live run_started arrives first (pipeline/model via run_meta), then the
  // replayed copy adds tool_names; nothing already known may be lost.
  const first = mergeRunMeta({}, { pipeline_id: 'p', model_name: 'm' })
  const second = mergeRunMeta(first, { tool_names: ['bash'], max_turns: 60 })
  assert.equal(second.pipelineId, 'p')
  assert.equal(second.modelName, 'm')
  assert.deepEqual(second.toolNames, ['bash'])
  assert.equal(second.maxTurns, 60)
})

test('mergeRunMeta ignores null/undefined/wrong-type fields', () => {
  const meta = mergeRunMeta({}, {
    pipeline_id: null,
    model_name: undefined,
    tool_names: 'not-an-array',
    max_turns: 0,
    context_limit: null,
  })
  assert.deepEqual(meta, {})
})

const ZERO: UsageTotals = { prompt: 0, completion: 0, total: 0, cacheRead: 0, cacheWrite: 0 }

test('accumulateUsage sums per-turn deltas', () => {
  let totals = { ...ZERO }
  totals = accumulateUsage(totals, { prompt_tokens: 100, completion_tokens: 10, total_tokens: 110 })
  totals = accumulateUsage(totals, { prompt_tokens: 50, completion_tokens: 5, total_tokens: 55 })
  assert.deepEqual(totals, { prompt: 150, completion: 15, total: 165, cacheRead: 0, cacheWrite: 0 })
})

test('accumulateUsage tolerates missing usage', () => {
  const totals = accumulateUsage({ prompt: 1, completion: 2, total: 3, cacheRead: 0, cacheWrite: 0 }, undefined)
  assert.deepEqual(totals, { prompt: 1, completion: 2, total: 3, cacheRead: 0, cacheWrite: 0 })
})

// T2.11 口径：provider 别名走回退链（input/output tokens），total 缺失或为 0 时
// 由 prompt + completion 推导，cache 读/写分开累计。
test('accumulateUsage mirrors aggregate_usage alias fallback (input/output tokens)', () => {
  const totals = accumulateUsage(ZERO, {
    input_tokens: 100,
    output_tokens: 20,
    total_tokens: 120,
    cache_read_tokens: 30,
    cache_write_tokens: 5,
  })
  assert.deepEqual(totals, { prompt: 100, completion: 20, total: 120, cacheRead: 30, cacheWrite: 5 })
})

test('accumulateUsage derives total when gateway reports zero', () => {
  const totals = accumulateUsage(ZERO, { prompt_tokens: 100, completion_tokens: 10, total_tokens: 0 })
  assert.deepEqual(totals, { prompt: 100, completion: 10, total: 110, cacheRead: 0, cacheWrite: 0 })
})

test('accumulateUsage maps legacy cache aliases without double counting', () => {
  const totals = accumulateUsage(ZERO, {
    prompt_tokens: 10,
    completion_tokens: 2,
    total_tokens: 12,
    cached_tokens: 8,
    cache_creation_tokens: 3,
  })
  assert.deepEqual(totals, { prompt: 10, completion: 2, total: 12, cacheRead: 8, cacheWrite: 3 })
})

test('formatElapsed renders terminal-style durations', () => {
  assert.equal(formatElapsed(0), '0s')
  assert.equal(formatElapsed(42_000), '42s')
  assert.equal(formatElapsed(65_000), '1m05s')
  assert.equal(formatElapsed(3_723_000), '1h02m')
})
