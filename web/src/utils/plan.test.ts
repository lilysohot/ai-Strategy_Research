import assert from 'node:assert/strict'
import { test } from 'node:test'

import { buildPlan, planDoneCount } from './plan.ts'

function addStep(descriptions: string[], addedIds: string[]) {
  return {
    name: 'add_task',
    input: { tasks: descriptions.map((d) => ({ description: d })) },
    output: `Added ${JSON.stringify(addedIds).replaceAll('"', "'")}.\nboard...`,
  }
}

test('buildPlan creates tasks from add_task with ids parsed from output', () => {
  const plan = buildPlan([
    addStep(['Search papers', 'Verify claim'], ['t1', 't2']),
  ])
  assert.deepEqual(plan, [
    { id: 't1', description: 'Search papers', status: 'open' },
    { id: 't2', description: 'Verify claim', status: 'open' },
  ])
})

test('buildPlan applies update_task resolutions in order', () => {
  const plan = buildPlan([
    addStep(['A', 'B', 'C'], ['t1', 't2', 't3']),
    {
      name: 'update_task',
      input: { updates: [{ id: 't1', resolution: 'in_progress' }] },
      output: "Updated ['t1'].",
    },
    {
      name: 'update_task',
      input: {
        updates: [
          { id: 't1', resolution: 'resolved' },
          { id: 't3', resolution: 'cancelled' },
        ],
      },
      output: "Updated ['t1', 't3'].",
    },
  ])
  assert.deepEqual(
    plan.map((t) => [t.id, t.status]),
    [
      ['t1', 'resolved'],
      ['t2', 'open'],
      ['t3', 'cancelled'],
    ],
  )
})

test('buildPlan dedups repeated descriptions instead of duplicating rows', () => {
  const plan = buildPlan([
    addStep(['A'], ['t1']),
    addStep(['A', 'B'], ['t1', 't2']),
  ])
  assert.deepEqual(
    plan.map((t) => t.id),
    ['t1', 't2'],
  )
})

test('buildPlan ignores unrelated tools and malformed shapes', () => {
  const plan = buildPlan([
    { name: 'bash', input: { command: 'ls' }, output: 'x' },
    { name: 'add_task', input: { tasks: 'not-a-list' }, output: 'Added []' },
    { name: 'add_task', input: { tasks: [{ nope: 1 }] }, output: 'Error: ...' },
    { name: 'update_task', input: { updates: [{ id: 'ghost', resolution: 'resolved' }] }, output: '' },
    { name: 'update_task', input: { updates: [{ id: 't9', resolution: 'nonsense' }] }, output: '' },
    {},
  ])
  assert.deepEqual(plan, [])
})

test('buildPlan waits for accepted ids instead of creating optimistic rows', () => {
  const plan = buildPlan([
    { name: 'add_task', input: { tasks: [{ description: 'Only step' }] }, output: '' },
  ])
  assert.equal(plan.length, 0)
})

test('rejected resolutions and duplicate retries preserve the actual board', () => {
  const plan = buildPlan([
    addStep(['Verify'], ['t1']),
    {
      name: 'update_task',
      input: { updates: [{ id: 't1', resolution: 'resolved' }] },
      output: "Error: checks not passed\nUpdated [].\n  ○ t1 open        Verify\nProgress recorded ['t1']; requested resolution rejected.",
    },
    addStep(['Verify'], ['t1']),
  ])
  assert.deepEqual(plan, [{ id: 't1', description: 'Verify', status: 'open' }])
})

test('partial batch accepts only returned ids and blocked is not successful', () => {
  const plan = buildPlan([
    addStep(['Verify', 'Research'], ['t1', 't2']),
    {
      name: 'update_task',
      input: { updates: [{ id: 't1', resolution: 'resolved' }, { id: 't2', resolution: 'resolved' }] },
      output: "Updated ['t2'].\nerrors: t1 rejected",
    },
    {
      name: 'update_task',
      input: { updates: [{ id: 't1', resolution: 'blocked' }] },
      output: "Updated ['t1'].\n  ! t1 blocked     Verify",
    },
  ])
  assert.deepEqual(plan.map((t) => t.status), ['blocked', 'resolved'])
  assert.equal(planDoneCount(plan), 1)
})

test('failed add never creates a ghost row', () => {
  assert.deepEqual(buildPlan([{
    name: 'add_task', input: { tasks: [{ description: 'Verify', bad_field: 1 }] },
    output: 'Error: unknown field',
  }]), [])
})

test('terminal board overrides staged delivery on reconnect', () => {
  const steps = [addStep(['Write answer'], ['t1'])]
  assert.deepEqual(buildPlan(steps, [
    { id: 't1', description: 'Write answer', resolution: 'resolved' },
    { id: 't2', description: 'Verify', resolution: 'blocked' },
  ]).map((t) => t.status), ['resolved', 'blocked'])
  assert.deepEqual(buildPlan(steps, []), [])
})

test('planDoneCount counts resolved only (cancelled stays unfinished)', () => {
  const done = planDoneCount([
    { id: 't1', description: 'a', status: 'resolved' },
    { id: 't2', description: 'b', status: 'cancelled' },
    { id: 't3', description: 'c', status: 'open' },
  ])
  assert.equal(done, 1)
})
