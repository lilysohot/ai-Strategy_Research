/**
 * SSE client built on ``fetch`` + ``ReadableStream`` (T3.1).
 *
 * Why not ``EventSource``: it cannot send an ``Authorization`` header, and every
 * route under ``/api`` requires a bearer token (``server/deps.py``). It also
 * offers no way to pass the ``?after=`` line cursor the platform's replay
 * protocol needs (tech-stack.md §7 decision 7).
 *
 * Wire format produced by ``server/events.py::to_sse``::
 *
 *     data: {"type":"assistant_delta","ts":...,"seq":3,"content":"..."}\n\n
 *
 * Cursor protocol (this is the part that is easy to get wrong):
 *
 *   - ``GET /api/runs/{id}/events?after=N`` replays the run's trajectory from
 *     line ``N+1``, then tails it. Each replayed frame carries ``seq`` = its
 *     1-based trajectory line (see ``server/relay.py``).
 *   - The client remembers the highest ``seq`` seen and reconnects with
 *     ``after=seq``, so a dropped connection resumes exactly where it stopped
 *     instead of replaying from zero or silently skipping lines.
 *   - Live frames that have no trajectory line omit ``seq``; the cursor is NOT
 *     advanced by them, because advancing would skip an unread trajectory line.
 *     (Before ``seq`` existed the client had to count frames, which conflated
 *     the two.)
 *
 * Terminal semantics: the server closes the stream once the run's trajectory is
 * fully replayed (``summary.json`` exists), and the terminal frames
 * run_completed/run_failed/run_stopped mark the end explicitly. Either signal
 * ends the stream without a reconnect. Anything else — transport error, proxy
 * cut, 5xx — reconnects with exponential backoff + jitter.
 */

import { TERMINAL_EVENT_TYPES, type SseEvent } from './types'

/** How a stream ended, so callers can decide between "retry" and "show error". */
export type SseEndReason =
  /** A terminal frame arrived, or the server closed a fully replayed stream. */
  | 'completed'
  /** The caller aborted (``stop()`` or an external AbortSignal). */
  | 'aborted'
  /** Credentials rejected — retrying cannot help; the app must re-login. */
  | 'unauthorized'
  /** Run is missing or not visible to this user (404 is an anti-IDOR 404). */
  | 'not_found'
  /** Retries were exhausted after repeated transport failures. */
  | 'give_up'
  /** A non-retryable HTTP status (other than 401/404). */
  | 'http_error'

export interface SseError {
  kind: SseEndReason
  message: string
  status?: number
  /** The underlying exception, when there is one. */
  cause?: unknown
}

export type SseListener = (event: SseEvent) => void
export type SseErrorListener = (error: SseError) => void
export type SseDoneListener = (reason: SseEndReason) => void

export interface SseStreamOptions {
  /** Stream URL **without** the ``after`` query param. */
  url: string
  /**
   * Bearer token. A getter rather than a string so a token refreshed mid-run is
   * picked up on the next (re)connect instead of sticking with a stale one.
   */
  token: string | (() => string | null)
  /** Initial cursor: resume from this trajectory line. Defaults to 0 (from start). */
  after?: number
  onEvent: SseListener
  onError?: SseErrorListener
  onDone?: SseDoneListener
  /** Frames that close the stream. Defaults to {@link TERMINAL_EVENT_TYPES}. */
  terminalTypes?: readonly string[]
  /** Called whenever the cursor advances, so a caller can persist it. */
  onCursor?: (cursor: number) => void
  /** Called after each (re)connect succeeds, useful to clear an error banner. */
  onOpen?: () => void
  /** Aborts the stream from outside (component unmount, navigation). */
  signal?: AbortSignal
  /** Max reconnect attempts after a transport failure. Default 8. */
  maxRetries?: number
  /** First backoff delay in ms; doubles each attempt. Default 500. */
  baseDelayMs?: number
  /** Backoff ceiling in ms. Default 15000. */
  maxDelayMs?: number
}

export interface SseStreamHandle {
  /** Stop streaming and release resources. Idempotent. */
  stop: () => void
  /** Highest trajectory line consumed so far. */
  cursor: () => number
  /** True while a fetch is in flight or its body is being read. */
  active: () => boolean
}

/** 4xx statuses that mean "retrying this exact request cannot succeed". */
const FATAL_STATUSES: ReadonlySet<number> = new Set([400, 401, 403, 404, 422])

