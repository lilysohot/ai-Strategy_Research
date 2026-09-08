import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  classifyDiffLines,
  diffStatusLabel,
  diffStatusTagType,
  summarizeDiff,
} from './diff.ts'
import type { DiffFile } from '../types.ts'

function file(partial: Partial<DiffFile>): DiffFile {
  return {
    path: '/outputs/a.md',
    status: 'modified',
    source: 'file_tool',
    hunks: '',
    additions: 0,
    deletions: 0,
    binary: false,
    ...partial,
  }
}

test('summarizeDiff totals files/additions/deletions; empty is all zero', () => {
  const empty = summarizeDiff([])
  assert.deepEqual(empty, { files: 0, additions: 0, deletions: 0 })

  const summary = summarizeDiff([
    file({ additions: 3, deletions: 1 }),
    file({ additions: 2, deletions: 0 }),
  ])
  assert.deepEqual(summary, { files: 2, additions: 5, deletions: 1 })
})

test('diffStatusLabel and diffStatusTagType cover the three statuses', () => {
  assert.equal(diffStatusLabel('added'), '新增')
  assert.equal(diffStatusLabel('modified'), '修改')
  assert.equal(diffStatusLabel('deleted'), '删除')
  assert.equal(diffStatusTagType('added'), 'success')
  assert.equal(diffStatusTagType('modified'), 'warning')
  assert.equal(diffStatusTagType('deleted'), 'danger')
})

test('classifyDiffLines sorts unified lines into add/del/hunk/meta/ctx', () => {
  const hunks = [
    '--- a//outputs/a.md',
    '+++ b//outputs/a.md',
    '@@ -1,2 +1,2 @@',
    'ctx line',
    '-old line',
    '+new line',
  ].join('\n')
  const lines = classifyDiffLines(hunks)
  assert.deepEqual(
    lines.map((l) => l.type),
    ['meta', 'meta', 'hunk', 'ctx', 'del', 'add'],
  )
  assert.equal(lines[4].text, '-old line')
  assert.equal(lines[5].text, '+new line')
})

test('classifyDiffLines keeps blank context lines and drops the trailing newline', () => {
  const lines = classifyDiffLines('@@ -1 +1 @@\n+a\n\n')
  assert.deepEqual(
    lines.map((l) => l.type),
    ['hunk', 'add', 'ctx'],
  )
})
