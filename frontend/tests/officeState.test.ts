// Unit tests for app/utils/officeState.ts. Run: npm test (Node's built-in
// test runner; Node strips the TypeScript types itself).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  ALERT_MS, BUBBLE_MS, MIN_WORK_MS, WALK_MS,
  activeBubble, characterStatus, initialState, reduce, showsAlert, tick, walkProgress
} from '../app/utils/officeState.ts'
import type { OfficeEvent, OfficeState } from '../app/utils/officeState.ts'

const T0 = Date.parse('2026-11-03T23:12:35.000+08:00')

// Event at T0 + ms.
function ev(ms: number, type: string, agent = 'orchestrator', extra: Partial<OfficeEvent> = {}): OfficeEvent {
  return { ts: new Date(T0 + ms).toISOString(), task_id: 't', agent, type, tool: null, path: null, summary: '', ...extra }
}

function run(events: OfficeEvent[], state: OfficeState = initialState()): OfficeState {
  return events.reduce(reduce, state)
}

function deepFreeze<T>(value: T): T {
  if (typeof value === 'object' && value !== null) {
    Object.values(value).forEach(deepFreeze)
    Object.freeze(value)
  }
  return value
}

test('initial state: orchestrator idle at its desk, nobody else', () => {
  const s = initialState()
  assert.deepEqual(Object.keys(s.characters), ['orchestrator'])
  assert.equal(s.characters.orchestrator!.present, true)
  assert.equal(s.characters.orchestrator!.desk, 'desk:orchestrator')
  assert.equal(characterStatus(s, 'orchestrator'), 'idle')
  assert.equal(s.task, 'none')
})

test('task_queued and task_started set the task status only', () => {
  let s = run([ev(0, 'task_queued')])
  assert.equal(s.task, 'queued')
  s = reduce(s, ev(10, 'task_started'))
  assert.equal(s.task, 'running')
  assert.equal(s.nowMs, T0 + 10)
  assert.equal(characterStatus(s, 'orchestrator'), 'idle')
})

test('tool_start → working until tool_end, held for at least MIN_WORK_MS', () => {
  let s = run([ev(0, 'tool_start', 'orchestrator', { tool: 'Write' })])
  assert.equal(s.characters.orchestrator!.openTools, 1)
  assert.equal(characterStatus(s, 'orchestrator'), 'working')
  s = reduce(s, ev(10, 'tool_end', 'orchestrator', { tool: 'Write' }))
  assert.equal(s.characters.orchestrator!.openTools, 0)
  assert.equal(characterStatus(tick(s, T0 + MIN_WORK_MS - 1), 'orchestrator'), 'working')
  assert.equal(characterStatus(tick(s, T0 + MIN_WORK_MS), 'orchestrator'), 'idle')
})

test('a long tool keeps the character working past MIN_WORK_MS', () => {
  const s = run([ev(0, 'tool_start')])
  assert.equal(characterStatus(tick(s, T0 + 60_000), 'orchestrator'), 'working')
  const done = reduce(tick(s, T0 + 60_000), ev(60_000, 'tool_end'))
  assert.equal(characterStatus(done, 'orchestrator'), 'idle')
})

test('tool_end without tool_start does not go below zero', () => {
  const s = run([ev(0, 'tool_end')])
  assert.equal(s.characters.orchestrator!.openTools, 0)
  assert.equal(characterStatus(s, 'orchestrator'), 'idle')
})

test('agent_message → talking with the first 40 chars for BUBBLE_MS', () => {
  const summary = 'The guide is ready in `output/route.md`, at about 430 words'
  const s = run([ev(0, 'agent_message', 'orchestrator', { summary })])
  assert.equal(characterStatus(s, 'orchestrator'), 'talking')
  assert.equal(activeBubble(s, 'orchestrator'), `${summary.slice(0, 40)}…`)
  const later = tick(s, T0 + BUBBLE_MS)
  assert.equal(characterStatus(later, 'orchestrator'), 'idle')
  assert.equal(activeBubble(later, 'orchestrator'), null)
})

test('agent_message: short text is kept whole, missing summary is empty', () => {
  assert.equal(activeBubble(run([ev(0, 'agent_message', 'orchestrator', { summary: 'Hi\nthere' })]), 'orchestrator'), 'Hi there')
  assert.equal(activeBubble(run([ev(0, 'agent_message', 'orchestrator', { summary: undefined })]), 'orchestrator'), '')
})

test('talking ends back in working when a tool is still open', () => {
  const s = run([ev(0, 'tool_start'), ev(10, 'agent_message', 'orchestrator', { summary: 'x' })])
  assert.equal(characterStatus(s, 'orchestrator'), 'talking')
  assert.equal(characterStatus(tick(s, T0 + 10 + BUBBLE_MS), 'orchestrator'), 'working')
})

test('tool_denied → red "!" for ALERT_MS, no open tool', () => {
  const s = run([ev(0, 'tool_denied', 'orchestrator', { tool: 'Write' })])
  assert.equal(showsAlert(s, 'orchestrator'), true)
  assert.equal(s.characters.orchestrator!.openTools, 0)
  assert.equal(showsAlert(tick(s, T0 + ALERT_MS), 'orchestrator'), false)
})

