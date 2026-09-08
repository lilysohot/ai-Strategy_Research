/**
 * Status-bar helpers (cli-web-parity §5.6).
 *
 * Pure, dependency-free (no vue/pinia imports) so they run on the bare node
 * test runner — same constraint as ``activity.ts``.
 *
 * The bar renders 阶段 · 耗时 · workflow · model · context · tools. Run-level
 * facts arrive piecemeal: the live ``run_started`` carries pipeline/model
 * (stamped by the worker) + the context window (from LoopConfig), while the
 * replayed copy carries ``tool_names`` from the trajectory's start record.
 * ``mergeRunMeta`` folds both into one object without clobbering.
 */

/** Run-level facts shown in the status bar. */
export interface RunMeta {
  pipelineId?: string
  modelName?: string
  toolNames?: string[]
  maxTurns?: number
  /** Context window in tokens (LoopConfig.context_token_limit). */
  contextLimit?: number
}

/** The raw fields any ``run_started`` event may carry. */
export interface RunStartFields {
  pipeline_id?: unknown
  model_name?: unknown
  tool_names?: unknown
  max_turns?: unknown
  context_limit?: unknown
}

/**
 * Fold one ``run_started`` event's metadata into ``prev``, returning a new
 * object. Live and replay both emit the event type, so this must be
 * order-tolerant: later fields fill gaps, never overwrite known ones.
 */
export function mergeRunMeta(prev: RunMeta, event: RunStartFields): RunMeta {
  const next: RunMeta = { ...prev }
  if (typeof event.pipeline_id === 'string' && event.pipeline_id) {
    next.pipelineId = event.pipeline_id
  }
  if (typeof event.model_name === 'string' && event.model_name) {
    next.modelName = event.model_name
  }
  if (Array.isArray(event.tool_names)) {
    const names = event.tool_names.filter((n): n is string => typeof n === 'string')
    if (names.length) next.toolNames = names
  }
  if (typeof event.max_turns === 'number' && event.max_turns > 0) {
    next.maxTurns = event.max_turns
  }
  if (typeof event.context_limit === 'number' && event.context_limit > 0) {
    next.contextLimit = event.context_limit
  }
  return next
}

/**
 * Running token totals, accumulated per turn.
 *
 * Mirrors server ``aggregate_usage`` (T2.11): the cache split is kept because
 * reads bill at ~0.1x (or free) while writes bill at 1.25x-2x — folding them
 * into one bucket is exactly the under-attribution the server module warns about.
 */
export interface UsageTotals {
  prompt: number
  completion: number
  total: number
  /** Cache-hit tokens (``cache_read_tokens`` / legacy ``cached_tokens``). */
  cacheRead: number
  /** Cache-creation tokens (``cache_write_tokens`` / legacy ``cache_creation_tokens``). */
  cacheWrite: number
}

/**
 * The usage block riding on a replayed ``assistant_delta`` event — the same
 * normalised dict the runtime persists per LLM turn, so provider aliases
 * (``input_tokens`` etc.) may appear instead of the canonical names.
 */
export interface UsageFields {
  prompt_tokens?: unknown
  completion_tokens?: unknown
  total_tokens?: unknown
  input_tokens?: unknown
  output_tokens?: unknown
  cache_read_tokens?: unknown
  cached_tokens?: unknown
  cache_write_tokens?: unknown
  cache_creation_tokens?: unknown
}

/**
 * Add one turn's usage deltas, applying the server's T2.11 semantics so the
 * bar and the platform metering never disagree: alias fallback (prompt→input,
 * completion→output, new cache names before legacy ones) and a missing/zero
 * ``total_tokens`` derived from its parts.
 */
export function accumulateUsage(prev: UsageTotals, usage?: UsageFields | null): UsageTotals {
  if (!usage || typeof usage !== 'object') return prev
  const num = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) ? v : 0)
  const first = (...values: unknown[]): number => {
    for (const v of values) {
      if (v !== null && v !== undefined) return num(v)
    }
    return 0
  }
  const prompt = first(usage.prompt_tokens, usage.input_tokens)
  const completion = first(usage.completion_tokens, usage.output_tokens)
  const reported = num(usage.total_tokens)
  return {
    prompt: prev.prompt + prompt,
    completion: prev.completion + completion,
    total: prev.total + (reported > 0 ? reported : prompt + completion),
    cacheRead: prev.cacheRead + first(usage.cache_read_tokens, usage.cached_tokens),
    cacheWrite: prev.cacheWrite + first(usage.cache_write_tokens, usage.cache_creation_tokens),
  }
}

/**
 * Terminal-style elapsed clock for the status bar: ``42s`` / ``1m05s`` / ``1h02m``.
 */
export function formatElapsed(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return '0s'
  const totalSec = Math.floor(ms / 1000)
  const h = Math.floor(totalSec / 3600)
  const m = Math.floor((totalSec % 3600) / 60)
  const s = totalSec % 60
  if (h > 0) return `${h}h${String(m).padStart(2, '0')}m`
  if (m > 0) return `${m}m${String(s).padStart(2, '0')}s`
  return `${s}s`
}
