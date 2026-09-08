/**
 * Unit tests for the activity-timeline status semantics (cli-web-parity §5.3).
 *
 * Run with the built-in runner (the project has no vitest and cannot install
 * one offline):
 *
 *   node --experimental-strip-types --test web/src/utils/activity.test.ts
 *
 * The module under test must stay dependency-free (no vue/pinia imports) so
 * these tests can execute on a bare node binary.
 */
import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  interruptInFlight,
  statusLabel,
  statusTagType,
  stepSummary,
  toolStepStatus,
  type StepStatus,
} from './activity.ts'

test('toolStepStatus maps a clean result to done', () => {
  assert.equal(toolStepStatus({ ok: true }), 'done')
})

test('toolStepStatus maps a failed result to error', () => {
  assert.equal(toolStepStatus({ ok: false }), 'error')
})

test('toolStepStatus maps a never-ran result to skipped regardless of ok', () => {
  assert.equal(toolStepStatus({ ok: true, skipped: true }), 'skipped')
  assert.equal(toolStepStatus({ ok: false, skipped: true }), 'skipped')
})

test('toolStepStatus defaults to done when ok is absent (tolerant replay)', () => {
  assert.equal(toolStepStatus({}), 'done')
})

test('interruptInFlight marks only running tool steps interrupted', () => {
  const steps: Array<{ kind: string; status?: StepStatus }> = [
    { kind: 'tool', status: 'running' },
    { kind: 'tool', status: 'done' },
    { kind: 'tool', status: 'error' },
    { kind: 'tool', status: 'skipped' },
    { kind: 'thinking' },
  ]
  const changed = interruptInFlight(steps)
  assert.equal(changed, 1)
  assert.equal(steps[0].status, 'interrupted')
  assert.equal(steps[1].status, 'done')
  assert.equal(steps[2].status, 'error')
  assert.equal(steps[3].status, 'skipped')
})

test('interruptInFlight is a no-op when nothing is running', () => {
  const steps: Array<{ kind: string; status?: StepStatus }> = [
    { kind: 'tool', status: 'done' },
  ]
  assert.equal(interruptInFlight(steps), 0)
  assert.equal(steps[0].status, 'done')
})

test('stepSummary surfaces the most descriptive input key', () => {
  assert.equal(stepSummary({ name: 'bash', input: { command: 'ls -la' } }), 'ls -la')
  assert.equal(stepSummary({ name: 'read_file', input: { path: '/outputs/a.md' } }), '/outputs/a.md')
})

test('stepSummary flattens newlines and truncates long values', () => {
  const long = 'x'.repeat(120)
  const summary = stepSummary({ name: 'bash', input: { command: `echo a\necho b\n${long}` } })
  assert.ok(!summary.includes('\n'), 'summary must be single-line')
  assert.ok(summary.length <= 81, `summary too long: ${summary.length}`)
  assert.ok(summary.startsWith('echo a echo b'))
})

test('stepSummary falls back to stringified input and empty string', () => {
  assert.equal(stepSummary({ name: 't', input: 'raw string' }), 'raw string')
  assert.equal(stepSummary({ name: 't', input: { unrelated: 1 } }), '')
  assert.equal(stepSummary({ name: 't' }), '')
})

test('statusLabel covers the five terminal-aligned states', () => {
  assert.equal(statusLabel('running'), '调用中')
  assert.equal(statusLabel('done'), '完成')
  assert.equal(statusLabel('error'), '失败')
  assert.equal(statusLabel('skipped'), '跳过')
  assert.equal(statusLabel('interrupted'), '已中断')
  assert.equal(statusLabel(undefined), '')
})

test('statusTagType maps states to element-plus tag types', () => {
  assert.equal(statusTagType('running'), 'warning')
  assert.equal(statusTagType('done'), 'success')
  assert.equal(statusTagType('error'), 'danger')
  assert.equal(statusTagType('skipped'), 'info')
  assert.equal(statusTagType('interrupted'), 'warning')
  assert.equal(statusTagType(undefined), 'info')
})
