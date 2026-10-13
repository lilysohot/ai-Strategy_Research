import assert from 'node:assert/strict'
import { test } from 'node:test'
import { tokenBreakdown } from './tokenUsage.ts'

test('reference screenshot: reasoning is part of output and hits are part of input', () => {
  const result = tokenBreakdown({
    prompt_tokens: 244551, completion_tokens: 2886,
    cache_read_tokens: 244352, cache_write_tokens: 0, reasoning_tokens: 1715,
  })
  assert.equal(result.total, 247437)
  assert.equal(result.miss, 199)
  assert.equal(result.reply, 1171)
  assert.equal(result.hitRate?.toFixed(1), '99.9')
})

test('cache writes are neither hits nor additional prompt tokens', () => {
  const result = tokenBreakdown({
    prompt_tokens: 100, completion_tokens: 20, cached_tokens: 90,
    cache_read_tokens: 60, cache_write_tokens: 30, reasoning_tokens: 5,
  })
  assert.equal(result.total, 120)
  assert.equal(result.read, 60)
  assert.equal(result.miss, 10)
  assert.equal(result.hitRate, 60)
})

test('absent/unavailable usage never becomes verified zero consumption', () => {
  assert.equal(tokenBreakdown(null).total, null)
  assert.equal(tokenBreakdown({ prompt_tokens: 0, completion_tokens: 0, status: 'unavailable' }).total, null)
  assert.equal(tokenBreakdown({ prompt_tokens: 0, completion_tokens: 0, status: 'partial', llm_calls: 0 }).total, null)
  assert.equal(tokenBreakdown({ prompt_tokens: 0, completion_tokens: 0, status: 'complete' }).total, 0)
  assert.equal(tokenBreakdown({ prompt_tokens: 10, completion_tokens: 2 }).reasoning, null)
})

test('invalid subsets cannot produce negative values or overflowing cache bars', () => {
  const result = tokenBreakdown({
    prompt_tokens: 10, completion_tokens: 2, cache_read_tokens: 11,
    cache_write_tokens: 1, reasoning_tokens: 5,
  })
  assert.equal(result.miss, null)
  assert.equal(result.reply, null)
  assert.equal(result.hitRate, null)
})
