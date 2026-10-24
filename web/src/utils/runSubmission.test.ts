import test from 'node:test'
import assert from 'node:assert/strict'
import { buildRunPayload } from './runSubmission.ts'

test('each JSON turn carries its selected mode in the same research', () => {
  assert.deepEqual(buildRunPayload('Deep research', [], 'research-1', 'team'), {
    message: 'Deep research', session_id: 'research-1', mode: 'team',
  })
  assert.deepEqual(buildRunPayload('Follow up', [], 'research-1', 'single'), {
    message: 'Follow up', session_id: 'research-1', mode: 'single',
  })
})

test('multipart keeps mode, research and all file contents', async () => {
  const file = new File(['evidence'], 'source.txt', { type: 'text/plain' })
  const payload = buildRunPayload('Read evidence', [file], 'research-1', 'team')
  assert.ok(payload instanceof FormData)
  assert.equal(payload.get('mode'), 'team')
  assert.equal(payload.get('session_id'), 'research-1')
  assert.equal(payload.get('message'), 'Read evidence')
  const files = payload.getAll('files') as File[]
  assert.equal(files.length, 1)
  assert.equal(files[0]?.name, 'source.txt')
  assert.equal(await files[0]?.text(), 'evidence')
})
