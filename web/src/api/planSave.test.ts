import assert from 'node:assert/strict'
import test from 'node:test'
import { createServer } from 'vite'

test('Chinese plan names reach the transport without an invalid HTTP header', async () => {
  const server = await createServer({ server: { middlewareMode: true }, appType: 'custom' })
  const originalFetch = globalThis.fetch
  let sent = false
  try {
    globalThis.fetch = async (url, init) => {
      // Fetch performs this conversion before the network sees any request.
      const req = new Request(`http://test${url}`, init)
      sent = true
      assert.equal((await req.json()).name, '工业富联回调买入')
      return Response.json({ plan_id: 'plan-1' })
    }
    const { createPlanWriter } = await server.ssrLoadModule('/src/utils/saveResearchPlan.ts')
    await createPlanWriter().save('research-1', {
      name: '工业富联回调买入', symbol: '601138.SH', market: 'CN',
      direction: 'buy', allocatedCapital: '10000', isPrimary: false,
    })
    assert.equal(sent, true)
  } finally {
    globalThis.fetch = originalFetch
    await server.close()
  }
})

test('retry after link failure reuses the write identity; changed fields get a new one', async () => {
  const server = await createServer({ server: { middlewareMode: true }, appType: 'custom' })
  const originalFetch = globalThis.fetch
  const writes: { path: string; key: string; body: unknown }[] = []
  let failLink = true
  try {
    globalThis.fetch = async (url, init) => {
      const request = new Request(`http://test${url}`, init)
      const key = request.headers.get('Idempotency-Key')!
      assert.match(key, /^[\x21-\x7e]+$/)
      writes.push({ path: String(url), key, body: await request.json() })
      if (String(url).endsWith('/link') && failLink) {
        failLink = false
        return Response.json({ detail: '暂时无法绑定，请重试' }, { status: 503 })
      }
      return Response.json({ plan_id: 'plan-1' })
    }
    const { createPlanWriter } = await server.ssrLoadModule('/src/utils/saveResearchPlan.ts')
    const writer = createPlanWriter()
    const input = { name: '回调买入', symbol: '601138.SH', market: 'CN', direction: 'buy', allocatedCapital: '10000', isPrimary: true }
    await assert.rejects(writer.save('research-1', input), /暂时无法绑定/)
    await writer.save('research-1', input)
    assert.equal(writes[0].key, writes[2].key)
    assert.equal(writes[1].key, writes[3].key)
    await writer.save('research-1', { ...input, allocatedCapital: '20000' })
    assert.notEqual(writes[4].key, writes[0].key)
    writer.reset()
    await writer.save('research-1', { ...input, allocatedCapital: '20000' })
    assert.notEqual(writes[6].key, writes[4].key)
  } finally {
    globalThis.fetch = originalFetch
    await server.close()
  }
})
