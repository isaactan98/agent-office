<script setup lang="ts">
// 2D office: one character per agent, animated from the task's events.
// All state comes from utils/officeState.ts (pure reducer). This component
// only feeds it events (live from the feed, or replayed from events.jsonl)
// and draws the result on a plain Canvas 2D.
import {
  DOOR, WALK_MS, BUBBLE_MS, activeBubble, characterStatus, initialState, reduce, showsAlert, tick, walkProgress
} from '~/utils/officeState'
import type { Character, OfficeEvent, OfficeState } from '~/utils/officeState'

const props = defineProps<{
  taskId: string
  events: OfficeEvent[] // the live feed (past events first, then new ones)
  finished: boolean // replay is offered for done / failed / cancelled tasks only
}>()

const apiBase = useRuntimeConfig().public.apiBase as string

// ---- Layout (canvas units) ----
const W = 720
const H = 360
const CORRIDOR_Y = 170 // characters walk along this line between the rows
const DESK_W = 90
const DESK_H = 40
const DESKS: Record<string, { x: number, y: number, label: string }> = {
  'desk:orchestrator': { x: 140, y: 60, label: 'orchestrator' },
  'desk:writer': { x: 360, y: 60, label: 'writer' },
  'desk:reviewer': { x: 580, y: 60, label: 'reviewer' },
  'spare:1': { x: 460, y: 240, label: 'spare' },
  'spare:2': { x: 560, y: 240, label: 'spare' },
  'spare:3': { x: 660, y: 240, label: 'spare' }
}
const TABLE = { x: 250, y: 290, rx: 80, ry: 30 }
const DOOR_POINT = { x: 30, y: 260 }
// Same colours as the agent tags in the feed.
const COLOURS: Record<string, string> = { orchestrator: '#0550ae', writer: '#8250df', reviewer: '#bc4c00' }

interface Point { x: number, y: number }

// Where a character stands for a place: the door, the chair in front of a
// desk, or a seat around the meeting table (table:<n>, 8 seats, then repeats).
function placePoint(place: string): Point {
  if (place === DOOR) return DOOR_POINT
  const desk = DESKS[place]
  if (desk) return { x: desk.x, y: desk.y + DESK_H / 2 + 26 }
  const n = Number(place.split(':')[1]) || 1
  const angle = -Math.PI / 2 + ((n - 1) % 8) * (Math.PI / 4)
  return { x: TABLE.x + Math.cos(angle) * (TABLE.rx + 18), y: TABLE.y + Math.sin(angle) * (TABLE.ry + 18) }
}

// Position along a walk: up/down to the corridor, across, then to the target.
function walkPoint(from: Point, to: Point, progress: number): Point {
  const path = [from, { x: from.x, y: CORRIDOR_Y }, { x: to.x, y: CORRIDOR_Y }, to]
  const lengths = path.slice(1).map((p, i) => Math.hypot(p.x - path[i]!.x, p.y - path[i]!.y))
  let left = progress * lengths.reduce((a, b) => a + b, 0)
  for (let i = 0; i < lengths.length; i++) {
    const len = lengths[i]!
    if (left <= len && len > 0) {
      const a = path[i]!
      const b = path[i + 1]!
      return { x: a.x + (b.x - a.x) * (left / len), y: a.y + (b.y - a.y) * (left / len) }
    }
    left -= len
  }
  return to
}

function characterPoint(state: OfficeState, c: Character): Point {
  if (!c.walk) return placePoint(c.desk)
  return walkPoint(placePoint(c.walk.from), placePoint(c.walk.to), walkProgress(state, c.name))
}

// ---- Live: follow the feed ----
let liveState = initialState()
let liveCount = 0
// Scene time = Date.now() + clockOffset, so walks and bubbles run on the
// events' own clock. Only moves forward.
let clockOffset = Number.NEGATIVE_INFINITY

function eventMs(event: OfficeEvent): number {
  return typeof event.ts === 'string' ? Date.parse(event.ts) : NaN
}

function feedLive() {
  while (liveCount < props.events.length) {
    const event = props.events[liveCount++]!
    liveState = reduce(liveState, event)
    const ms = eventMs(event)
    if (!Number.isNaN(ms)) clockOffset = Math.max(clockOffset, ms - Date.now())
  }
}
watch(() => props.events.length, feedLive)

// ---- Replay: play events.jsonl with the original relative timing ----
const mode = ref<'live' | 'replay'>('live')
const playing = ref(false)
const speed = ref(1)
const loading = ref(false)
const replayError = ref<string | null>(null)
const replayPos = ref(0) // events played so far
let replayEvents: OfficeEvent[] = []
let replayState = initialState()
let replayClock = 0
let replayEndMs = 0

async function startReplay() {
  loading.value = true
  replayError.value = null
  try {
    replayEvents = await $fetch<OfficeEvent[]>(`${apiBase}/tasks/${props.taskId}/events`)
  } catch (err) {
    replayError.value = `could not load events: ${(err as Error)?.message ?? err}`
    return
  } finally {
    loading.value = false
  }
  const times = replayEvents.map(eventMs).filter(ms => !Number.isNaN(ms))
  replayClock = times.length ? Math.min(...times) : 0
  // Keep playing a little after the last event so the last walk / bubble finishes.
  replayEndMs = (times.length ? Math.max(...times) : 0) + Math.max(WALK_MS, BUBBLE_MS)
  replayState = initialState()
  replayPos.value = 0
  mode.value = 'replay'
  playing.value = true
}

