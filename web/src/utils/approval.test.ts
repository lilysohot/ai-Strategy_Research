import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  buildApprovalRequest,
  canSubmitApproval,
  isApprovalResolvedFor,
} from './approval.ts'
import type { SseEvent } from '../types.ts'

function approvalEvent(partial: Partial<SseEvent> = {}): SseEvent {
  return {
    type: 'approval_requested',
    ts: 1000,
    approval_id: 'a-1',
    tool_name: 'bash',
    target: 'rm -rf build/',
    reason: '需要确认的命令',
    preview: 'rm -rf build/',
    risk: 'normal',
    ...partial,
  }
}

test('buildApprovalRequest maps the §6.1 event contract to camelCase', () => {
  const req = buildApprovalRequest(approvalEvent())
  assert.deepEqual(req, {
    approvalId: 'a-1',
    toolName: 'bash',
    target: 'rm -rf build/',
    reason: '需要确认的命令',
    preview: 'rm -rf build/',
    risk: 'normal',
  })
})

test('buildApprovalRequest keeps the high-risk flag', () => {
  assert.equal(buildApprovalRequest(approvalEvent({ risk: 'high' }))?.risk, 'high')
})

test('buildApprovalRequest tolerates a missing risk as normal', () => {
  const event = approvalEvent()
  delete event.risk
  assert.equal(buildApprovalRequest(event)?.risk, 'normal')
})

test('buildApprovalRequest ignores unrelated events', () => {
  assert.equal(buildApprovalRequest({ type: 'tool_started', ts: 1 }), null)
})

test('buildApprovalRequest rejects a frame without an approval_id', () => {
  const event = approvalEvent()
  delete event.approval_id
  assert.equal(buildApprovalRequest(event), null)
})

test('normal risk can be approved without typing anything', () => {
  assert.equal(canSubmitApproval('normal', ''), true)
})

test('high risk requires the literal confirmation "yes"', () => {
  assert.equal(canSubmitApproval('high', ''), false)
  assert.equal(canSubmitApproval('high', 'y'), false)
  assert.equal(canSubmitApproval('high', 'YES'), false)
  assert.equal(canSubmitApproval('high', 'no'), false)
  assert.equal(canSubmitApproval('high', 'yes'), true)
})

test('high-risk confirmation tolerates surrounding whitespace only', () => {
  assert.equal(canSubmitApproval('high', ' yes '), true)
  assert.equal(canSubmitApproval('high', ' yes no'), false)
})

test('a resolved event matching the pending request clears it', () => {
  const pending = buildApprovalRequest(approvalEvent())
  assert.equal(
    isApprovalResolvedFor(pending, { type: 'approval_resolved', ts: 2, approval_id: 'a-1' }),
    true,
  )
})

test('a resolved event for another request does not clear the pending one', () => {
  const pending = buildApprovalRequest(approvalEvent())
  assert.equal(
    isApprovalResolvedFor(pending, { type: 'approval_resolved', ts: 2, approval_id: 'a-2' }),
    false,
  )
})

test('a resolved event without an id clears defensively', () => {
  const pending = buildApprovalRequest(approvalEvent())
  assert.equal(isApprovalResolvedFor(pending, { type: 'approval_resolved', ts: 2 }), true)
})

test('nothing is cleared when no request is pending', () => {
  assert.equal(
    isApprovalResolvedFor(null, { type: 'approval_resolved', ts: 2, approval_id: 'a-1' }),
    false,
  )
})
