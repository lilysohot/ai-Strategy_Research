import assert from 'node:assert/strict'
import test from 'node:test'

import { errorDetailFromBody, messageFromDetail } from './apiError.ts'

test('business envelope is unwrapped to the inner error object', () => {
  // 2026-10-09 补数弹窗实测：只认 detail 时，用户看到的就是这一整段 JSON。
  const body = JSON.stringify({
    error: {
      code: 'unknown_field_rejected',
      message: '回答包含未请求的字段',
      fields: { 'plan.risk_budget_value': '请只回答本次待补字段' },
      current: {},
      retryable: false,
      remedy: 'fix_fields',
    },
  })
  const detail = errorDetailFromBody(body) as { code?: string }
  assert.equal(detail.code, 'unknown_field_rejected')
  assert.equal(messageFromDetail(400, detail), '回答包含未请求的字段')
  assert.equal(typeof detail, 'object')
  assert.notEqual(detail, null)
})

test('FastAPI detail still wins, string and 422 list included', () => {
  assert.equal(errorDetailFromBody('{"detail":"未认证"}'), '未认证')
  const list = errorDetailFromBody(
    JSON.stringify({ detail: [{ loc: ['body', 'message'], msg: '必填' }] }),
  )
  assert.equal(messageFromDetail(422, list), 'message: 必填')
  // 业务信封与 FastAPI 信封同时出现时不歧义：detail 优先。
  assert.equal(
    errorDetailFromBody('{"detail":"x","error":{"code":"y"}}'),
    'x',
  )
})

test('empty and non-JSON bodies keep their previous behaviour', () => {
  assert.equal(errorDetailFromBody(''), null)
  assert.equal(errorDetailFromBody('   '), null)
  assert.equal(errorDetailFromBody('<html>502</html>'), '<html>502</html>')
  assert.equal(errorDetailFromBody('[1,2]'), '[1,2]')
})

test('unknown shapes fall back to a status message', () => {
  assert.equal(messageFromDetail(404, null), '资源不存在或无权访问')
  assert.equal(messageFromDetail(409, null), '操作冲突，请重试')
  assert.equal(messageFromDetail(0, null), '网络异常，请检查连接')
  assert.equal(messageFromDetail(418, { current: {} }), '请求失败（HTTP 418）')
})
