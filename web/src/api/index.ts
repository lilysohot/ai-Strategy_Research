/**
 * Endpoint surface (T3.1 skeleton).
 *
 * One function per backend route, carrying the request/response types declared in
 * ``./types.ts``. Views should call these rather than ``fetch`` directly so the
 * auth header, error normalisation and the "never send an api_key" rule stay in
 * one place.
 *
 * The pages that consume most of this land in T3.2–T3.6; the calls are declared
 * now so the contract is reviewable before the UI is built on top of it.
 */

import { request, requestBlob } from './client'
import type {
  Account,
  AccountListResponse,
  AccountRevisionsResponse,
  ApprovalDecisionValue,
  Artifact,
  ArtifactPreview,
  BusinessEventListResponse,
  BusinessOperationResponse,
  InputRequest,
  InputRequestAnswerResponse,
  InputRequestListResponse,
  LlmConfig,
  OperationsListResponse,
  PlanListResponse,
  PlanRevisionsResponse,
  ResearchLink,
  RunControlsResponse,
  RunDiff,
  RunRerunResponse,
  RunRevertResponse,
  RunSummary,
  RunSubmitResponse,
  RunTraceResponse,
  Session,
  SessionListResponse,
  SnapshotView,
  TestResult,
  TokenResponse,
  TradesListResponse,
  TurnListResponse,
  User,
  WatchEventsListResponse,
  WatchRule,
  WatchRuleListResponse,
  WatchRuleVersionsResponse,
} from '../types'

// ── Auth (server/routes/auth.py) ────────────────────────────────
export const auth = {
  register: (username: string, password: string) =>
    request<User>('/auth/register', {
      method: 'POST',
      anonymous: true,
      body: { username, password },
    }),

  login: (username: string, password: string) =>
    request<TokenResponse>('/auth/login', {
      method: 'POST',
      anonymous: true,
      body: { username, password },
    }),

  me: () => request<User>('/auth/me'),

  logout: () => request<void>('/auth/logout', { method: 'POST' }),

  changePassword: (oldPassword: string, newPassword: string) =>
    request<void>('/auth/password', {
      method: 'POST',
      body: { old_password: oldPassword, new_password: newPassword },
    }),
}

// ── LLM configs (server/routes/models.py) ───────────────────────
export interface LlmConfigCreate {
  name: string
  base_url: string
  model: string
  /** Plaintext once, on write; stored encrypted and never returned. */
  api_key: string
  params?: Record<string, unknown> | null
  is_default?: boolean
}

export interface LlmConfigUpdate {
  name?: string
  base_url?: string
  model?: string
  api_key?: string
  params?: Record<string, unknown> | null
  is_default?: boolean
}