function stepReplay(dtMs: number) {
  if (playing.value) replayClock += dtMs * speed.value
  let pos = replayPos.value
  while (pos < replayEvents.length) {
    const event = replayEvents[pos]!
    if (eventMs(event) > replayClock) break // events without a valid ts play right away
    replayState = reduce(replayState, event)
    pos++
  }
  if (pos !== replayPos.value) replayPos.value = pos
  replayState = tick(replayState, replayClock)
  if (playing.value && pos >= replayEvents.length && replayClock >= replayEndMs) playing.value = false
}

const replayFinished = computed(() =>
  mode.value === 'replay' && !playing.value && replayPos.value >= replayEvents.length
)

function togglePlay() {
  if (replayFinished.value) startReplay()
  else playing.value = !playing.value
}

// ---- Drawing ----
const canvasEl = ref<HTMLCanvasElement | null>(null)
let frame = 0
let lastFrameMs = 0

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath()
  ctx.roundRect(x, y, w, h, r)
}

function drawRoom(ctx: CanvasRenderingContext2D) {
  ctx.fillStyle = '#f3efe6'
  ctx.fillRect(0, 0, W, H)
  ctx.strokeStyle = '#8c959f'
  ctx.lineWidth = 6
  ctx.strokeRect(3, 3, W - 6, H - 6)
  // Door: a gap in the left wall.
  ctx.fillStyle = '#a0784a'
  ctx.fillRect(0, DOOR_POINT.y - 34, 10, 68)
  ctx.fillStyle = '#57606a'
  ctx.font = '10px ui-monospace, monospace'
  ctx.textAlign = 'left'
  ctx.fillText('door', 14, DOOR_POINT.y - 38)
  // Meeting table.
  ctx.fillStyle = '#c9b48a'
  ctx.beginPath()
  ctx.ellipse(TABLE.x, TABLE.y, TABLE.rx, TABLE.ry, 0, 0, Math.PI * 2)
  ctx.fill()
  ctx.fillStyle = '#6e5a36'
  ctx.textAlign = 'center'
  ctx.fillText('meeting table', TABLE.x, TABLE.y + 4)
}

function drawDesk(ctx: CanvasRenderingContext2D, place: string, busy: boolean, now: number) {
  const desk = DESKS[place]!
  const x = desk.x - DESK_W / 2
  const y = desk.y - DESK_H / 2
  ctx.fillStyle = '#b08a5a'
  roundRect(ctx, x, y, DESK_W, DESK_H, 4)
  ctx.fill()
  // Monitor; its screen flickers while the owner is working.
  ctx.fillStyle = '#24292f'
  ctx.fillRect(desk.x - 18, y + 4, 36, 20)
  ctx.fillStyle = busy && Math.floor(now / 200) % 2 === 0 ? '#7ee2a8' : '#57606a'
  ctx.fillRect(desk.x - 15, y + 7, 30, 14)
  ctx.fillStyle = '#4b3a24'
  ctx.font = '10px ui-monospace, monospace'
  ctx.textAlign = 'center'
  ctx.fillText(desk.label, desk.x, y + DESK_H - 5)
}

function drawCharacter(ctx: CanvasRenderingContext2D, state: OfficeState, c: Character, now: number) {
  const status = characterStatus(state, c.name)
  const p = characterPoint(state, c)
  const bob = status === 'walking' ? Math.sin(now / 70) * 2 : 0
  const x = p.x
  const y = p.y + bob
  const colour = COLOURS[c.name] ?? '#6e7781'
  // Body and head.
  ctx.fillStyle = colour
  roundRect(ctx, x - 10, y - 10, 20, 22, 6)
  ctx.fill()
  ctx.beginPath()
  ctx.arc(x, y - 18, 9, 0, Math.PI * 2)
  ctx.fillStyle = '#f2d3b1'
  ctx.fill()
  ctx.strokeStyle = colour
  ctx.lineWidth = 2
  ctx.stroke()
  // Typing: hands going up and down.
  if (status === 'working') {
    const up = Math.floor(now / 120) % 2 === 0
    ctx.fillStyle = '#f2d3b1'
    ctx.beginPath()
    ctx.arc(x - 7, y - 8 - (up ? 3 : 0), 3, 0, Math.PI * 2)
    ctx.arc(x + 7, y - 8 - (up ? 0 : 3), 3, 0, Math.PI * 2)
    ctx.fill()
  }
  ctx.textAlign = 'center'
  ctx.fillStyle = '#1f2328'
  ctx.font = '11px ui-monospace, monospace'
  ctx.fillText(c.name, x, y + 24)
  ctx.fillStyle = '#6e7781'
  ctx.font = '10px ui-monospace, monospace'
  ctx.fillText(status, x, y + 35)
}

