// State of the 2D office (components/Office.vue), driven only by task events.
// Pure functions: no DOM, no timers, no clock reads, inputs are never mutated.
// Time comes from each event's `ts`, or from the `nowMs` given to tick(),
// in milliseconds since the epoch.

// One event (docs/PLAN.md "Event schema"). Typed loosely: unknown types or
// missing fields must not throw.
export interface OfficeEvent {
  seq?: number
  ts?: string
  agent?: string
  type?: string
  tool?: string | null
  path?: string | null
  summary?: string
  [key: string]: unknown
}

export type CharacterStatus = 'idle' | 'walking' | 'working' | 'talking'
export type TaskStatus = 'none' | 'queued' | 'running' | 'done' | 'failed'

// A place is 'door', 'desk:<agent>', 'spare:<n>' or 'table:<n>'.
// Office.vue maps places to canvas coordinates.
export const DOOR = 'door'
// Agents defined in backend/app/agents.py each have their own desk.
export const KNOWN_AGENTS = ['orchestrator', 'writer', 'reviewer']
export const SPARE_DESKS = ['spare:1', 'spare:2', 'spare:3']

export const WALK_MS = 2000 // door ↔ desk
export const BUBBLE_MS = 3000 // speech bubble after agent_message
export const BUBBLE_CHARS = 40
export const ALERT_MS = 3000 // red "!" after tool_denied
// Tools usually finish within milliseconds, so a character keeps typing for at
// least this long after tool_start, otherwise "working" would never be visible.
export const MIN_WORK_MS = 1500

export interface Walk {
  from: string
  to: string
  startMs: number
}

export interface Character {
  name: string
  desk: string
  present: boolean // in the room (false = has not come in yet, or has left)
  walk: Walk | null // set while walking
  openTools: number // tool_start minus tool_end
  workUntilMs: number
  bubble: string | null
  bubbleUntilMs: number
  alertUntilMs: number
}

export interface OfficeState {
  nowMs: number
  task: TaskStatus
  characters: Record<string, Character>
}

const TASK_TYPES: Record<string, TaskStatus> = {
  task_queued: 'queued',
  task_started: 'running',
  task_done: 'done',
  task_failed: 'failed'
}
const AGENT_TYPES = new Set([
  'agent_message', 'tool_start', 'tool_end', 'tool_denied', 'subagent_start', 'subagent_stop'
])

function newCharacter(state: OfficeState, name: string, present: boolean): Character {
  return {
    name,
    desk: deskFor(state, name),
    present,
    walk: null,
    openTools: 0,
    workUntilMs: 0,
    bubble: null,
    bubbleUntilMs: 0,
    alertUntilMs: 0
  }
}

// Known agents get their own desk. Others get the first free spare desk, then
// a seat at the meeting table.
function deskFor(state: OfficeState, name: string): string {
  if (KNOWN_AGENTS.includes(name)) return `desk:${name}`
  const taken = new Set(Object.values(state.characters).map(c => c.desk))
  const spare = SPARE_DESKS.find(desk => !taken.has(desk))
  if (spare) return spare
  let seat = 1
  while (taken.has(`table:${seat}`)) seat++
  return `table:${seat}`
}

export function initialState(): OfficeState {
  const empty: OfficeState = { nowMs: 0, task: 'none', characters: {} }
  // The orchestrator is the main session: always in the room.
  return { ...empty, characters: { orchestrator: newCharacter(empty, 'orchestrator', true) } }
}

function eventMs(event: OfficeEvent, fallback: number): number {
  const ms = typeof event.ts === 'string' ? Date.parse(event.ts) : NaN
  return Number.isNaN(ms) ? fallback : Math.max(ms, fallback)
}

function bubbleText(summary: unknown): string {
  const text = typeof summary === 'string' ? summary.replace(/\s+/g, ' ').trim() : ''
  return text.length > BUBBLE_CHARS ? `${text.slice(0, BUBBLE_CHARS)}…` : text
}

