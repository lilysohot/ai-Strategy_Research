import test from 'node:test'
import assert from 'node:assert/strict'

import {
  applyPreview,
  applyReset,
  blockMemberLabel,
  clearLive,
  cloneLive,
  emptyLiveState,
  markArchiveLoaded,
  MAX_LIVE_BLOCK_CHARS,
  MAX_LIVE_RUNS,
  shouldPollRunDetail,
  visibleBlocks,
} from './live.ts'
import type { SpacePreview } from './stream.ts'
import type { RunTraceRecord } from '../types.ts'

const SPACE = 'space-1'

function frame(overrides: Partial<SpacePreview> = {}): SpacePreview {
  return {
    schema_version: 1,
    space_id: SPACE,
    run_id: 'run-a',
    output_epoch: 'epoch-1',
    output_seq: 1,
    kind: 'content',
    member: { agent_id: 'member-a', agent_kind: 'subagent' },
    turn: 2,
    block_key: 'content|subagent|member-a|2',
    text: 'hello',
    ...overrides,
  }
}

function record(overrides: Partial<RunTraceRecord> = {}): RunTraceRecord {
  return {
    t: 'llm',
    turn: 2,
    agent_id: 'member-a',
    agent_kind: 'subagent',
    ...overrides,
  }
}

test('content and thinking accumulate by block without crossing members', () => {
  const live = emptyLiveState()
  assert.equal(applyPreview(live, frame({ kind: 'thinking', block_key: 'thinking|subagent|member-a|2', text: 'why' }), SPACE), true)
  assert.equal(applyPreview(live, frame({ output_seq: 2, text: 'hello' }), SPACE), true)
  assert.equal(applyPreview(live, frame({ output_seq: 3, text: ' hello' }), SPACE), true)
  assert.equal(
    applyPreview(
      live,
      frame({
        output_seq: 4,
        block_key: 'content|subagent|member-b|2',
        member: { agent_id: 'member-b', agent_kind: 'subagent' },
        text: 'other',
      }),
      SPACE,
    ),
    true,
  )

  const run = live.runs['run-a']
  assert.equal(run.blocks.length, 3)
  assert.equal(run.blocks[0].text, 'why')
  assert.equal(run.blocks[1].text, 'hello hello')
  assert.equal(run.blocks[2].agent_id, 'member-b')
  assert.equal(blockMemberLabel(run.blocks[1]), '成员 · member-a')
})

test('a run without thinking frames has no thinking block', () => {
  const live = emptyLiveState()
  applyPreview(live, frame({ text: 'answer' }), SPACE)
  assert.deepEqual(
    live.runs['run-a'].blocks.map((block) => block.kind),
    ['content'],
  )
})

test('a new output epoch clears every previous run', () => {
  const live = emptyLiveState()
  applyPreview(live, frame(), SPACE)
  applyPreview(live, frame({ run_id: 'run-b', output_seq: 1, text: 'b' }), SPACE)
  assert.deepEqual(Object.keys(live.runs).sort(), ['run-a', 'run-b'])

  applyPreview(
    live,
    frame({ output_epoch: 'epoch-2', output_seq: 1, text: 'new' }),
    SPACE,
  )
  assert.equal(live.epoch, 'epoch-2')
  assert.deepEqual(Object.keys(live.runs), ['run-a'])
  assert.equal(live.runs['run-a'].blocks[0].text, 'new')
})

test('a sequence gap clears the run and marks it for archive repair', () => {
  const live = emptyLiveState()
  applyPreview(live, frame({ text: 'first' }), SPACE)
  applyPreview(live, frame({ output_seq: 2, text: ' second' }), SPACE)
  applyPreview(live, frame({ output_seq: 5, text: 'after-gap' }), SPACE)

  const run = live.runs['run-a']
  assert.equal(run.needsArchive, true)
  assert.equal(run.lastSeq, 5)
  assert.equal(run.blocks.length, 1)
  assert.equal(run.blocks[0].text, 'after-gap')
})

test('duplicate and late frames are ignored without clearing text', () => {
  const live = emptyLiveState()
  applyPreview(live, frame({ text: 'first' }), SPACE)
  applyPreview(live, frame({ output_seq: 1, text: 'duplicate' }), SPACE)

  const run = live.runs['run-a']
  assert.equal(run.blocks[0].text, 'first')
  assert.equal(run.needsArchive, false)
})

