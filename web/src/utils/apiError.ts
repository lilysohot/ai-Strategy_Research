/**
 * 非 2xx 响应体 → ``ApiError`` 的 ``detail`` 与展示文本。
 *
 * 服务端有两套错误信封，视图不该各自解一遍：
 *
 *   - FastAPI 的 ``{"detail": ...}``（鉴权、422 校验等）；
 *   - 业务契约的 ``{"error": {code, message, fields, current, retryable, remedy}}``
 *     （web-business-data-contract §2）。
 *
 * 业务信封取内层 ``error`` 对象作为 ``detail``，调用方才能按契约用 ``code`` 分支
 * （例如 ``snapshot_absent``）；展示文本取 ``message``。此前只认 ``detail``，业务错误
 * 会退化成整段 JSON 文本——2026-10-09 实测：补数弹窗里显示的就是一整段
 * ``{"error":{"code":"unknown_field_rejected",...}}``，真正的字段级原因反而看不到。
 */

/** 解包一次错误响应体；空体返回 ``null``，非 JSON 原样返回文本。 */
export function errorDetailFromBody(text: string): unknown {
  const trimmed = text.trim()
  if (!trimmed) return null
  let body: unknown
  try {
    body = JSON.parse(trimmed)
  } catch {
    return trimmed
  }
  if (body && typeof body === 'object') {
    const record = body as { detail?: unknown; error?: unknown }
    if (record.detail !== undefined) return record.detail
    if (record.error !== undefined) return record.error
  }
  return trimmed
}

/**
 * Render FastAPI's ``detail`` into one display string.
 *
 * 422 bodies are ``[{loc: [...], msg, type}]``; joining every field error is
 * what makes a form usable, and falling back to a generic message keeps a
 * surprising body from rendering as ``[object Object]``.
 */
export function messageFromDetail(status: number, detail: unknown): string {
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
