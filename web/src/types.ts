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

export type InputRequestStatus = 'pending' | 'answered' | 'cancelled' | 'expired'

export interface InputRequestField {
  name: string
  unit?: string | null
  currency?: string | null
  known_value?: unknown
  reason?: string | null
}

export interface InputRequestAnswer {
  revision: number
  answer: string
  declared: Record<string, unknown>
  outcome: 'pending_clarification' | 'answered'
  created_at: string | null
}

export interface InputRequest {
  id: string
  research_id: string
  source_run_id: string | null
  watch_event_id: string | null
  follow_up_run_id: string | null
  use_case: string
  status: InputRequestStatus
  revision: number
  fields: InputRequestField[]
  known_versions: Record<string, number>
  current_versions: Record<string, number>
  collected: Record<string, Record<string, unknown>>
  remaining_fields: string[]
  expires_at: string | null
  created_at: string | null
  updated_at: string | null
  answers?: InputRequestAnswer[]
}

export interface InputRequestListResponse {
  requests: InputRequest[]
  total: number
  has_more: boolean
}

export interface InputRequestAnswerResponse {
  request_id: string
  status: InputRequestStatus
  revision: number
  follow_up_run_id: string | null
  operation_id: string
  replayed: boolean
  remaining_fields?: string[]
}

// ——— 业务资料（DATA-01…04 / accounts.plans.trades） ——————————————————————

/** 可写的业务对象响应信封：幂等回放标记 + 会话内操作标识。 */
export interface BusinessOperationResponse {
  replayed: boolean
  operation_id: string
  [field: string]: unknown
}

/** 一次业务写操作的持久回执（幂等恢复用，GET /api/business/operations）。 */
export interface OperationRecord {
  operation_id: string
  scope: string
  replayed: boolean
  status: string
  created_at: string | null
  request?: Record<string, unknown>
  result?: Record<string, unknown>
  [field: string]: unknown
}

export interface OperationsListResponse {
  operations: OperationRecord[]
}

export interface AccountValues {
  total_capital: string | null
  available_capital: string | null
  capital_basis: string | null
  currency: string | null
  as_of: string | null
  record_state: string | null
}

export interface Account {
  id: string
  name: string
  base_currency: string
  archived: boolean
  revision: number
  updated_at: string | null
  values: AccountValues
}

export interface AccountListResponse {
  accounts: Account[]
  total: number
  has_more: boolean
}

export interface AccountRevision {
  revision: number
  created_at: string | null
  source_kind: string | null
  changed_fields: string[]
  values: AccountValues
}

export interface AccountRevisionsResponse {
  revisions: AccountRevision[]
}

export interface PlanValues {
  symbol: string | null
  market: string | null
  asset_type: string | null
  direction: string | null
  /** 计划不含价格（2026-10-08 口径）：读接口不再返回计划价列。 */
  allocated_capital: string | null
  target_price: string | null
  target_profit: { value: string | null; unit: string | null } | null
  risk_budget: { value: string | null; unit: string | null }
  position_limit: { value: string | null; unit: string | null }
  time_window: string | null
  invalidation: string | null
  profit_loss_ratio: { value: string | null; definition: string | null }
  currency: string | null
  as_of: string | null
  record_state: string | null
}

export interface Plan {
  id: string
  research_id: string
  name: string
  status: string
  archived: boolean
  revision: number
  values: PlanValues
}

export interface PlanListResponse {
  plans: Plan[]
}

export interface PlanRevision {
  revision: number
  created_at: string | null
  source_kind: string | null
  changed_fields: string[]
  values: PlanValues
}

export interface PlanRevisionsResponse {
  revisions: PlanRevision[]
}

export interface ResearchLink {
  research_id: string
  account_id: string | null
  primary_plan_id: string | null
  updated_at?: string | null
}

export type TradeSide = 'buy' | 'sell'
export type TradeStatus = 'active' | 'superseded' | string

export interface Trade {
  id: string
  account_id: string
  symbol: string
  market: string
  side: TradeSide
  quantity: string | null
  price: string | null
  currency: string
  fees: string | null
  traded_at: string | null
  status: TradeStatus
  corrects_id: string | null
  source_kind: string | null
  created_at: string | null
}

export interface TradesListResponse {
  trades: Trade[]
}

// ——— 监控规则（DATA-09…11 / watch-rules + events） ——————————————————————

export interface WatchRule {
  id: string
  research_id: string
  plan_id: string | null
  name: string
  status: string
  current_version: number
  archived?: boolean
  spec?: Record<string, unknown>
  created_at?: string | null
  [field: string]: unknown
}

