/**
 * Wire types for the投研 Agent platform API.
 *
 * These mirror the response shapes produced by ``server/routes/*.py`` by hand.
 * They are intentionally *narrow* — only the fields the UI actually reads are
 * declared — so a server-side addition never silently widens the contract, and a
 * rename shows up as a type error instead of an ``undefined`` at runtime.
 *
 * The one field the backend never returns is the api_key: configs are surfaced as
 * ``masked_api_key`` only (FR-2.2). There is deliberately no ``api_key`` field on
 * {@link LlmConfig} so a future contributor cannot accidentally render one.
 */

/** Lifecycle states a run moves through (``runs.status``). */
export type RunStatus =
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed'
  | 'stopped'

export interface User {
  id: string
  username: string
  status: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
}

export interface Session {
  id: string
  title: string | null
  created_at: string | null
  updated_at: string | null
  /** Turn count, returned by the list/session endpoints. */
  turn_count?: number | null
}

export interface Turn {
  seq: number
  role: 'user' | 'assistant'
  content: string
  run_id: string | null
  created_at: string | null
}

/** Page of the conversation list (sessions are paged forward). */
export interface SessionListResponse {
  sessions: Session[]
  /** Total sessions owned by the caller — what ``has_more`` is derived from. */
  total: number
  has_more: boolean
}

/** Page of one session's turns (turns are paged backwards via ``before_seq``). */
export interface TurnListResponse {
  turns: Turn[]
  has_more: boolean
}

/** A user LLM config as returned by the API — always masked. */
export interface LlmConfig {
  id: string
  name: string
  base_url: string
  model: string
  masked_api_key: string
  is_default: boolean
  last_verify_ok?: boolean | null
  last_verified_at?: string | null
  /** Non-secret extras; may carry ``_last_verify_error`` (key-free summary). */
  params?: Record<string, unknown> | null
}

export interface TestResult {
  ok: boolean
  detail: string
}

/** POST /api/runs/{id}/approve 的 decision 枚举（§6.1，与服务端 Literal 对齐）。 */
export type ApprovalDecisionValue =
  | 'once'
  | 'reject'
  | 'session_bash'
  | 'session_all'
  | 'persist'

export interface RunSubmitResponse {
  run_id: string
  status: string
}

export interface Artifact {
  rel_path: string
  size: number
  sha256: string
  created_at: string | null
}

/** GET /api/runs/{id}/artifacts/preview (§5.4)：text/image 带内容，binary 无。 */
export interface ArtifactPreview {
  kind: 'text' | 'image' | 'binary' | 'unsupported'
  content?: string
  truncated: boolean
}

/** GET /api/runs/{id}/diff (§5.4)：worker 跑完生成的 diff.json。 */
export interface DiffFile {
  path: string
  status: 'added' | 'modified' | 'deleted'
  /** file_tool=有快照基线可 revert（P3.3）；bash_scan=仅展示。 */
  source: 'file_tool' | 'bash_scan'
  /** unified diff 全文；bash_scan 为空串（二进制文件不进 payload，§2.2）。 */
  hunks: string
  additions: number
  deletions: number
}

export interface RunDiff {
  files: DiffFile[]
}

/** POST /api/runs/{id}/revert 的逐路径结果（§6.3）。 */
export type RevertStatus = 'restored' | 'removed' | 'rejected' | 'failed'

export interface RevertResult {
  path: string
  status: RevertStatus
  /** 仅在 rejected/failed 时出现：机器可读的拒绝原因。 */
  reason?: string
  /** 面向用户的解释文案（扫描类必须给出，否则用户会以为是 bug）。 */
  message?: string
  detail?: string
}

export interface RunRevertResponse {
  run_id: string
  results: RevertResult[]
  /** 本次真正回滚掉的路径。 */
  reverted: string[]
}

export interface Usage {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cache_read_tokens: number
  cache_write_tokens: number
  reasoning_tokens: number
  llm_calls: number
}