test('output reset clears only the named runs and demands archive repair', () => {
  const live = emptyLiveState()
  applyPreview(live, frame(), SPACE)
  applyPreview(live, frame({ run_id: 'run-b', output_seq: 1 }), SPACE)

  assert.equal(
    applyReset(
      live,
      { schema_version: 1, space_id: SPACE, run_ids: ['run-a'], reason: 'preview_overflow' },
      SPACE,
    ),
    true,
  )

  assert.deepEqual(live.runs['run-a'].blocks, [])
  assert.equal(live.runs['run-a'].needsArchive, true)
  assert.equal(live.runs['run-b'].blocks.length, 1)

  // A reset run accepts the next frame as a new baseline even if its sequence
  // continues from the old one.
  applyPreview(live, frame({ output_seq: 9, text: 'resumed' }), SPACE)
  assert.equal(live.runs['run-a'].blocks[0].text, 'resumed')
  assert.equal(live.runs['run-a'].lastSeq, 9)
})

test('terminal marks the run inactive and keeps the final text in the archive', () => {
  const live = emptyLiveState()
  applyPreview(live, frame({ text: 'body' }), SPACE)
  assert.equal(
    applyPreview(
      live,
      frame({ output_seq: 2, kind: 'terminal', status: 'completed' }),
      SPACE,
    ),
    true,
  )

  const run = live.runs['run-a']
  assert.equal(run.active, false)
  assert.equal(run.terminalStatus, 'completed')
  assert.equal(run.blocks[0].text, 'body')

  assert.equal(markArchiveLoaded(live, 'run-a'), true)
  assert.equal(live.runs['run-a'], undefined)
})

test('tool frames merge by call id and expose the final state', () => {
  const live = emptyLiveState()
  applyPreview(
    live,
    frame({
      kind: 'tool',
      block_key: 'tool|subagent|member-a|call-1',
      tool: { call_id: 'call-1', name: 'web_search', state: 'started' },
    }),
    SPACE,
  )
  applyPreview(
    live,
    frame({
      output_seq: 2,
      kind: 'tool',
      block_key: 'tool|subagent|member-a|call-1',
      tool: {
        call_id: 'call-1',
        name: 'web_search',
        state: 'finished',
        ok: true,
        detail: '3 results',
        ms: 25,
      },
    }),
    SPACE,
  )

  const block = live.runs['run-a'].blocks[0]
  assert.equal(block.kind, 'tool')
  assert.equal(block.tool?.state, 'finished')
  assert.equal(block.tool?.ok, true)
  assert.equal(block.tool?.detail, '3 results')
})

test('unknown kinds still advance the sequence but create no block', () => {
  const live = emptyLiveState()
  applyPreview(live, frame({ kind: 'future-kind' }), SPACE)
  assert.equal(live.runs['run-a'].lastSeq, 1)
  assert.deepEqual(live.runs['run-a'].blocks, [])
})

test('space mismatch and malformed envelopes are ignored', () => {
  const live = emptyLiveState()
  assert.equal(applyPreview(live, frame({ space_id: 'other' }), SPACE), false)
  assert.equal(applyPreview(live, frame({ output_seq: 0 }), SPACE), false)
  assert.equal(applyPreview(live, frame({ run_id: '' }), SPACE), false)
  assert.deepEqual(live.runs, {})
})

test('archived turns hide the matching live blocks', () => {
  const live = emptyLiveState()
  applyPreview(live, frame({ text: 'live content' }), SPACE)
  applyPreview(
    live,
    frame({
      output_seq: 2,
      kind: 'thinking',
      block_key: 'thinking|subagent|member-a|2',
      text: 'live thinking',
    }),
    SPACE,
  )

  assert.equal(visibleBlocks(live.runs['run-a'], []).length, 2)
  assert.deepEqual(visibleBlocks(live.runs['run-a'], [record()]), [])

  // Another member's archive does not hide this member's live text.
  assert.equal(
    visibleBlocks(live.runs['run-a'], [
      record({ agent_id: 'member-b' }),
    ]).length,
    2,
  )
})

test('archived tool calls hide the matching live tool by name and turn', () => {
  const live = emptyLiveState()
  applyPreview(
    live,
    frame({
      kind: 'tool',
      block_key: 'tool|subagent|member-a|call-1',
      tool: { call_id: 'call-1', name: 'web_search', state: 'finished', ok: true },
    }),
    SPACE,
  )

  const archived = record({
    tool_calls: [{ id: 'call-1', name: 'web_search' }],
  })
  assert.deepEqual(visibleBlocks(live.runs['run-a'], [archived]), [])
  assert.equal(
    visibleBlocks(live.runs['run-a'], [
      record({ tool_calls: [{ id: 'call-2', name: 'read_file' }] }),
    ]).length,
    1,
  )
})