export interface WatchRuleListResponse {
  rules: WatchRule[]
  total: number
  has_more: boolean
}

export interface WatchRuleVersionsResponse {
  versions: Array<Record<string, unknown>>
}

export interface WatchEvent {
  id: string
  research_id: string
  rule_id: string
  run_id: string | null
  status: string
  triggered_at: string | null
  created_at: string | null
  [field: string]: unknown
}

export interface WatchEventsListResponse {
  events: WatchEvent[]
  total: number
  has_more: boolean
}

// ——— 分析依据 / 重算（UI-06，DATA-05/06） ——————————————————————————————

export interface SnapshotView {
  run_id: string
  schema_version: string
  created_at: string | null
  use_case?: string | null
  account?: Record<string, unknown> | null
  plan?: Record<string, unknown> | null
  values?: Record<string, unknown>
  [field: string]: unknown
}

export interface RunRerunResponse {
  run_id: string
  snapshot_id: string
  rerun_of_run_id: string
  old_run_stop_requested: boolean
  old_run_stop_confirmed: boolean
  [field: string]: unknown
}

export interface BusinessEvent {
  id: string
  cursor: number
  research_id: string
  request_id: string | null
  run_id: string | null
  kind: string
  title: string
  summary: string
  detail: Record<string, unknown>
  read: boolean
  read_at: string | null
  created_at: string | null
}

export interface BusinessEventListResponse {
  items: BusinessEvent[]
  cursor: number
  cursor_expired: boolean
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
 * One durable control action of a run (F21, ``GET /api/runs/{id}/controls``).
 *
 * A mid-run direction (``kind: 'steer'``) or a tool-call approval
 * (``kind: 'approval'``) with the state it reached. This is what a refreshed or
 * reconnected page reads to rebuild state that used to exist only in a live SSE
 * frame — most importantly a still-``pending`` approval.
 */
export interface RunControlRecord {
  control_id: string
  /**
   * Worker-side id (the SSE frame's ``approval_id``). A decision must echo THIS
   * id — the worker's gate matches on it, not on the row id.
   */
  external_id?: string | null
  run_id: string
  kind: 'steer' | 'approval'
  /** steer: queued | adopted | dropped | undelivered; approval: pending | adopted | rejected | expired | abandoned. */
  status: string
  /** Already redacted server-side: the same projection the SSE egress uses. */
  request: Record<string, unknown>
  decision?: string | null
  replacement_command?: string | null
  adopted_turn_seq?: number | null
  detail?: Record<string, unknown>
  created_at?: string | null
  resolved_at?: string | null
}

export interface RunControlsResponse {
  run_id: string
  controls: RunControlRecord[]
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
  // steer_queued (P3.1, §7): ``message`` is the redacted steer text.
  // ``steer_seq`` is the per-run steer order — deliberately NOT ``seq``: that
  // field is the trajectory line number / reconnect cursor, and overloading it
  // made a steer jump the cursor past unread lines (F09).
  steer_seq?: number
  message?: string
  // Control records (F21): ``control_id`` names the durable record of a steer or
  // approval, ``turn_index`` is the transcript position an adopted steer landed
  // at. Both are additive — older frames simply omit them.
  control_id?: string
  turn_index?: number
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
  /**
   * Readable chain-of-thought, when the model returned one and the observer
   * recorded it (F05). Absent means "not recorded", which the UI must say
   * instead of rendering nothing and calling it a complete answer.
   */
  thinking?: string | null
  /**
   * Verbatim native reasoning blocks (signatures / ``encrypted_content``) kept
   * for protocol replay. Deliberately NOT prose — the UI must not render it as
   * human-readable reasoning.
   */
  thinking_blocks?: unknown
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

/**
 * F06: how much of a run's trace survived.
 *
 * ``partial`` means records exist but the run never wrote its terminal marker —
 * everything on disk is readable, the tail is not guaranteed to be the whole
 * story. The UI must surface this instead of presenting an interrupted run as a
 * complete one.
 */
export interface TraceCompleteness {
  state: 'complete' | 'partial' | 'unavailable'
  valid_lines: number
  trailing_partial_line: boolean
  corrupt_lines: number
  reason: string
}

export interface RunTraceResponse {
  run_id: string
  records: RunTraceRecord[]
  /** Absent only on pre-F06 servers; treat as unknown, not as complete. */
  completeness?: TraceCompleteness
}
