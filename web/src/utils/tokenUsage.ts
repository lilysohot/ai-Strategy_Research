import type { UsageFields } from './statusbar'

export interface TokenUsageFields extends UsageFields {
  reasoning_tokens?: unknown
  status?: string
  llm_calls?: number
}

/** Missing provider counters stay unknown; cache/reasoning are subsets, not extras. */
export function tokenBreakdown(usage?: TokenUsageFields | null) {
  const unavailable = !usage || usage.status === 'unavailable'
    || (usage.status === 'partial' && usage.llm_calls === 0)
  const count = (...values: unknown[]): number | null => {
    if (unavailable) return null
    for (const value of values) {
      if (typeof value === 'number' && Number.isSafeInteger(value) && value >= 0) return value
    }
    return null
  }
  const input = count(usage?.prompt_tokens, usage?.input_tokens)
  const output = count(usage?.completion_tokens, usage?.output_tokens)
  const read = count(usage?.cache_read_tokens, usage?.cached_tokens)
  const write = count(usage?.cache_write_tokens, usage?.cache_creation_tokens)
  const reasoning = count(usage?.reasoning_tokens)
  const reported = count(usage?.total_tokens)
  const total = reported !== null && reported > 0 ? reported
    : input !== null && output !== null ? input + output : null
  const miss = input !== null && read !== null && write !== null && read + write <= input
    ? input - read - write : null
  const reply = output !== null && reasoning !== null && reasoning <= output
    ? output - reasoning : null
  const hitRate = input && read !== null && read <= input ? read / input * 100 : null
  return { input, output, total, read, write, miss, reasoning, reply, hitRate }
}
