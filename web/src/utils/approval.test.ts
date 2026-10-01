import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  approvalRequestFromRecord,
  buildApprovalRequest,
  canSubmitApproval,
  isApprovalResolvedFor,
} from './approval.ts'
import type { RunControlRecord, SseEvent } from '../types.ts'

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

function pendingRecord(partial: Partial<RunControlRecord> = {}): RunControlRecord {
  return {
    control_id: 'a-1',
    run_id: 'r-1',
    kind: 'approval',
    status: 'pending',
    request: {
      tool_name: 'bash',
      target: 'rm -rf build/',
      reason: '需要确认的命令',
      preview: 'rm -rf build/',
      risk: 'normal',
    },
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

test('approvalRequestFromRecord rebuilds the same dialog shape from a record', () => {
  // F21: the recovery path must not invent a second rendering contract.
  assert.deepEqual(approvalRequestFromRecord(pendingRecord()), {
    approvalId: 'a-1',
    toolName: 'bash',
    target: 'rm -rf build/',
    reason: '需要确认的命令',
    preview: 'rm -rf build/',
    risk: 'normal',
  })
})

test('approvalRequestFromRecord keeps a high-risk record high', () => {
  const record = pendingRecord({ request: { risk: 'high', tool_name: 'bash' } })
  assert.equal(approvalRequestFromRecord(record)?.risk, 'high')
})

test('approvalRequestFromRecord refuses anything that is not an open approval', () => {
  // A decided approval must never raise a dialog again after a refresh.
  for (const record of [
    pendingRecord({ status: 'adopted' }),
    pendingRecord({ status: 'rejected' }),
    pendingRecord({ kind: 'steer', status: 'pending' }),
  ]) {
    assert.equal(approvalRequestFromRecord(record), null)
  }
})

test('approvalRequestFromRecord tolerates a record without a request body', () => {
  const request = approvalRequestFromRecord(pendingRecord({ request: {} }))
  assert.equal(request?.toolName, 'tool')
  assert.equal(request?.risk, 'normal')
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
