/**
 * Super-link space event stream (SSE-T04).
 *
 * One connection, no internal retry: the sync state machine owns backoff,
 * resynchronisation and max-age reconnects because those decisions depend on
 * the snapshot cursor and the current space. This module only speaks the wire
 * protocol and reports exactly one close per connection.
 *
 * Not built on ``openRunStream``: a run stream ends on terminal frames and
 * advances a numeric trajectory cursor. A space stream never ends on business
 * events, carries an ``sl1`` cursor, and uses control frames to ask the client
 * to re-authenticate or rebuild state. Only the byte framing is shared.
 */

// Explicit .ts keeps the module importable by the `node --experimental-strip-types`
// test runner as well as by Vite (see tsconfig `exclude` note).
import { extractFrames, parseFrame } from '../utils/sseFrames.ts'

export const SPACE_CONTROL_EVENTS = [
  'sl.auth_required',
  'sl.resync_required',
  'sl.unavailable',
] as const
export type SpaceControlEvent = (typeof SPACE_CONTROL_EVENTS)[number]

export const SPACE_PREVIEW_EVENT = 'sl.run.preview'
export const SPACE_OUTPUT_RESET_EVENT = 'sl.output_reset'

/** Display-only run preview; never advances the durable space cursor. */
export interface SpacePreview {
  schema_version?: number
  space_id?: string
  run_id?: string
  session_id?: string
  output_epoch?: string
  output_seq?: number
  kind?: string
  member?: { agent_id?: string; agent_kind?: string }
  turn?: number | null
  block_key?: string
  text?: string
  tool?: {
    call_id?: string
    name?: string
    state?: string
    ok?: boolean
    skipped?: boolean
    detail?: string
    ms?: number | null
  }
  status?: string
  stopped_by?: string
  error?: string
  [key: string]: unknown
}

export interface SpaceOutputReset {
  schema_version?: number
  space_id?: string
  run_ids?: string[]
  reason?: string
}

/** Minimal envelope; the sync state machine re-validates every field. */
export interface SpaceFact {
  schema_version?: number
  type?: string
  space_id?: string
  stream_epoch?: string
  seq?: string
  cursor?: string
  invalidate?: string[]
  [key: string]: unknown
}

export interface StreamCloseInfo {
  reason: 'eof' | 'error' | 'http' | 'aborted'
  status?: number
  retryAfterMs?: number
  cause?: unknown
}

export interface SpaceStreamCallbacks {
  onFact: (fact: SpaceFact) => void
  onControl: (event: SpaceControlEvent, reason: string) => void
  /** Live run output; high frequency and explicitly lossy. */
  onPreview?: (preview: SpacePreview) => void
  /** Preview fragments were dropped; the listed runs need an archive reload. */
  onOutputReset?: (reset: SpaceOutputReset) => void
  /** Called once the 2xx body is ready; used to reset retry attempts. */
  onOpen?: () => void
  /** Called exactly once unless ``stop()`` aborted the connection. */
  onClose?: (info: StreamCloseInfo) => void
}

export interface SpaceStreamOptions {
  url: string
  token: string | (() => string | null)
  /** Snapshot cursor; always sent as ``?after=``. */
  after: string
  signal?: AbortSignal
  fetchImpl?: typeof fetch
  callbacks: SpaceStreamCallbacks
}

export interface SpaceStreamHandle {
  stop: () => void
}

const CONTROL_SET: ReadonlySet<string> = new Set(SPACE_CONTROL_EVENTS)

function resolveToken(token: SpaceStreamOptions['token']): string | null {
  return typeof token === 'function' ? token() : token
}

function retryAfterMs(response: Response): number | undefined {
  const raw = response.headers.get('Retry-After')
  if (!raw) return undefined
  const seconds = Number.parseInt(raw, 10)
  return Number.isFinite(seconds) && seconds >= 0 ? seconds * 1000 : undefined
}

function controlReason(data: string): string {
  try {
    const parsed: unknown = JSON.parse(data)
    if (parsed && typeof parsed === 'object') {
      const reason = (parsed as { reason?: unknown }).reason
      if (typeof reason === 'string' && reason) return reason
    }
  } catch {
    /* A malformed control body still means "handle this control event". */
  }
  return ''
}