export const models = {
  list: () => request<LlmConfig[]>('/models'),

  create: (body: LlmConfigCreate) =>
    request<LlmConfig>('/models', { method: 'POST', body }),

  get: (id: string) => request<LlmConfig>(`/models/${encodeURIComponent(id)}`),

  update: (id: string, body: LlmConfigUpdate) =>
    request<LlmConfig>(`/models/${encodeURIComponent(id)}`, { method: 'PUT', body }),

  remove: (id: string) =>
    request<void>(`/models/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  /** Connectivity preflight: decrypts the key server-side for one probe. */
  test: (id: string) =>
    request<TestResult>(`/models/${encodeURIComponent(id)}/test`, { method: 'POST' }),
}

// ── Sessions + turns (server/routes/sessions.py) ────────────────
export const sessions = {
  create: (title?: string, firstMessage?: string) =>
    request<Session>('/sessions', {
      method: 'POST',
      body: { title: title ?? null, first_message: firstMessage ?? null },
    }),

  /** Most recent first. ``offset`` pages forward; ``has_more`` says if there is more. */
  list: (params?: { limit?: number; offset?: number }) =>
    request<SessionListResponse>('/sessions', { query: params }),

  get: (id: string) => request<Session>(`/sessions/${encodeURIComponent(id)}`),

  /**
   * One page of turns, newest last. Pass ``before_seq`` (the oldest seq already
   * held) to page backwards into older history — a long conversation is fetched
   * a page at a time rather than in one growing response.
   */
  turns: (id: string, params?: { limit?: number; before_seq?: number }) =>
    request<TurnListResponse>(`/sessions/${encodeURIComponent(id)}/turns`, {
      query: params,
    }),

  remove: (id: string) =>
    request<void>(`/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' }),
}

// ── Runs (server/routes/runs.py) ────────────────────────────────
export const runs = {
  /**
   * Submit a run. Pass ``FormData`` to attach input files (T2.10); the browser
   * sets the multipart boundary and the server writes the files into the run's
   * read-only inputs dir. Credentials are never sent here — they are resolved
   * from the user's default config server-side.
   */
  submit: (body: {
    message: string
    session_id?: string
    investment_input?: Record<string, unknown> | null
  } | FormData) =>
    request<RunSubmitResponse>('/runs', { method: 'POST', body }),

  /** One-shot replay of the trajectory timeline (no streaming). */
  trace: (runId: string, after = 0) =>
    request<RunTraceResponse>(
      `/runs/${encodeURIComponent(runId)}/trace`,
      { query: { after } },
    ),

  /**
   * The business input frozen at this run's submission (UI-06 / DATA-05).
   * A non-business (legacy) run returns 404 with ``snapshot_absent`` — callers
   * must show the empty state instead of back-filling current values.
   */
  investmentSnapshot: (runId: string) =>
    request<SnapshotView>(`/runs/${encodeURIComponent(runId)}/investment-snapshot`),

  /**
   * "用新资料重算": stops the old run, freezes current data, queues a NEW run
   * that points back at the old one via ``rerun_of_run_id``. Idempotency-keyed
   * so a timeout retry must not create two runs.
   */
  rerun: (runId: string, body: { message?: string; session_id?: string }, idempotencyKey: string) =>
    request<RunRerunResponse>(`/runs/${encodeURIComponent(runId)}/rerun`, {
      method: 'POST',
      body,
      headers: { 'Idempotency-Key': idempotencyKey },
    }),

  /** SSE endpoint — consumed by {@link openRunStream}, not by this client. */
  eventsUrl: (runId: string) =>
    `/api/runs/${encodeURIComponent(runId)}/events`,

  stop: (runId: string) =>
    request<{ run_id: string; stopped: boolean }>(
      `/runs/${encodeURIComponent(runId)}/control`,
      { method: 'POST', body: { action: 'stop' } },
    ),

  /**
   * Inject a mid-run instruction (P3.1, §6.2). Queued on the worker's stdin and
   * applied at the next tool boundary; 409 when the run already finished.
   */
  steer: (runId: string, message: string) =>
    request<{ run_id: string; queued: boolean; seq: number; control_id?: string | null }>(
      `/runs/${encodeURIComponent(runId)}/steer`,
      { method: 'POST', body: { message } },
    ),

  /**
   * Answer a pending approval (P3.2, §6.1). The decision enum is closed
   * server-side (Literal → 422 on anything else); ``replacementCommand``
   * turns a reject into redirect feedback the model sees as the declined
   * call's result (terminal ``[e]``).
   */
  approve: (
    runId: string,
    approvalId: string,
    decision: ApprovalDecisionValue,
    replacementCommand?: string,
  ) =>
    request<{ run_id: string; approved: boolean; control_id?: string | null }>(
      `/runs/${encodeURIComponent(runId)}/approve`,
      {
        method: 'POST',
        body: {
          approval_id: approvalId,
          decision,
          replacement_command: replacementCommand?.trim() || null,
        },
      },
    ),

  /**
   * Undo file-tool changes (P3.3, §6.3). Only paths a file tool snapshotted
   * are restorable; the bash-scan class comes back as a per-path ``rejected``
   * result carrying a reason, never as a failed request — a bulk selection
   * where one row is legitimately not revertable must stay usable.
   */
  revert: (runId: string, paths: string[]) =>
    request<RunRevertResponse>(`/runs/${encodeURIComponent(runId)}/revert`, {
      method: 'POST',
      body: { paths },
    }),

  /**
   * Authoritative single-run view (GET /api/runs/{id}). Used to reconcile the
   * outcome the live SSE stream reported with what the server actually persisted
   * — the stream is best-effort and never carries a failed run's *reason*, only
   * the row does (§6.4 P2 + §5.7 traceable failure).
   */
  get: (runId: string) => request<RunSummary>(`/runs/${encodeURIComponent(runId)}`),

  /**
   * Durable control history of one run (F21). Read after a refresh/reconnect to
   * rebuild what only a live SSE frame used to carry — notably an approval that
   * is still pending. ``status=pending`` narrows it to the actionable ones.
   */
  controls: (runId: string, params?: { kind?: string; status?: string }) =>
    request<RunControlsResponse>(`/runs/${encodeURIComponent(runId)}/controls`, {
      query: params,
    }),
}

// ── Durable business input requests (DATA-07) ──────────────────
export const inputRequests = {
  list: (params?: { research_id?: string; status?: string; limit?: number; offset?: number }) =>
    request<InputRequestListResponse>('/business/input-requests', { query: params }),

  get: (id: string) =>
    request<InputRequest>(`/business/input-requests/${encodeURIComponent(id)}`),

  answer: (
    id: string,
    body: {
      answer: string
      declared: Record<string, Record<string, unknown>>
      expected_versions: Record<string, number>
    },
    idempotencyKey: string,
  ) => request<InputRequestAnswerResponse>(
    `/business/input-requests/${encodeURIComponent(id)}/answers`,
    { method: 'POST', body, headers: { 'Idempotency-Key': idempotencyKey } },
  ),

  cancel: (id: string, idempotencyKey: string) =>
    request<InputRequestAnswerResponse>(
      `/business/input-requests/${encodeURIComponent(id)}/cancel`,
      { method: 'POST', headers: { 'Idempotency-Key': idempotencyKey } },
    ),
}

export const businessEvents = {
  list: (after = 0, limit = 100) =>
    request<BusinessEventListResponse>('/business/events', { query: { after, limit } }),

  markRead: (id: string) =>
    request<void>(`/business/events/${encodeURIComponent(id)}/read`, { method: 'POST' }),

  markAllRead: (through: number) =>
    request<void>('/business/events/read-all', { method: 'POST', body: { through } }),

  streamUrl: () => '/api/business/events/stream',
}

// ── Accounts / Plans / Trades (DATA-01…04 / PR-BIZ-01—04) ───────────
//
// Every write carries an Idempotency-Key and returns {replayed, operation_id, ...}.
// Amounts travel as decimal strings end-to-end (never through JS Number). Updates
// require the current ``expected_revision``; a 409 means concurrent edit.

const IDEMPOTENCY_HEADER = (key: string): Record<string, string> => ({
  'Idempotency-Key': key,
})

export const accounts = {
  create(body: {
    name: string
    base_currency: string
    declared: Record<string, Array<unknown> | string | Record<string, unknown>>
    use_case: string
    allow_incomplete: boolean
  }, idempotencyKey: string) {
    return request<BusinessOperationResponse>('/business/accounts', {
      method: 'POST',
      body: { ...body, source_kind: 'form' },
      headers: IDEMPOTENCY_HEADER(idempotencyKey),
    })
  },

  list(params?: { limit?: number; offset?: number }) {
    return request<AccountListResponse>('/business/accounts', { query: params })
  },

  get(id: string) {
    return request<Account>(`/business/accounts/${encodeURIComponent(id)}`)
  },

  update(id: string, body: {
    declared: Record<string, unknown>
    expected_revision: number
    allow_incomplete: boolean
  }, idempotencyKey: string) {
    return request<BusinessOperationResponse>(`/business/accounts/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body,
      headers: IDEMPOTENCY_HEADER(idempotencyKey),
    })
  },

  revisions(id: string, params?: { limit?: number; offset?: number }) {
    return request<AccountRevisionsResponse>(
      `/business/accounts/${encodeURIComponent(id)}/revisions`,
      { query: params },
    )
  },

  archive(id: string, idempotencyKey: string) {
    return request<BusinessOperationResponse>(`/business/accounts/${encodeURIComponent(id)}/archive`, {
      method: 'POST',
      headers: IDEMPOTENCY_HEADER(idempotencyKey),
    })
  },
}

export const plans = {
  create(researchId: string, body: {
    name: string
    declared: Record<string, unknown>
    allow_incomplete: boolean
  }, idempotencyKey: string) {
    return request<BusinessOperationResponse>(`/business/sessions/${encodeURIComponent(researchId)}/plans`, {
      method: 'POST',
      body: { ...body, source_kind: 'form' },
      headers: IDEMPOTENCY_HEADER(idempotencyKey),
    })
  },

  list(researchId: string, params?: { limit?: number; offset?: number }) {
    return request<PlanListResponse>(
      `/business/sessions/${encodeURIComponent(researchId)}/plans`,
      { query: params },
    )
  },

  update(id: string, body: {
    declared: Record<string, unknown>
    expected_revision: number
    allow_incomplete: boolean
  }, idempotencyKey: string) {
    return request<BusinessOperationResponse>(`/business/plans/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body,
      headers: IDEMPOTENCY_HEADER(idempotencyKey),
    })
  },

  revisions(id: string, params?: { limit?: number; offset?: number }) {
    return request<PlanRevisionsResponse>(
      `/business/plans/${encodeURIComponent(id)}/revisions`,
      { query: params },
    )
  },

  archive(id: string, idempotencyKey: string) {
    return request<BusinessOperationResponse>(`/business/plans/${encodeURIComponent(id)}/archive`, {
      method: 'POST',
      headers: IDEMPOTENCY_HEADER(idempotencyKey),
    })
  },
}