export interface RunSummary {
  run_id: string
  status: RunStatus
  prompt?: string
  pipeline_id?: string | null
  model?: string | null
  final_answer?: string | null
  error?: string | null
  stopped_by?: string | null
  created_at?: string | null
  finished_at?: string | null
  run_dir?: string | null
  usage?: Usage | null
}

/**
 * One SSE frame from ``GET /api/runs/{id}/events``.
 *
 * ``seq`` is the trajectory line number the event was replayed from. It is the
 * reconnect cursor (``?after=seq``) and is present only on replayed events —
 * live bridge deltas have no trajectory line and omit it.
 */
export interface SseEvent {
  type: string
  ts: number
  seq?: number
  turn?: number
  content?: string | null
  thinking?: string | null
  tool_calls?: unknown[] | null
  name?: string | null
  ok?: boolean
  // True when the call never actually ran (per-turn cap, rejection, safety
  // block) — rendered as "skipped", not a clean success (§5.3).
  skipped?: boolean
  detail?: string | null
  ms?: number
  usage?: Partial<Usage> | null
  model_name?: string | null
  tool_names?: string[] | null
  max_turns?: number | null
  // Status-bar facts (§5.6): pipeline id from the worker's run_meta, the
  // context window from LoopConfig, both stamped on run_started.
  pipeline_id?: string | null
  context_limit?: number | null
  // Tool-call frames (used by T3.3 timeline cards)
  tool_call_id?: string
  tool_name?: string
  input?: unknown
  output?: unknown
  // Live streaming frames (P1.5). The worker's BridgeObserver emits one event per
  // token fragment: ``text`` is answer content, ``thinking_text`` is reasoning.
  // These are distinct from ``content``/``thinking``, which arrive once per turn
  // from the trajectory replay.
  text?: string
  thinking_text?: string
  // steer_queued (P3.1, §7): ``message`` is the redacted steer text, ``seq``
  // (overloaded with the trajectory cursor above) is the per-run steer order.
  message?: string
  // approval_requested / approval_resolved (P3.2, §6.1). ``risk`` mirrors the
  // worker's risk assessment; ``decision`` is the POSTed verdict echoed back.
  approval_id?: string
  target?: string
  reason?: string
  preview?: string
  risk?: 'normal' | 'high'
  decision?: string
  // Terminal run outcome (§5.6 / T3.1): run_failed carries the persisted reason,
  // run_stopped the initiator. They travel on the live SSE but not the *why* of a
  // failure's text beyond this field (the row is the source of truth, see §6.4).
  error?: string
  stopped_by?: string
  // True on the replay copy of a turn (whole text in one event), so the client can
  // discard it for any turn it already streamed live and avoid rendering twice.
  full?: boolean
  [key: string]: unknown
}

/** Event types that close a run's stream for good. */
export const TERMINAL_EVENT_TYPES: readonly string[] = [
  'run_completed',
  'run_failed',
  'run_stopped',
]

/**
 * One raw record from ``run/agent/trajectories/react_agent.jsonl`` as returned by
 * ``GET /api/runs/{run_id}/trace``. The ``t`` field discriminates the record kind
 * (start / llm / result / compaction); only the fields relevant to each kind are
 * populated. Kept permissive (unknown extras) because the runtime may add fields.
 */
export interface RunTraceRecord {
  t: 'start' | 'llm' | 'result' | 'compaction' | string
  ts?: number | string | null
  turn?: number | null
  // start
  model_name?: string | null
  tool_names?: string[] | null
  max_turns?: number | null
  // llm
  content?: string | null
  tool_calls?: Array<{
    id?: string
    name?: string
    args?: Record<string, unknown> | null
  }> | null
  usage?: Partial<Usage> | null
  // result
  name?: string | null
  error?: boolean | null
  result?: unknown
  ms?: number | null
  [key: string]: unknown
}

export interface RunTraceResponse {
  run_id: string
  records: RunTraceRecord[]
}
