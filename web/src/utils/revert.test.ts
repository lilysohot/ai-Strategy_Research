import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  REVERT_SCAN_REASON,
  diffKey,
  isRevertable,
  revertResultText,
  revertTargets,
  summarizeRevert,
} from './revert.ts'
import type { DiffFile } from '../types.ts'

function file(partial: Partial<DiffFile>): DiffFile {
  return {
    path: '/outputs/a.md',
    status: 'modified',
    source: 'file_tool',
    hunks: '',
    additions: 0,
    deletions: 0,
    ...partial,
  }
}

test('only file-tool entries are revertable; the scan class is not', () => {
  assert.equal(isRevertable(file({ source: 'file_tool' })), true)
  assert.equal(isRevertable(file({ source: 'bash_scan' })), false)
})

test('diffKey keeps the two sources apart for one path', () => {
  assert.notEqual(
    diffKey(file({ source: 'file_tool' })),
    diffKey(file({ source: 'bash_scan' })),
  )
  assert.equal(diffKey(file({})), diffKey(file({})))
})

test('revertTargets drops scan rows even when they are selected', () => {
  const files = [
    file({ path: '/outputs/a.md', source: 'file_tool' }),
    file({ path: '/outputs/b.log', source: 'bash_scan' }),
    file({ path: '/outputs/c.md', source: 'file_tool' }),
  ]
  const selected = [
    diffKey(files[0]),
    diffKey(files[1]), // selected by a stale/crafted key — must not be sent
    '/outputs/ghost.md::/outputs/ghost.md',
  ]
  assert.deepEqual(revertTargets(files, selected), ['/outputs/a.md'])
})

test('revertTargets is empty for an empty selection', () => {
  assert.deepEqual(revertTargets([file({})], []), [])
})

test('summarizeRevert counts restored+removed against everything else', () => {
  const outcome = summarizeRevert([
    { path: '/a', status: 'restored' },
    { path: '/b', status: 'removed' },
    { path: '/c', status: 'rejected', reason: 'not_snapshotted' },
    { path: '/d', status: 'failed', reason: 'io_error' },
  ])
  assert.deepEqual(outcome, { reverted: 2, rejected: 2 })
})

test('revertResultText prefers the server wording and explains the rest', () => {
  assert.equal(
    revertResultText({ path: '/c', status: 'rejected', message: '扫描发现，请人工处理' }),
    '扫描发现，请人工处理',
  )
  assert.equal(revertResultText({ path: '/a', status: 'restored' }), '已还原')
  assert.equal(revertResultText({ path: '/b', status: 'removed' }), '已删除（运行前不存在）')
  assert.equal(revertResultText({ path: '/d', status: 'failed' }), '回滚失败')
})

test('the scan reason is user-facing text, not a bare code', () => {
  assert.ok(REVERT_SCAN_REASON.length > 10)
  assert.ok(REVERT_SCAN_REASON.includes('扫描'))
})
