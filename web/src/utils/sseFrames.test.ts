import test from 'node:test'
import assert from 'node:assert/strict'

import { extractFrames, parseFrame } from './sseFrames.ts'

test('complete frames split on a blank line and keep the partial tail', () => {
  const { frames, rest } = extractFrames('data: one\n\ndata: two\n\ndata: thr')
  assert.deepEqual(frames, ['data: one', 'data: two'])
  assert.equal(rest, 'data: thr')
})

test('a frame split across chunks is reassembled by the caller', () => {
  const first = extractFrames('data: {"type":"assistant_delta","cont')
  assert.deepEqual(first.frames, [])
  const second = extractFrames(`${first.rest}ent":"你好"}\n\n`)
  assert.deepEqual(second.frames, ['data: {"type":"assistant_delta","content":"你好"}'])
  assert.equal(second.rest, '')
})

test('multi-line data joins with a newline', () => {
  const parsed = parseFrame('data: first\ndata: second')
  assert.equal(parsed?.data, 'first\nsecond')
})

test('heartbeat comments carry no payload', () => {
  assert.equal(parseFrame(': heartbeat'), null)
  assert.equal(parseFrame(': ping'), null)
  // An explicit empty data line is a payload (the consumers reject it as
  // non-JSON); only a frame with no data field at all is a comment.
  assert.deepEqual(parseFrame('data:'), {
    data: '',
    event: null,
    id: null,
    retry: undefined,
  })
})

test('event, id and retry fields are parsed but excluded from data', () => {
  const parsed = parseFrame(
    'event: sl.fact\nid: sl1:space:epoch:7\ndata: {"seq":"7"}\nretry: 2500',
  )
  assert.deepEqual(parsed, {
    data: '{"seq":"7"}',
    event: 'sl.fact',
    id: 'sl1:space:epoch:7',
    retry: 2500,
  })
})

test('unknown fields and invalid retry values are ignored', () => {
  const parsed = parseFrame('foo: bar\ndata: x\nretry: nope')
  assert.deepEqual(parsed, { data: 'x', event: null, id: null, retry: undefined })
})