export const link = {
  get(researchId: string) {
    return request<ResearchLink>(`/business/sessions/${encodeURIComponent(researchId)}/link`)
  },

  set(researchId: string, body: {
    account_id: string | null
    primary_plan_id: string | null
  }, idempotencyKey: string) {
    return request<BusinessOperationResponse>(`/business/sessions/${encodeURIComponent(researchId)}/link`, {
      method: 'PUT',
      body,
      headers: IDEMPOTENCY_HEADER(idempotencyKey),
    })
  },
}

export const trades = {
  register(accountId: string, body: {
    declared: Record<string, unknown>
  }, idempotencyKey: string) {
    return request<BusinessOperationResponse>(`/business/accounts/${encodeURIComponent(accountId)}/trades`, {
      method: 'POST',
      body: { ...body, source_kind: 'form' },
      headers: IDEMPOTENCY_HEADER(idempotencyKey),
    })
  },

  list(params?: { account_id?: string; limit?: number; offset?: number }) {
    return request<TradesListResponse>('/business/trades', { query: params })
  },

  correct(tradeId: string, body: { declared: Record<string, unknown> }, idempotencyKey: string) {
    return request<BusinessOperationResponse>(`/business/trades/${encodeURIComponent(tradeId)}/correct`, {
      method: 'POST',
      body: { ...body, source_kind: 'form' },
      headers: IDEMPOTENCY_HEADER(idempotencyKey),
    })
  },
}

