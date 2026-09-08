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
  ApprovalDecisionValue,
  Artifact,
  ArtifactPreview,
  LlmConfig,
  RunDiff,
  RunRevertResponse,
  RunSummary,
  RunSubmitResponse,
  RunTraceResponse,
  Session,
  TestResult,
  TokenResponse,
  Turn,
  User,
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

  list: () => request<{ sessions: Session[] }>('/sessions'),

  get: (id: string) => request<Session>(`/sessions/${encodeURIComponent(id)}`),

  turns: (id: string) =>
    request<{ turns: Turn[] }>(`/sessions/${encodeURIComponent(id)}/turns`),

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
  submit: (body: { message: string; session_id?: string } | FormData) =>
    request<RunSubmitResponse>('/runs', { method: 'POST', body }),

  /** One-shot replay of the trajectory timeline (no streaming). */
  trace: (runId: string, after = 0) =>
    request<RunTraceResponse>(
      `/runs/${encodeURIComponent(runId)}/trace`,
      { query: { after } },
    ),

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
    request<{ run_id: string; queued: boolean; seq: number }>(
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
    request<{ run_id: string; approved: boolean }>(
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