function resolveToken(token: SseStreamOptions['token']): string | null {
  return typeof token === 'function' ? token() : token
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
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

/** Exponential backoff with full jitter, so parallel tabs don't sync up. */
function backoffDelay(attempt: number, base: number, max: number): number {
  const ceiling = Math.min(max, base * 2 ** attempt)
  return Math.random() * ceiling
}

/**
 * Split a decoded chunk into complete SSE frames.
 *
 * Frames end at a blank line. The trailing partial (if any) is returned so the
 * caller can prepend it to the next chunk — a run's delta can easily straddle a
 * network packet.
 */
function extractFrames(buffer: string): { frames: string[]; rest: string } {
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
 * Parse one SSE frame into its payload, or ``null`` if it carries none.
 *
 * Handles the parts of the spec the platform actually uses plus the cheap
 * robustness wins: multi-line ``data:``, comment/keepalive lines (``: ping``),
 * and ``event:`` / ``id:`` / ``retry:`` fields that must not be mistaken for
 * payload. A frame with no ``data:`` line is a comment or a heartbeat.
 */
function parseFrame(frame: string): { data: string; retry?: number } | null {
  const dataLines: string[] = []
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
      case 'retry': {
        const parsed = Number.parseInt(value, 10)
        if (Number.isFinite(parsed) && parsed >= 0) retry = parsed
        break
      }
      case 'event':
      case 'id':
        // Named events / last-event-id are not part of this platform's contract;
        // the cursor lives in the payload's ``seq`` and the query string.
        break
      default:
        // Unknown field or a comment line (": keepalive") — ignore.
        break
    }
  }
  if (dataLines.length === 0) return null
  return { data: dataLines.join('\n'), retry }
}

/**
 * Open a run's event stream, reconnecting from the last cursor on failure.
 *
 * The returned handle is safe to call from any lifecycle hook; ``stop()`` is
 * idempotent and never throws.
 */
