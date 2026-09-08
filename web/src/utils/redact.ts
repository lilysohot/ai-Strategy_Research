/**
 * Client-side secret redaction for LLM-produced text (T3.7 / requirements §6).
 *
 * Why this exists when the backend already has a sanitizer: the backend redacts
 * the *event stream*, but the text the UI renders also comes from the agent's
 * own output — tool arguments, tool results and assistant prose can all quote a
 * credential (a model asked to "show my config" will happily print the key it
 * was given, and a ``read_file`` of an env file returns one verbatim). The
 * platform's contract is "no plaintext key anywhere on screen", so the last
 * rendering hop has to enforce it too.
 *
 * This is defence in depth, not the primary control: the server never returns a
 * stored api_key (configs are masked at the API boundary), so what this catches
 * is a key being *echoed through model output* rather than read from storage.
 *
 * Patterns are deliberately broad-but-cheap: we mask the shape of a credential,
 * never try to validate whether it is a live one. A false positive costs a bit
 * of legibility; a false negative costs a leaked key.
 */

/** How much of a matched secret to keep, so the user can tell which one it was. */
const KEEP_PREFIX = 4

interface RedactionRule {
  name: string
  pattern: RegExp
  /**
   * Which capture group holds the secret (1-based). ``undefined`` means the
   * whole match is the secret.
   */
  group?: number
}

/**
 * Order matters: the most specific rules run first, so a Bearer header is
 * redacted as a header rather than as a bare token.
 *
 * Each pattern is written so the secret is isolated in its own group; the
 * surrounding context (the key name, the quotes) is preserved verbatim.
 */
const RULES: RedactionRule[] = [
  {
    name: 'bearer',
    pattern: /(Bearer\s+)([A-Za-z0-9._\-]{8,})/gi,
    group: 2,
  },
  {
    name: 'sk',
    pattern: /\b(sk-[A-Za-z0-9._\-]{8,})/g,
  },
  {
    name: 'vendor',
    pattern: /\b((?:ghp|gho|ghu|ghs|github_pat|xoxb|xoxp|AKIA|AIza|glpat)[_\-A-Za-z0-9]{8,})/g,
  },
  {
    name: 'assignment',
    pattern: /\b(api[_-]?key|apikey|secret|access[_-]?token|auth[_-]?token|password|passwd|pwd)(\s*[:=]\s*)(["']?)([^\s"',;}\]]{6,})\3/gi,
    group: 4,
  },
]

/**
 * Mask a single secret value, keeping a short prefix so the string stays
 * recognisable (the user can tell *which* key it was) but is not reusable.
 */
function maskValue(value: string): string {
  if (value.length <= KEEP_PREFIX) return '***'
  return `${value.slice(0, KEEP_PREFIX)}***`
}

/** Redact known credential shapes in arbitrary text. */
export function redactSecrets(text: string): string {
  if (!text) return text
  let out = text
  for (const rule of RULES) {
    if (rule.group === undefined) {
      // Whole match is the secret.
      out = out.replace(rule.pattern, (match) => maskValue(match))
      continue
    }
    const groupIndex = rule.group
    out = out.replace(rule.pattern, (match, ...rest: unknown[]) => {
      const groups = rest.slice(0, -2) as string[]
      const secret = groups[groupIndex - 1]
      if (typeof secret !== 'string' || !secret) return match
      // Rebuild: everything before the secret + masked secret + everything after.
      const at = match.lastIndexOf(secret)
      if (at === -1) return maskValue(secret)
      return match.slice(0, at) + maskValue(secret) + match.slice(at + secret.length)
    })
  }
  return out
}

/** Redact every string in a JSON-serialisable structure (tool args / results). */
export function redactDeep(value: unknown): unknown {
  if (typeof value === 'string') return redactSecrets(value)
  if (Array.isArray(value)) return value.map(redactDeep)
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      out[k] = redactDeep(v)
    }
    return out
  }
  return value
}
