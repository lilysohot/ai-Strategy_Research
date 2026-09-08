/**
 * Approval-dialog logic (P3.2, §6.1).
 *
 * Pure helpers extracted from the dialog/store so the fail-closed rules —
 * default focus on reject, high-risk requiring the typed word "yes" — are
 * unit-testable without a DOM. The backend gate already fails closed on
 * timeout; this layer only decides what the UI enables.
 */

import type { SseEvent } from '../types.ts'

/** One pending ``approval_requested`` in the shape the dialog renders. */
export interface ApprovalRequest {
  approvalId: string
  toolName: string
  target: string
  reason: string
  preview: string
  risk: 'normal' | 'high'
}

/** Parse an ``approval_requested`` frame; ``null`` for anything else. */
export function buildApprovalRequest(event: SseEvent): ApprovalRequest | null {
  if (event.type !== 'approval_requested' || typeof event.approval_id !== 'string') {
    return null
  }
  return {
    approvalId: event.approval_id,
    toolName: typeof event.tool_name === 'string' ? event.tool_name : 'tool',
    target: typeof event.target === 'string' ? event.target : '',
    reason: typeof event.reason === 'string' ? event.reason : '',
    preview: typeof event.preview === 'string' ? event.preview : '',
    risk: event.risk === 'high' ? 'high' : 'normal',
  }
}

/**
 * Whether the approve button may fire. Mirrors the terminal's gate: risky
 * commands demand the literal word ``yes`` (not merely a click), everything
 * else approves on click. Whitespace around the word is tolerated — paste
 * artifacts should not force a retyping — but case is not.
 */
export function canSubmitApproval(risk: ApprovalRequest['risk'], confirmText: string): boolean {
  if (risk !== 'high') return true
  return confirmText.trim() === 'yes'
}

/**
 * Whether an ``approval_resolved`` frame closes the currently shown request.
 * An exact id match is the normal path; a frame without an id clears
 * defensively (the gate always sends the id, but a stale dialog is worse than
 * a cleared one), and a mismatched id is someone else's resolution.
 */
export function isApprovalResolvedFor(
  pending: ApprovalRequest | null,
  event: SseEvent,
): boolean {
  if (!pending || event.type !== 'approval_resolved') return false
  if (typeof event.approval_id !== 'string') return true
  return event.approval_id === pending.approvalId
}