/** Open one space event connection. Call ``stop()`` to release it. */
export function openSpaceStream(options: SpaceStreamOptions): SpaceStreamHandle {
  const { url, token, after, callbacks, fetchImpl = fetch } = options
  const controller = new AbortController()
  const externalSignal = options.signal
  const onExternalAbort = () => controller.abort()
  if (externalSignal) {
    if (externalSignal.aborted) controller.abort()
    else externalSignal.addEventListener('abort', onExternalAbort, { once: true })
  }

  let stopped = false
  let closed = false
  let reader: ReadableStreamDefaultReader<Uint8Array> | null = null

  const cleanup = () => {
    if (externalSignal) externalSignal.removeEventListener('abort', onExternalAbort)
  }

  const close = (info: StreamCloseInfo) => {
    if (stopped || closed) return
    closed = true
    cleanup()
    callbacks.onClose?.(info)
  }

  const run = async () => {
    const bearer = resolveToken(token)
    if (!bearer) {
      close({ reason: 'http', status: 401 })
      return
    }

    const target = `${url}${url.includes('?') ? '&' : '?'}after=${encodeURIComponent(after)}`
    let response: Response
    try {
      response = await fetchImpl(target, {
        method: 'GET',
        headers: {
          Accept: 'text/event-stream',
          Authorization: `Bearer ${bearer}`,
          'Cache-Control': 'no-cache',
        },
        signal: controller.signal,
        // `Last-Event-ID` is deliberately not set: the durable cursor lives in
        // the query string, and a second implicit cursor would be ambiguous.
        keepalive: false,
      })
    } catch (err) {
      if (controller.signal.aborted) return
      close({ reason: 'error', cause: err })
      return
    }

    if (controller.signal.aborted) return

    if (!response.ok) {
      const hint = retryAfterMs(response)
      try {
        await response.body?.cancel()
      } catch {
        /* best-effort */
      }
      close({ reason: 'http', status: response.status, retryAfterMs: hint })
      return
    }

    if (!response.body) {
      close({ reason: 'error', cause: new Error('响应不支持流式读取') })
      return
    }

    callbacks.onOpen?.()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    reader = response.body.getReader()

    try {
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        if (controller.signal.aborted) return
        if (!value || value.length === 0) continue

        buffer += decoder.decode(value, { stream: true })
        const { frames, rest } = extractFrames(buffer)
        buffer = rest

        for (const frame of frames) {
          const parsed = parseFrame(frame)
          if (!parsed || !parsed.event) continue
          if (parsed.event === 'sl.fact') {
            let payload: unknown
            try {
              payload = JSON.parse(parsed.data)
            } catch {
              continue
            }
            if (payload && typeof payload === 'object') {
              callbacks.onFact(payload as SpaceFact)
            }
            continue
          }
          if (
            parsed.event === SPACE_PREVIEW_EVENT ||
            parsed.event === SPACE_OUTPUT_RESET_EVENT
          ) {
            let payload: unknown
            try {
              payload = JSON.parse(parsed.data)
            } catch {
              continue
            }
            if (!payload || typeof payload !== 'object') continue
            if (parsed.event === SPACE_PREVIEW_EVENT) {
              callbacks.onPreview?.(payload as SpacePreview)
            } else {
              callbacks.onOutputReset?.(payload as SpaceOutputReset)
            }
            continue
          }
          if (CONTROL_SET.has(parsed.event)) {
            callbacks.onControl(
              parsed.event as SpaceControlEvent,
              controlReason(parsed.data),
            )
          }
          // Unknown event names are ignored; the connection stays usable.
        }
      }
      close({ reason: 'eof' })
    } catch (err) {
      if (controller.signal.aborted) return
      close({ reason: 'error', cause: err })
    } finally {
      try {
        reader?.releaseLock()
      } catch {
        /* already released */
      }
      reader = null
      try {
        await response.body.cancel().catch(() => undefined)
      } catch {
        /* best-effort */
      }
    }
  }

  void run()

  return {
    stop: () => {
      if (stopped) return
      stopped = true
      cleanup()
      try {
        reader?.cancel().catch(() => undefined)
      } catch {
        /* best-effort */
      }
      controller.abort()
    },
  }
}
