import { request } from './client'
import type { ApprovalDecisionValue, RunControlRecord } from '../types'

export interface Page<T> { items: T[]; next_after: string | null }
export interface Space {
  space_id: string; goal: string; goal_version: number; paused: boolean
  control_state: 'active' | 'paused' | 'stopping' | 'stopped'; control_version: number; can_control?: boolean
  participants?: { participant_id: string; session_id: string; role: string }[]
  automatic_budget?: { used: number; limit: number; remaining: number }
}
export interface LinkRun {
  run_id: string; session_id: string; status: string; pipeline_id: string; created_at: string
  finalization: { state: string; error: string | null; attempts: number; limit: number } | null
  model_snapshot?: Record<string, unknown> | null
  dispatch: { status: string; error: string | null } | null
}
export interface Delivery {
  message_id: string; phase: string; sender_id: string; recipient_id: string
  request_id: string; revises_message_id: string | null; published_at: string | null
  goal_version?: number; content_sha256?: string
  content?: { body: string; requests_execution: boolean }
  inspection: { verdict: string; explanation: string; attempts: number; limit: number; failure_kind: string | null } | null
  source_run: LinkRun | null; recipient_run: LinkRun | null
  feedback: { run: LinkRun | null; error: string | null } | null
  revisions?: string[]
  attempts?: { number: number; verdict: string; explanation: string; started_at: string; finished_at: string | null; model_snapshot?: Record<string, unknown>; input?: Record<string, unknown>; failure_kind?: string | null }[]
}
export interface ControlCommand {
  action: 'pause' | 'stop' | 'resume' | 'continue'; idempotency_key: string
  expected_version: number; reason: string; participant_id?: string; message?: string
}
export interface RecoveryCommand {
  action: 'inspection_retry' | 'admission_retry' | 'feedback_retry' | 'finalization_retry' | 'abandon_finalization' | 'extend_budget'
  idempotency_key: string; reason: string; target_id?: string; additional_runs?: number
}
export interface RecoveryRecord { id: string; actor_id: string; request: Record<string, unknown>; result: Record<string, unknown>; created_at: string }
const root = '/super-link'
const space = (id: string) => `${root}/spaces/${encodeURIComponent(id)}`
export const superLink = {
  capabilities: () => request<{ can_create: boolean; reason: string | null }>(`${root}/capabilities`),
  spaces: (after?: string) => request<Page<Space>>(`${root}/spaces`, { query: { after } }),
  create: (goal: string, creation_key: string) => request<{ space_id: string; initial_run_id: string }>(`${root}/spaces`, { method: 'POST', body: { goal, creation_key } }),
  space: (id: string) => request<Space>(space(id)),
  runs: (id: string, after?: string) => request<Page<LinkRun>>(`${space(id)}/runs`, { query: { after, limit: 50, newest_first: 'true' } }),
  deliveries: (id: string, after?: string) => request<Page<Delivery>>(`${space(id)}/deliveries`, { query: { after, limit: 50, newest_first: 'true' } }),
  delivery: (id: string, mid: string) => request<Delivery>(`${space(id)}/deliveries/${encodeURIComponent(mid)}`),
  control: (id: string, body: ControlCommand) => request<Record<string, unknown>>(`${space(id)}/control`, { method: 'POST', body }),
  recover: (id: string, body: RecoveryCommand) => request<Record<string, unknown>>(`${space(id)}/recovery`, { method: 'POST', body }),
  recoveryActions: (id: string, after?: string) => request<Page<RecoveryRecord>>(`${space(id)}/recovery-actions`, { query: { after, limit: 50, newest_first: 'true' } }),
  interventions: (id: string) => request<{ pending: RunControlRecord[]; recent: RunControlRecord[]; active_runs: LinkRun[] }>(`${space(id)}/interventions`),
  approve: (id: string, rid: string, approval_id: string, decision: ApprovalDecisionValue, replacement_command?: string) => request(`${space(id)}/runs/${encodeURIComponent(rid)}/approve`, { method: 'POST', body: { approval_id, decision, replacement_command } }),
  steer: (id: string, rid: string, message: string) => request(`${space(id)}/runs/${encodeURIComponent(rid)}/steer`, { method: 'POST', body: { message } }),
}
