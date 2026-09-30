/**
 * Presentation logic for the historical trajectory timeline (F05).
 *
 * Kept out of the Vue component so it can be exercised without a browser: the
 * audit runs these functions directly against synthetic records.
 *
 * Two promises this file exists to keep:
 *
 * 1. **Never invent reasoning.** A turn with no recorded thinking must say so.
 *    A turn whose only reasoning is an encrypted/signed native block must say it
 *    is restricted — rendering `thinking_blocks` as if it were prose would be
 *    showing a signature blob and calling it an explanation.
 * 2. **Never hide the tail silently.** Tool results used to be sliced at 300
 *    chars with no indicator, so an error message that started at char 301 was
 *    simply gone. Truncation is now explicit and resumable.
 *
 * Redaction is deliberately NOT here: masking is the egress boundary (F03) and
 * belongs to the caller, so a test of this file never has to fake it.
 */

/** First slice shown for a tool result — enough context, cheap to render. */
export const RESULT_PREVIEW_CHARS = 300

/** How much each "read more" press adds. Bounded so a huge result can't freeze
 * the page (F13 has the server-side counterpart). */
export const RESULT_PAGE_CHARS = 2000

/**
 * How a turn's reasoning should be presented.
 *
 * - ``visible``    a readable reasoning text exists
 * - ``absent``     nothing was recorded for this turn
 * - ``empty``      recorded, but blank
 * - ``restricted`` only non-prose reasoning exists (encrypted/signed native
 *                  blocks, or a non-text structure) — must not be rendered as
 *                  human-readable thought
 */
export type ThinkingView =
  | { state: 'visible'; text: string }
  | { state: 'absent' }
  | { state: 'empty' }
  | { state: 'restricted'; reason: string }

/** True when a value is a non-blank string. */
function isFilledString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0
}

/** True when a value carries at least one entry (array) or key (object). */
function hasContent(value: unknown): boolean {
  if (Array.isArray(value)) return value.length > 0
  if (value !== null && typeof value === 'object') return Object.keys(value).length > 0
  return false
}

/**
 * Classify one ``llm`` record's reasoning.
 *
 * ``thinking`` is the readable chain-of-thought the trajectory observer writes
 * when the model returns one. ``thinking_blocks`` is the verbatim native block
 * list (signatures / ``encrypted_content``) kept for replay — it is explicitly
 * not prose, so a turn carrying only that is reported as restricted rather than
 * shown as if it were an explanation.
 */
export function thinkingView(record: {
  thinking?: unknown
  thinking_blocks?: unknown
}): ThinkingView {
  const thinking = record.thinking

  if (isFilledString(thinking)) return { state: 'visible', text: thinking }
  if (thinking === '') return { state: 'empty' }
  if (thinking !== undefined && thinking !== null && !isFilledString(thinking)) {
    // Present but not prose (e.g. a structured block) — show it raw would be
    // misleading, and the UI has no safe rendering for it.
    return { state: 'restricted', reason: '推理内容为非文本结构，无法作为可读文本展示' }
  }

  if (hasContent(record.thinking_blocks)) {
    return {
      state: 'restricted',
      reason: '该轮仅有加密/签名推理块（用于协议回放），不可作为可读推理展示',
    }
  }
  return { state: 'absent' }
}

/** Chinese label for a non-visible thinking state, shown in place of the text. */
export function thinkingLabel(view: ThinkingView): string {
  switch (view.state) {
    case 'visible':
      return ''
    case 'absent':
      return '该轮未记录可见推理'
    case 'empty':
      return '该轮记录了空的推理'
    case 'restricted':
      return view.reason
  }
}

/** A tool result's text plus how much of it is still unread. */
export interface ResultView {
  /** The slice that should be rendered now. */
  visible: string
  /** Characters still hidden; 0 when everything is shown. */
  hidden: number
  /** True when a "read more" control should be offered. */
  hasMore: boolean
  /** Total length of the full text. */
  total: number
}

/**
 * Slice a tool result for display.
 *
 * ``shown`` is how many characters the user has unlocked (start at
 * {@link RESULT_PREVIEW_CHARS}). The slice is on code points, not UTF-16 units,
 * so a multi-byte character is never cut in half.
 */
export function resultView(text: string, shown: number): ResultView {
  const chars = Array.from(text)
  const limit = Math.max(0, Math.floor(shown))
  const visible = chars.slice(0, limit).join('')
  const hidden = Math.max(0, chars.length - limit)
  return { visible, hidden, hasMore: hidden > 0, total: chars.length }
}

/** Default number of characters a result shows before "read more". */
export function initialResultChars(): number {
  return RESULT_PREVIEW_CHARS
}

/** How many characters the next "read more" press should reveal. */
export function nextResultChars(shown: number): number {
  return Math.max(shown, RESULT_PREVIEW_CHARS) + RESULT_PAGE_CHARS
}