test('text stops growing at the per-block cap and flags truncation', () => {
  const live = emptyLiveState()
  applyPreview(live, frame({ text: 'x'.repeat(MAX_LIVE_BLOCK_CHARS + 10) }), SPACE)
  applyPreview(live, frame({ output_seq: 2, text: 'more' }), SPACE)

  const block = live.runs['run-a'].blocks[0]
  assert.equal(block.text.length, MAX_LIVE_BLOCK_CHARS)
  assert.equal(block.truncated, true)
})

test('cloning isolates block and tool mutation', () => {
  const live = emptyLiveState()
  applyPreview(
    live,
    frame({
      kind: 'tool',
      block_key: 'tool|subagent|member-a|call-1',
      tool: { call_id: 'call-1', name: 'web_search', state: 'started' },
    }),
    SPACE,
  )
  const copy = cloneLive(live)
  applyPreview(
    live,
    frame({
      output_seq: 2,
      kind: 'tool',
      block_key: 'tool|subagent|member-a|call-1',
      tool: { call_id: 'call-1', name: 'web_search', state: 'finished' },
    }),
    SPACE,
  )

  assert.equal(copy.runs['run-a'].blocks[0].tool?.state, 'started')
  assert.equal(live.runs['run-a'].blocks[0].tool?.state, 'finished')
})

test('clearLive resets the epoch and all previews', () => {
  const live = emptyLiveState()
  applyPreview(live, frame(), SPACE)
  assert.equal(clearLive(live), true)
  assert.equal(live.epoch, null)
  assert.deepEqual(live.runs, {})
  assert.equal(clearLive(live), false)
})

test('a reset received before the first preview survives epoch initialisation', () => {
  const live = emptyLiveState()
  assert.equal(
    applyReset(
      live,
      { schema_version: 1, space_id: SPACE, run_ids: ['run-a'], reason: 'preview_overflow' },
      SPACE,
    ),
    true,
  )
  assert.equal(live.epoch, null)
  assert.equal(live.runs['run-a'].needsArchive, true)

  assert.equal(applyPreview(live, frame({ output_seq: 3, text: 'resumed' }), SPACE), true)
  assert.equal(live.epoch, 'epoch-1')
  assert.equal(live.runs['run-a'].needsArchive, true)
  assert.equal(live.runs['run-a'].lastSeq, 3)
  assert.equal(live.runs['run-a'].blocks[0].text, 'resumed')
})

test('single previews match the archived single identity', () => {
  const live = emptyLiveState()
  const singleMember = { agent_id: '', agent_kind: '' }
  applyPreview(
    live,
    frame({
      member: singleMember,
      block_key: 'content|single||1',
      turn: 1,
      text: 'answer',
    }),
    SPACE,
  )
  applyPreview(
    live,
    frame({
      output_seq: 2,
      kind: 'tool',
      member: singleMember,
      block_key: 'tool|single||call-1',
      turn: 1,
      tool: { call_id: 'call-1', name: 'web_search', state: 'started' },
    }),
    SPACE,
  )

  // The real archive annotates the single trajectory as react_agent/single.
  const archived = record({
    t: 'llm',
    turn: 1,
    agent_id: 'react_agent',
    agent_kind: 'single',
    tool_calls: [{ id: 'call-1', name: 'web_search' }],
  })
  assert.deepEqual(visibleBlocks(live.runs['run-a'], [archived]), [])
})

test('every accepted preview enforces the live run budget', () => {
  const live = emptyLiveState()
  for (let i = 0; i < 20; i += 1) {
    const runId = `run-${i}`
    applyPreview(live, frame({ run_id: runId, text: 'x' }), SPACE)
    applyPreview(
      live,
      frame({ run_id: runId, output_seq: 2, kind: 'terminal', status: 'completed' }),
      SPACE,
    )
  }

  assert.ok(Object.keys(live.runs).length <= MAX_LIVE_RUNS)
  assert.ok(live.runs['run-19'], 'the newest run must survive eviction')
})

test('normal mode polling ignores absent space flags', () => {
  // Vue supplies absent Boolean props as false, so a normal ChatView has
  // liveMode=false and liveActive=false while the global run is still active.
  assert.equal(
    shouldPollRunDetail({ liveMode: false, liveActive: false, globalRunning: true }),
    true,
  )
  assert.equal(
    shouldPollRunDetail({ liveMode: false, liveActive: false, globalRunning: false }),
    false,
  )
  assert.equal(
    shouldPollRunDetail({ liveMode: true, liveActive: false, globalRunning: true }),
    false,
  )
  assert.equal(
    shouldPollRunDetail({ liveMode: true, liveActive: true, globalRunning: false }),
    true,
  )
})
