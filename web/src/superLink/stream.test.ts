import test from 'node:test'
import assert from 'node:assert/strict'

import { openSpaceStream, type StreamCloseInfo } from './stream.ts'

const encoder = new TextEncoder()

function sseResponse(chunks: string[], status = 200, headers: Record<string, string> = {}): Response {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      controller.close()
    },
  })
  return new Response(stream, {
    status,
    headers: { 'Content-Type': 'text/event-stream', ...headers },
  })
}

function factFrame(seq: number, invalidate: string[]): string {
  const cursor = `sl1:space-a:epoch-1:${seq}`
  return [
    'event: sl.fact',
    `id: ${cursor}`,
    `data: ${JSON.stringify({
      schema_version: 1,
      type: 'sl.run.changed',
      space_id: 'space-a',
      stream_epoch: 'epoch-1',
      seq: String(seq),
      cursor,
      invalidate,
    })}`,
  ].join('\n') + '\n\n'
}

test('dispatches ordered facts and ignores heartbeats and partial frames', async () => {
  const facts: Array<{ seq?: string; cursor?: string; invalidate?: string[] }> = []
  let opened = 0
  const closed = new Promise<StreamCloseInfo>((resolve) => {
    const first = factFrame(1, ['runs'])
    const second = factFrame(2, ['deliveries'])
    const cut = first.length + 10
    const all = `: heartbeat\n\n${first}${second}`
    const fetchImpl = (async () =>
      sseResponse([all.slice(0, cut), all.slice(cut)])) as typeof fetch
    openSpaceStream({
      url: '/api/super-link/spaces/space-a/events',
      token: 'token-1',
      after: 'sl1:space-a:epoch-1:0',
      fetchImpl,
      callbacks: {
        onFact: (fact) => facts.push(fact),
        onControl: () => assert.fail('no control frames expected'),
        onOpen: () => {
          opened += 1
        },
        onClose: resolve,
      },
    })
  })

  const info = await closed
  assert.equal(info.reason, 'eof')
  assert.equal(opened, 1)
  assert.deepEqual(
    facts.map((f) => f.seq),
    ['1', '2'],
  )
  assert.deepEqual(facts[1].invalidate, ['deliveries'])
})

test('forwards control events with their reason', async () => {
  const controls: Array<[string, string]> = []
  const closed = new Promise<StreamCloseInfo>((resolve) => {
    const body =
      'event: sl.resync_required\n' +
      'data: {"schema_version":1,"reason":"cursor_expired"}\n\n'
    const fetchImpl = (async () => sseResponse([body])) as typeof fetch
    openSpaceStream({
      url: '/events',
      token: () => 'token-1',
      after: 'sl1:space-a:epoch-1:3',
      fetchImpl,
      callbacks: {
        onFact: () => assert.fail('no facts expected'),
        onControl: (event, reason) => controls.push([event, reason]),
        onClose: resolve,
      },
    })
  })

  const info = await closed
  assert.equal(info.reason, 'eof')
  assert.deepEqual(controls, [['sl.resync_required', 'cursor_expired']])
})

test('reports HTTP status and Retry-After without opening the stream', async () => {
  const seen: { url: string; headers: Headers }[] = []
  let opened = 0
  const closed = new Promise<StreamCloseInfo>((resolve) => {
    const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
      seen.push({
        url: String(input),
        headers: new Headers(init?.headers),
      })
      return new Response('', { status: 503, headers: { 'Retry-After': '7' } })
    }) as typeof fetch
    openSpaceStream({
      url: '/api/super-link/spaces/space-a/events',
      token: 'token-1',
      after: 'sl1:space-a:epoch-1:9',
      fetchImpl,
      callbacks: {
        onFact: () => assert.fail('no facts expected'),
        onControl: () => assert.fail('no controls expected'),
        onOpen: () => {
          opened += 1
        },
        onClose: resolve,
      },
    })
  })

  const info = await closed
  assert.equal(info.reason, 'http')
  assert.equal(info.status, 503)
  assert.equal(info.retryAfterMs, 7000)
  assert.equal(opened, 0)
  assert.equal(
    seen[0].url,
    '/api/super-link/spaces/space-a/events?after=sl1%3Aspace-a%3Aepoch-1%3A9',
  )
  assert.equal(seen[0].headers.get('Authorization'), 'Bearer token-1')
  assert.equal(seen[0].headers.get('Accept'), 'text/event-stream')
})

test('stop aborts the connection and suppresses the close callback', async () => {
  let cancelled = false
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode(': heartbeat\n\n'))
    },
    cancel() {
      cancelled = true
    },
  })
  const fetchImpl = (async () => new Response(body, { status: 200 })) as typeof fetch
  let closeCalls = 0
  const handle = openSpaceStream({
    url: '/events',
    token: 'token-1',
    after: 'sl1:space-a:epoch-1:0',
    fetchImpl,
    callbacks: {
      onFact: () => undefined,
      onControl: () => undefined,
      onClose: () => {
        closeCalls += 1
      },
    },
  })
  // Let the fetch and first read settle, then release.
  await new Promise((resolve) => setTimeout(resolve, 10))
  handle.stop()
  await new Promise((resolve) => setTimeout(resolve, 10))
  assert.equal(cancelled, true)
  assert.equal(closeCalls, 0)
})

test('missing bearer fails as an auth HTTP close', async () => {
  const closed = new Promise<StreamCloseInfo>((resolve) => {
    const fetchImpl = (async () => assert.fail('fetch must not run')) as unknown as typeof fetch
    openSpaceStream({
      url: '/events',
      token: null,
      after: 'sl1:space-a:epoch-1:0',
      fetchImpl,
      callbacks: {
        onFact: () => assert.fail('no facts expected'),
        onControl: () => assert.fail('no controls expected'),
        onClose: resolve,
      },
    })
  })
  const info = await closed
  assert.equal(info.reason, 'http')
  assert.equal(info.status, 401)
})