// Move the clock forward to nowMs and finish walks that are over.
// A character who walked to the door leaves the room.
export function tick(state: OfficeState, nowMs: number): OfficeState {
  if (!(nowMs > state.nowMs)) return state
  const characters: Record<string, Character> = {}
  for (const [name, c] of Object.entries(state.characters)) {
    characters[name] = c.walk && nowMs >= c.walk.startMs + WALK_MS
      ? { ...c, walk: null, present: c.walk.to !== DOOR }
      : c
  }
  return { ...state, nowMs, characters }
}

export function reduce(state: OfficeState, event: OfficeEvent): OfficeState {
  if (typeof event !== 'object' || event === null || typeof event.type !== 'string') return state
  const type = event.type
  const taskStatus = TASK_TYPES[type]
  if (!taskStatus && !AGENT_TYPES.has(type)) return state // unknown type: ignored

  const at = eventMs(event, state.nowMs)
  const next = tick(state, at)

  if (taskStatus) {
    const characters: Record<string, Character> = { ...next.characters }
    if (type === 'task_done' || type === 'task_failed') {
      // Nothing is running any more: nobody stays at the keyboard.
      for (const name of Object.keys(characters)) {
        characters[name] = { ...characters[name]!, openTools: 0, workUntilMs: 0 }
      }
    }
    return { ...next, task: taskStatus, characters }
  }

  if (typeof event.agent !== 'string' || event.agent === '') return next
  const name = event.agent
  // A character seen for the first time outside subagent_start is already at its desk.
  const before = next.characters[name] ?? newCharacter(next, name, type !== 'subagent_start')
  let c: Character = before

  switch (type) {
    case 'agent_message':
      c = { ...c, bubble: bubbleText(event.summary), bubbleUntilMs: at + BUBBLE_MS }
      break
    case 'tool_start':
      c = { ...c, openTools: c.openTools + 1, workUntilMs: Math.max(c.workUntilMs, at + MIN_WORK_MS) }
      break
    case 'tool_end':
      c = { ...c, openTools: Math.max(0, c.openTools - 1) }
      break
    case 'tool_denied':
      c = { ...c, alertUntilMs: at + ALERT_MS }
      break
    case 'subagent_start':
      c = { ...c, openTools: 0, workUntilMs: 0 }
      if (!c.present || c.walk?.to === DOOR) {
        c = { ...c, present: true, walk: { from: DOOR, to: c.desk, startMs: at } }
      }
      break
    case 'subagent_stop':
      c = { ...c, openTools: 0, workUntilMs: 0 }
      if (c.present && c.walk?.to !== DOOR) {
        c = { ...c, walk: { from: c.desk, to: DOOR, startMs: at } }
      }
      break
  }
  return { ...next, characters: { ...next.characters, [name]: c } }
}

// What the character is doing at state.nowMs. Call tick() first.
export function characterStatus(state: OfficeState, name: string): CharacterStatus {
  const c = state.characters[name]
  if (!c) return 'idle'
  if (c.walk) return 'walking'
  if (c.bubble !== null && state.nowMs < c.bubbleUntilMs) return 'talking'
  if (c.openTools > 0 || state.nowMs < c.workUntilMs) return 'working'
  return 'idle'
}

export function activeBubble(state: OfficeState, name: string): string | null {
  const c = state.characters[name]
  return c && c.bubble !== null && state.nowMs < c.bubbleUntilMs ? c.bubble : null
}

export function showsAlert(state: OfficeState, name: string): boolean {
  const c = state.characters[name]
  return !!c && state.nowMs < c.alertUntilMs
}

// 0..1 along the current walk (1 when not walking).
export function walkProgress(state: OfficeState, name: string): number {
  const walk = state.characters[name]?.walk
  if (!walk) return 1
  return Math.min(1, Math.max(0, (state.nowMs - walk.startMs) / WALK_MS))
}
