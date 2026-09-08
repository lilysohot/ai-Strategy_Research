/**
 * Typed REST client for the投研 Agent platform (T3.1).
 *
 * Responsibilities kept here, and nowhere else:
 *
 *   - prefix every path with ``/api`` so views never hardcode the origin
 *     (the dev server proxies it; Caddy reverse-proxies it in production);
 *   - attach the bearer token, read through a provider so a token refreshed
 *     mid-session is picked up without re-importing anything;
 *   - turn a non-2xx into a single {@link ApiError} shape, because FastAPI
 *     reports ``detail`` as either a string or (for 422) a list of field errors,
 *     and every view would otherwise re-implement that unwrapping;
 *   - route 401 to one handler so "log out and go to /login" lives in one place.
 *
 * The api_key is never part of any request body or response type here — LLM
 * credentials are entered once and stored encrypted server-side (FR-2.2).
 */

const API_PREFIX = '/api'

export class ApiError extends Error {
  readonly status: number
  /** Raw ``detail`` as returned by FastAPI (string or validation-error list). */
  readonly detail: unknown

  constructor(status: number, message: string, detail: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }

  /** True for the credential failures that must send the user to /login. */
  get isUnauthorized(): boolean {
    return this.status === 401 || this.status === 403
  }
}

let tokenProvider: () => string | null = () => null
let unauthorizedHandler: (() => void) | null = null

/** Register where the bearer token comes from (wired once in the auth store). */
export function setTokenProvider(provider: () => string | null): void {
  tokenProvider = provider
}

/** Register what to do on a 401/403 (wired once by the router guard). */
export function setUnauthorizedHandler(handler: () => void): void {
  unauthorizedHandler = handler
}

/**
 * Render FastAPI's ``detail`` into one display string.
 *
 * 422 bodies are ``[{loc: [...], msg, type}]``; joining every field error is
 * what makes a form usable, and falling back to a generic message keeps a
 * surprising body from rendering as ``[object Object]``.
 */
function messageFromDetail(status: number, detail: unknown): string {
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (item && typeof item === 'object' && 'msg' in item) {
          const loc = (item as { loc?: unknown[] }).loc
          const field = Array.isArray(loc) ? loc.filter((p) => p !== 'body').join('.') : ''
          return field ? `${field}: ${String((item as { msg: unknown }).msg)}` : String((item as { msg: unknown }).msg)
        }
        return String(item)
      })
      .filter(Boolean)
    if (parts.length) return parts.join('；')
  }
  if (detail && typeof detail === 'object') {
    const maybeMsg = (detail as { message?: unknown; msg?: unknown }).message
      ?? (detail as { message?: unknown; msg?: unknown }).msg
    if (typeof maybeMsg === 'string') return maybeMsg
  }
  switch (status) {
    case 401:
      return '登录状态已失效，请重新登录'
    case 403:
      return '没有权限执行该操作'
    case 404:
      return '资源不存在或无权访问'
    case 409:
      return '操作冲突，请重试'
    case 413:
      return '上传内容过大'
    case 423:
      return '操作被暂时锁定，请稍后重试'
    case 0:
      return '网络异常，请检查连接'
    default:
      return `请求失败（HTTP ${status}）`
  }
}

/**
 * Fetch a binary body (artifact download) with the same auth and error
 * normalisation as {@link request}.
 *
 * A plain ``<a download>`` cannot carry an Authorization header, so this exists
 * for the authenticated path: the caller turns the Blob into an object URL and
 * triggers the save itself.
 */
export async function requestBlob(
  path: string,
  query?: RequestOptions['query'],
  signal?: AbortSignal,
): Promise<Blob> {
  const headers: Record<string, string> = {}
  const token = tokenProvider()
  if (token) headers.Authorization = `Bearer ${token}`

  let response: Response
  try {
    response = await fetch(buildUrl(path, query), { headers, signal })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    throw new ApiError(0, '网络异常，请检查连接', null)
  }

  if (response.status === 401 || response.status === 403) {
    if (unauthorizedHandler) unauthorizedHandler()
  }
  if (!response.ok) {
    throw new ApiError(
      response.status,
      messageFromDetail(response.status, null),
      null,
    )
  }
  return response.blob()
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  body?: unknown
  /** Query string values; ``undefined``/``null`` entries are dropped. */
  query?: Record<string, string | number | undefined | null>
  signal?: AbortSignal
  /** Skip the Authorization header (login/register only). */
  anonymous?: boolean
  /** Expected for 204 No Content endpoints. */
  parseJson?: boolean
}

function buildUrl(path: string, query?: RequestOptions['query']): string {
  const url = `${API_PREFIX}${path}`
  if (!query) return url
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue
    params.set(key, String(value))
  }
  const qs = params.toString()
  return qs ? `${url}?${qs}` : url
}

/**
 * One request. Rejects with {@link ApiError} for any non-2xx.
 *
 * A network failure (server down, DNS, CORS) has no status, so it is reported as
 * status 0 — callers branch on {@link ApiError.status} rather than on the error
 * class, which keeps the "show a message" path uniform.
 */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const {
    method = 'GET',
    body,
    query,
    signal,
    anonymous = false,
    parseJson = true,
  } = options

  const headers: Record<string, string> = {}
  const isFormData = typeof FormData !== 'undefined' && body instanceof FormData
  // FormData must keep its browser-generated boundary, so Content-Type is
  // deliberately not set in that case.
  if (body !== undefined && !isFormData) headers['Content-Type'] = 'application/json'
  if (!anonymous) {
    const token = tokenProvider()
    if (token) headers.Authorization = `Bearer ${token}`
  }

  let response: Response
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      headers,
      signal,
      body: body === undefined
        ? undefined
        : isFormData
          ? (body as FormData)
          : JSON.stringify(body),
    })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    throw new ApiError(0, '网络异常，请检查连接', null)
  }

  if (response.status === 401 || response.status === 403) {
    // Let the app drop the stale token and bounce to /login exactly once per
    // failure, instead of every view re-deciding what "unauthorized" means.
    if (unauthorizedHandler) unauthorizedHandler()
  }

  if (!response.ok) {
    let detail: unknown = null
    try {
      const text = await response.text()
      if (text) {
        try {
          detail = (JSON.parse(text) as { detail?: unknown }).detail ?? text
        } catch {
          detail = text
        }
      }
    } catch {
      detail = null
    }
    throw new ApiError(
      response.status,
      messageFromDetail(response.status, detail),
      detail,
    )
  }

  if (!parseJson || response.status === 204) return undefined as T
  const text = await response.text()
  if (!text.trim()) return undefined as T
  try {
    return JSON.parse(text) as T
  } catch {
    throw new ApiError(response.status, '服务端返回了非 JSON 响应', text)
  }
}