test('subagent_start → walks from the door to its desk, then idle', () => {
  const s = run([ev(0, 'subagent_start', 'writer')])
  const writer = s.characters.writer!
  assert.equal(writer.present, true)
  assert.equal(writer.desk, 'desk:writer')
  assert.deepEqual(writer.walk, { from: 'door', to: 'desk:writer', startMs: T0 })
  assert.equal(characterStatus(s, 'writer'), 'walking')
  assert.equal(walkProgress(tick(s, T0 + WALK_MS / 2), 'writer'), 0.5)
  const arrived = tick(s, T0 + WALK_MS)
  assert.equal(arrived.characters.writer!.walk, null)
  assert.equal(arrived.characters.writer!.present, true)
  assert.equal(characterStatus(arrived, 'writer'), 'idle')
})

test('a tool started while walking in shows as working after arrival', () => {
  const s = run([ev(0, 'subagent_start', 'writer'), ev(500, 'tool_start', 'writer')])
  assert.equal(characterStatus(s, 'writer'), 'walking')
  assert.equal(characterStatus(tick(s, T0 + WALK_MS), 'writer'), 'working')
})

test('subagent_stop → walks to the door and leaves the room', () => {
  const s = run([
    ev(0, 'subagent_start', 'reviewer'),
    ev(3000, 'tool_start', 'reviewer'),
    ev(4000, 'subagent_stop', 'reviewer')
  ])
  const reviewer = s.characters.reviewer!
  assert.deepEqual(reviewer.walk, { from: 'desk:reviewer', to: 'door', startMs: T0 + 4000 })
  assert.equal(reviewer.openTools, 0)
  assert.equal(characterStatus(s, 'reviewer'), 'walking')
  const gone = tick(s, T0 + 4000 + WALK_MS)
  assert.equal(gone.characters.reviewer!.present, false)
  assert.equal(characterStatus(gone, 'reviewer'), 'idle')
})

test('the same subagent can come back after leaving', () => {
  const s = run([
    ev(0, 'subagent_start', 'writer'),
    ev(5000, 'subagent_stop', 'writer'),
    ev(10_000, 'subagent_start', 'writer')
  ])
  assert.equal(s.characters.writer!.present, true)
  assert.deepEqual(s.characters.writer!.walk, { from: 'door', to: 'desk:writer', startMs: T0 + 10_000 })
})

test('task_done and task_failed: task status set, nobody keeps working', () => {
  for (const type of ['task_done', 'task_failed']) {
    const s = run([ev(0, 'tool_start'), ev(10, type)])
    assert.equal(s.task, type === 'task_done' ? 'done' : 'failed')
    assert.equal(s.characters.orchestrator!.openTools, 0)
    assert.equal(characterStatus(s, 'orchestrator'), 'idle')
  }
})

test('unknown event type is ignored (same state object)', () => {
  const s = run([ev(0, 'task_started')])
  assert.equal(reduce(s, ev(99_000, 'something_new', 'writer')), s)
})

test('events that are not objects or have no type are ignored', () => {
  const s = initialState()
  assert.equal(reduce(s, null as unknown as OfficeEvent), s)
  assert.equal(reduce(s, { agent: 'writer' }), s)
  assert.equal(reduce(s, { type: 42 } as unknown as OfficeEvent), s)
})

test('agent event without an agent name changes no character', () => {
  const s = reduce(initialState(), { ts: new Date(T0).toISOString(), type: 'tool_start' })
  assert.deepEqual(Object.keys(s.characters), ['orchestrator'])
  assert.equal(s.characters.orchestrator!.openTools, 0)
})

test('unknown agents get spare desks, then meeting table seats', () => {
  const names = ['a', 'b', 'c', 'd', 'e']
  const s = run(names.map((name, i) => ev(i, 'tool_start', name)))
  assert.deepEqual(names.map(n => s.characters[n]!.desk), ['spare:1', 'spare:2', 'spare:3', 'table:1', 'table:2'])
  // First seen outside subagent_start: already at the desk.
  assert.equal(s.characters.a!.present, true)
  assert.equal(characterStatus(s, 'a'), 'working')
})

test('missing or bad ts uses the current clock; time never goes back', () => {
  let s = run([ev(5000, 'task_started')])
  s = reduce(s, { type: 'tool_start', agent: 'orchestrator' })
  assert.equal(s.nowMs, T0 + 5000)
  s = reduce(s, { type: 'tool_end', agent: 'orchestrator', ts: 'not a date' })
  assert.equal(s.nowMs, T0 + 5000)
  s = reduce(s, ev(1000, 'agent_message', 'orchestrator', { summary: 'late' }))
  assert.equal(s.nowMs, T0 + 5000)
  assert.equal(tick(s, T0), s)
})

test('reduce and tick never mutate their input', () => {
  const events = [
    ev(0, 'task_queued'), ev(1, 'task_started'), ev(2, 'subagent_start', 'writer'),
    ev(3, 'tool_start', 'writer'), ev(4, 'tool_end', 'writer'), ev(5, 'tool_denied', 'writer'),
    ev(6, 'agent_message'), ev(7, 'subagent_stop', 'writer'), ev(8, 'task_failed'), ev(9, 'task_done')
  ]
  let s = deepFreeze(initialState())
  for (const e of events) {
    s = deepFreeze(reduce(s, deepFreeze(e)))
  }
  deepFreeze(tick(s, T0 + 60_000))
})