function drawOverlays(ctx: CanvasRenderingContext2D, state: OfficeState, c: Character) {
  const p = characterPoint(state, c)
  const bubble = activeBubble(state, c.name)
  if (bubble !== null) {
    ctx.font = '11px -apple-system, BlinkMacSystemFont, sans-serif'
    const w = Math.min(W - 8, ctx.measureText(bubble).width + 14)
    const bx = Math.min(Math.max(4, p.x - w / 2), W - w - 4)
    const by = p.y - 58
    ctx.fillStyle = '#ffffff'
    ctx.strokeStyle = '#57606a'
    ctx.lineWidth = 1
    roundRect(ctx, bx, by, w, 20, 6)
    ctx.fill()
    ctx.stroke()
    ctx.beginPath()
    ctx.moveTo(p.x - 5, by + 20)
    ctx.lineTo(p.x, by + 27)
    ctx.lineTo(p.x + 5, by + 20)
    ctx.fill()
    ctx.fillStyle = '#1f2328'
    ctx.textAlign = 'left'
    ctx.fillText(bubble, bx + 7, by + 14)
  }
  if (showsAlert(state, c.name)) {
    ctx.font = 'bold 22px -apple-system, BlinkMacSystemFont, sans-serif'
    ctx.textAlign = 'center'
    ctx.lineWidth = 3
    ctx.strokeStyle = '#ffffff'
    ctx.strokeText('!', p.x + 16, p.y - 26)
    ctx.fillStyle = '#cf222e'
    ctx.fillText('!', p.x + 16, p.y - 26)
  }
}

function draw(state: OfficeState, now: number) {
  const canvas = canvasEl.value
  const ctx = canvas?.getContext('2d')
  if (!canvas || !ctx) return
  const dpr = window.devicePixelRatio || 1
  if (canvas.width !== W * dpr) {
    canvas.width = W * dpr
    canvas.height = H * dpr
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  drawRoom(ctx)
  const visible = Object.values(state.characters).filter(c => c.present)
  for (const place of Object.keys(DESKS)) {
    const owner = visible.find(c => c.desk === place && !c.walk)
    drawDesk(ctx, place, !!owner && characterStatus(state, owner.name) === 'working', now)
  }
  // Lower characters drawn last so they overlap the ones behind them.
  visible.sort((a, b) => characterPoint(state, a).y - characterPoint(state, b).y)
  for (const c of visible) drawCharacter(ctx, state, c, now)
  for (const c of visible) drawOverlays(ctx, state, c)
}

function loop(frameMs: number) {
  // Clamp: a hidden tab gets no frames, and replay should not jump ahead when
  // it comes back. Slow frame rates (down to 1 fps) still play in real time.
  const dt = lastFrameMs ? Math.min(1000, frameMs - lastFrameMs) : 0
  lastFrameMs = frameMs
  let state: OfficeState
  if (mode.value === 'replay') {
    stepReplay(dt)
    state = replayState
  } else {
    if (Number.isFinite(clockOffset)) liveState = tick(liveState, Date.now() + clockOffset)
    state = liveState
  }
  draw(state, frameMs)
  frame = requestAnimationFrame(loop)
}

onMounted(() => {
  feedLive()
  frame = requestAnimationFrame(loop)
})

onBeforeUnmount(() => cancelAnimationFrame(frame))
</script>

<template>
  <div class="office">
    <div class="office-bar">
      <strong>Office</strong>
      <template v-if="mode === 'live'">
        <span class="muted">live</span>
        <button
          :disabled="!finished || loading"
          :title="finished ? 'Replay events.jsonl' : 'Replay is available once the task has finished'"
          @click="startReplay"
        >
          {{ loading ? 'Loading…' : 'Replay' }}
        </button>
      </template>
      <template v-else>
        <span class="muted">replay: {{ replayPos }}/{{ replayEvents.length }} events</span>
        <button @click="togglePlay">{{ replayFinished ? 'Restart' : playing ? 'Pause' : 'Play' }}</button>
        <button :class="{ active: speed === 1 }" @click="speed = 1">1×</button>
        <button :class="{ active: speed === 4 }" @click="speed = 4">4×</button>
        <button @click="mode = 'live'">Back to live</button>
      </template>
      <span v-if="replayError" class="error">{{ replayError }}</span>
    </div>
    <canvas ref="canvasEl" class="office-canvas" :width="W" :height="H" />
  </div>
</template>

<style scoped>
.office-bar { display: flex; gap: 8px; align-items: center; margin-bottom: 6px; flex-wrap: wrap; }
.office-bar button {
  font: inherit;
  font-size: 12px;
  padding: 2px 10px;
  border: 1px solid #d0d7de;
  border-radius: 6px;
  background: #fff;
  cursor: pointer;
}
.office-bar button:disabled { color: #8c959f; cursor: not-allowed; }
.office-bar button.active { background: #ddf4ff; border-color: #54aeff; }
.office-canvas {
  display: block;
  width: 100%;
  max-width: 720px;
  aspect-ratio: 2 / 1;
  border: 1px solid #d0d7de;
  border-radius: 6px;
}
</style>
