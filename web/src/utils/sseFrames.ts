/**
 * Wire-level SSE helpers shared by the run stream (``src/sse.ts``) and the
 * Super-link space stream (``src/superLink/stream.ts``).
 *
 * The two streams differ in cursor and termination semantics, but the byte
 * framing is identical: frames end at a blank line, ``data:`` may repeat, and
 * comments such as ``: heartbeat`` carry no payload. Keeping this here means a
 * fix to half-frame buffering or field parsing applies to both, without forcing
 * the run stream to adopt the space stream's cursor model.
 */

export interface ParsedFrame {
  /** Joined ``data:`` lines. Empty when the frame carried none. */
  data: string
  /** ``event:`` name, or ``null`` for the default message event. */
  event: string | null
  /** ``id:`` value, or ``null``. The run stream deliberately ignores it. */
  id: string | null
  /** ``retry:`` hint in milliseconds, when present and valid. */
  retry?: number
}

/**
 * Split a decoded chunk into complete SSE frames.
 *
 * Frames end at a blank line. The trailing partial (if any) is returned so the
 * caller can prepend it to the next chunk — a delta can easily straddle a
 * network packet.
 */
export function extractFrames(buffer: string): { frames: string[]; rest: string } {
  const frames: string[] = []
  let rest = buffer
  for (;;) {
    const idx = rest.indexOf('\n\n')
    if (idx === -1) break
    frames.push(rest.slice(0, idx))
    rest = rest.slice(idx + 2)
  }
  return { frames, rest }
}

/**
 * Parse one SSE frame into its fields, or ``null`` if it carries no payload.
 *
 * Handles multi-line ``data:``, comment/keepalive lines (``: ping``), and the
 * ``event`` / ``id`` / ``retry`` fields that must not be mistaken for payload.
 * A frame with no ``data:`` line is a comment or a heartbeat and returns null;
 * both consumers treat those as "stay connected, advance nothing".
 */
export function parseFrame(frame: string): ParsedFrame | null {
  const dataLines: string[] = []
  let event: string | null = null
  let id: string | null = null
  let retry: number | undefined
  for (const rawLine of frame.split(/\r?\n/)) {
    if (!rawLine) continue
    const colon = rawLine.indexOf(':')
    // A line with no colon is a field name with an empty value (spec allows it).
    const field = colon === -1 ? rawLine : rawLine.slice(0, colon)
    let value = colon === -1 ? '' : rawLine.slice(colon + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    switch (field) {
      case 'data':
        dataLines.push(value)
        break
      case 'event':
        event = value
        break
      case 'id':
        id = value
        break
      case 'retry': {
        const parsed = Number.parseInt(value, 10)
        if (Number.isFinite(parsed) && parsed >= 0) retry = parsed
        break
      }
      default:
        // Unknown field or a comment line (": keepalive") — ignore.
        break
    }
  }
  if (dataLines.length === 0) return null
  return { data: dataLines.join('\n'), event, id, retry }
}

/** Exponential backoff with full jitter, so parallel tabs don't sync up. */
export function backoffDelay(attempt: number, base: number, max: number): number {
  const ceiling = Math.min(max, base * 2 ** attempt)
  return Math.random() * ceiling
}

/** Abortable sleep used between reconnect attempts. */
export function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException('Aborted', 'AbortError'))
      return
    }
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', onAbort)
      resolve()
    }, ms)
    function onAbort() {
      clearTimeout(timer)
      reject(new DOMException('Aborted', 'AbortError'))
    }
    signal.addEventListener('abort', onAbort, { once: true })
  })
}