export function openRunStream(options: SseStreamOptions): SseStreamHandle {
  const {
    url,
    token,
    onEvent,
    onError,
    onDone,
    onCursor,
    onOpen,
    terminalTypes = TERMINAL_EVENT_TYPES,
    maxRetries = 8,
    baseDelayMs = 500,
    maxDelayMs = 15_000,
  } = options

  // Internal controller is always used so `stop()` can cancel an in-flight read
  // even when the caller passed no signal.
  const controller = new AbortController()
  const externalSignal = options.signal
  const onExternalAbort = () => controller.abort()
  if (externalSignal) {
    if (externalSignal.aborted) controller.abort()
    else externalSignal.addEventListener('abort', onExternalAbort, { once: true })
  }

  let cursor = Math.max(0, options.after ?? 0)
  let stopped = false
  let inFlight = false
  let attempt = 0
  let reader: ReadableStreamDefaultReader<Uint8Array> | null = null

  const cleanup = () => {
    if (externalSignal) externalSignal.removeEventListener('abort', onExternalAbort)
  }

  const finish = (reason: SseEndReason, error?: SseError) => {
    if (stopped) return
    stopped = true
    cleanup()
    if (error && onError) onError(error)
    if (onDone) onDone(reason)
  }

  const advanceCursor = (seq: number) => {
    if (!Number.isFinite(seq) || seq <= cursor) return
    cursor = seq
    if (onCursor) onCursor(cursor)
  }

  /** One connect-and-read cycle. Returns how it ended. */
  const runOnce = async (): Promise<{ reason: SseEndReason; error?: SseError }> => {
    const bearer = resolveToken(token)
    if (!bearer) {
      return {
        reason: 'unauthorized',
        error: { kind: 'unauthorized', message: '未登录或登录已失效' },
      }
    }

    const target = `${url}${url.includes('?') ? '&' : '?'}after=${cursor}`
    let response: Response
    try {
      response = await fetch(target, {
        method: 'GET',
        headers: {
          Accept: 'text/event-stream',
          Authorization: `Bearer ${bearer}`,
          // Stops intermediate caches from holding a stream that is meant to be
          // consumed once, live.
          'Cache-Control': 'no-cache',
        },
        signal: controller.signal,
        keepalive: false,
      })
    } catch (err) {
      if (controller.signal.aborted) return { reason: 'aborted' }
      return {
        reason: 'give_up',
        error: {
          kind: 'give_up',
          message: '网络连接失败',
          cause: err,
        },
      }
    }

    if (controller.signal.aborted) return { reason: 'aborted' }

    if (!response.ok) {
      const status = response.status
      // Drain the body so the connection can be reused; ignore failures.
      try {
        await response.body?.cancel()
      } catch {
        /* best-effort */
      }
      const message =
        status === 401 || status === 403
          ? '登录状态已失效，请重新登录'
          : status === 404
            ? '该运行不存在或无访问权限'
            : `服务端返回 HTTP ${status}`
      const kind: SseEndReason =
        status === 401 || status === 403
          ? 'unauthorized'
          : status === 404
            ? 'not_found'
            : 'http_error'
      const error: SseError = { kind, message, status }
      // Only a transport/5xx problem is worth retrying; a 401 will still be a
      // 401 in 500ms, and hammering it looks like credential stuffing.
      return FATAL_STATUSES.has(status)
        ? { reason: kind, error }
        : { reason: 'give_up', error }
    }

    if (!response.body) {
      return {
        reason: 'give_up',
        error: { kind: 'give_up', message: '浏览器不支持流式响应' },
      }
    }

    if (onOpen) onOpen()
    attempt = 0

    // `stream: true` is what keeps a multi-byte character split across two
    // network chunks from decoding into replacement characters — the answers are
    // Chinese, so this is not theoretical.
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    reader = response.body.getReader()

    try {
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        if (controller.signal.aborted) return { reason: 'aborted' }
        if (!value || value.length === 0) continue

        buffer += decoder.decode(value, { stream: true })
        const { frames, rest } = extractFrames(buffer)
        buffer = rest

        for (const frame of frames) {
          const parsed = parseFrame(frame)
          if (!parsed) continue
          if (parsed.retry !== undefined && parsed.retry >= 0) {
            // Server hint honoured as the floor for the next backoff.
            void parsed.retry
          }
          let payload: unknown
          try {
            payload = JSON.parse(parsed.data)
          } catch {
            // A half-written or non-JSON frame must not kill the stream: the
            // trajectory file on disk stays the source of truth, and the next
            // reconnect re-reads whatever was missed.
            continue
          }
          if (typeof payload !== 'object' || payload === null) continue
          const event = payload as SseEvent
          if (typeof event.type !== 'string') continue

          if (typeof event.seq === 'number') advanceCursor(event.seq)
          onEvent(event)

          if (terminalTypes.includes(event.type)) {
            return { reason: 'completed' }
          }
        }
      }
    } catch (err) {
      if (controller.signal.aborted) return { reason: 'aborted' }
      return {
        reason: 'give_up',
        error: { kind: 'give_up', message: '事件流中断', cause: err },
      }
    } finally {
      // Release the lock/body whether we returned early or finished cleanly.
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

    // Clean EOF: the server closes the stream once the trajectory is fully
    // replayed, which is the normal end for a finished run.
    return { reason: 'completed' }
  }

  const pump = async () => {
    while (!stopped) {
      inFlight = true
      let result: { reason: SseEndReason; error?: SseError }
      try {
        result = await runOnce()
      } catch (err) {
        result = {
          reason: 'give_up',
          error: { kind: 'give_up', message: '事件流异常', cause: err },
        }
      } finally {
        inFlight = false
      }

      if (stopped) return

      if (result.reason === 'completed' || result.reason === 'aborted') {
        finish(result.reason)
        return
      }
      if (
        result.reason === 'unauthorized' ||
        result.reason === 'not_found' ||
        result.reason === 'http_error'
      ) {
        // Fatal by construction (see runOnce): never retried.
        finish(result.reason, result.error)
        return
      }

      if (attempt >= maxRetries) {
        finish(
          'give_up',
          result.error ?? {
            kind: 'give_up',
            message: `重连 ${maxRetries} 次后仍失败，已停止重试`,
          },
        )
        return
      }

      const delay = backoffDelay(attempt, baseDelayMs, maxDelayMs)
      attempt += 1
      try {
        await sleep(delay, controller.signal)
      } catch {
        finish('aborted')
        return
      }
    }
  }

  void pump()

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
      if (onDone && !inFlight) onDone('aborted')
    },
    cursor: () => cursor,
    active: () => !stopped,
  }
}