export const operations = {
  /** Recent writes, refreshed after a page reload (UI-04 幂等恢复). */
  list(params?: { scope?: string; limit?: number }) {
    return request<OperationsListResponse>('/business/operations', { query: params })
  },

  get(id: string) {
    return request<BusinessOperationResponse>(`/business/operations/${encodeURIComponent(id)}`)
  },
}

// ── Watch rules + events (DATA-09…11 / PR-WATCH-01…04) ─────────────

export const watchRules = {
  create(researchId: string, body: {
    name: string
    spec: Record<string, unknown>
    plan_id?: string | null
  }, idempotencyKey: string) {
    return request<BusinessOperationResponse>(`/business/sessions/${encodeURIComponent(researchId)}/watch-rules`, {
      method: 'POST',
      body: { ...body, source_kind: 'form' },
      headers: IDEMPOTENCY_HEADER(idempotencyKey),
    })
  },

  list(params?: { research_id?: string; status?: string; limit?: number; offset?: number }) {
    return request<WatchRuleListResponse>('/business/watch-rules', { query: params })
  },

  get(id: string) {
    return request<WatchRule>(`/business/watch-rules/${encodeURIComponent(id)}`)
  },

  update(id: string, patch: Record<string, unknown>, expectedVersion: number, idempotencyKey: string) {
    return request<BusinessOperationResponse>(`/business/watch-rules/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: { ...patch, expected_version: expectedVersion },
      headers: IDEMPOTENCY_HEADER(idempotencyKey),
    })
  },

  versions(id: string, params?: { limit?: number; offset?: number }) {
    return request<WatchRuleVersionsResponse>(
      `/business/watch-rules/${encodeURIComponent(id)}/versions`,
      { query: params },
    )
  },

  statusOp(id: string, action: 'pause' | 'resume' | 'cancel', expectedVersion: number, idempotencyKey: string) {
    return request<BusinessOperationResponse>(`/business/watch-rules/${encodeURIComponent(id)}/${action}`, {
      method: 'POST',
      body: { expected_version: expectedVersion },
      headers: IDEMPOTENCY_HEADER(idempotencyKey),
    })
  },
}

export const watchEvents = {
  list(params?: { research_id?: string; status?: string; limit?: number; offset?: number }) {
    return request<WatchEventsListResponse>('/business/watch-events', { query: params })
  },
}

// ── Research delete (DATA-13 / PR-BIZ-06) ──────────────────────────

export const researchDelete = {
  remove(researchId: string, idempotencyKey: string) {
    return request<BusinessOperationResponse>(`/business/sessions/${encodeURIComponent(researchId)}`, {
      method: 'DELETE',
      headers: IDEMPOTENCY_HEADER(idempotencyKey),
    })
  },
}

// ── Artifacts (server/routes/artifacts.py) ──────────────────────
export const artifacts = {
  list: (runId: string) =>
    request<{ run_id: string; artifacts: Artifact[] }>(
      `/runs/${encodeURIComponent(runId)}/artifacts`,
    ),

  /**
   * Read-only preview (P2.3). ``rel_path`` is server-authoritative and passed
   * through unchanged — containment stays inside resolve_artifact_path.
   */
  preview: (runId: string, relPath: string) =>
    request<ArtifactPreview>(
      `/runs/${encodeURIComponent(runId)}/artifacts/preview`,
      { query: { path: relPath } },
    ),

  /** Run diff (P2.5). 404 when the run produced no diff.json — callers treat that as "no changes". */
  diff: (runId: string) =>
    request<RunDiff>(`/runs/${encodeURIComponent(runId)}/diff`),

  /**
   * Authenticated download: fetches the file with the bearer header and triggers
   * a save dialog under the artifact's own basename.
   *
   * Preferred over a plain ``<a download>``: that cannot carry an Authorization
   * header, so it only works while the SPA happens to be same-origin with the
   * API. ``rel_path`` is server-authoritative — the backend resolves it inside
   * the run's outputs dir and rejects traversal, so it is passed through
   * unchanged rather than being sanitised here (sanitising twice is how a path
   * check gets weakened).
   */
  async download(runId: string, relPath: string): Promise<void> {
    const blob = await requestBlob(
      `/runs/${encodeURIComponent(runId)}/artifacts/download`,
      { path: relPath },
    )
    const filename = relPath.split('/').pop() || 'artifact'
    const url = URL.createObjectURL(blob)
    try {
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = filename
      anchor.rel = 'noopener'
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
    } finally {
      // Revoking synchronously can cancel the download in some browsers; one
      // tick is enough and still avoids leaking the blob.
      setTimeout(() => URL.revokeObjectURL(url), 0)
    }
  },
}
