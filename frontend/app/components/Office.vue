<script setup lang="ts">
// Office: one robot per agent, animated from the task's events.
// All state comes from utils/officeState.ts (pure reducer). This component
// only feeds it events (live from the feed, or replayed from events.jsonl);
// utils/officeScene.ts draws the result in 3D with three.js.
import { KNOWN_AGENTS, WALK_MS, BUBBLE_MS, initialState, reduce, tick } from '~/utils/officeState'
import type { OfficeEvent, OfficeState } from '~/utils/officeState'
import type { OfficeScene } from '~/utils/officeScene'

const props = defineProps<{
  taskId: string | null // null: no task open, an empty office
  events: OfficeEvent[] // the live feed (past events first, then new ones)
  finished: boolean // replay is offered for done / failed / cancelled tasks only
  insetRight: number // px on the right covered by the chat panel
}>()

const apiBase = useRuntimeConfig().public.apiBase as string

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
  if (!props.taskId) return
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

// ---- Drawing (three.js, utils/officeScene.ts) ----
const sceneEl = ref<HTMLDivElement | null>(null)
const sceneError = ref<string | null>(null)
// Not reactive: three.js objects must not be wrapped in Vue proxies.
let scene: OfficeScene | null = null
let frame = 0
let lastFrameMs = 0
let unmounted = false

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
  scene?.draw(state, frameMs)
  frame = requestAnimationFrame(loop)
}

onMounted(async () => {
  feedLive()
  // Loaded here so three.js only runs in the browser (never during SSR).
  const { createOfficeScene } = await import('~/utils/officeScene')
  if (unmounted || !sceneEl.value) return
  try {
    scene = createOfficeScene(sceneEl.value)
    scene.setInsetRight(props.insetRight)
  } catch (err) {
    sceneError.value = `3D view unavailable (WebGL): ${(err as Error)?.message ?? err}`
    return
  }
  frame = requestAnimationFrame(loop)
})

watch(() => props.insetRight, px => scene?.setInsetRight(px))

onBeforeUnmount(() => {
  unmounted = true
  cancelAnimationFrame(frame)
  scene?.dispose()
  scene = null
})
</script>

<template>
  <div class="office">
    <div ref="sceneEl" class="office-scene">
      <p v-if="sceneError" class="scene-error">{{ sceneError }}</p>
    </div>
    <div class="office-bar">
      <template v-if="mode === 'live'">
        <span class="pill"><span class="live-dot" />live</span>
        <button
          v-if="taskId"
          :disabled="!finished || loading"
          :title="finished ? 'Replay events.jsonl' : 'Replay is available once the task has finished'"
          @click="startReplay"
        >
          {{ loading ? 'Loading…' : 'Replay' }}
        </button>
      </template>
      <template v-else>
        <span class="pill">replay {{ replayPos }}/{{ replayEvents.length }}</span>
        <button @click="togglePlay">{{ replayFinished ? 'Restart' : playing ? 'Pause' : 'Play' }}</button>
        <button :class="{ active: speed === 1 }" @click="speed = 1">1×</button>
        <button :class="{ active: speed === 4 }" @click="speed = 4">4×</button>
        <button @click="mode = 'live'">Back to live</button>
      </template>
      <span v-if="replayError" class="pill error">{{ replayError }}</span>
      <button
        v-if="!sceneError"
        title="Drag to rotate, scroll or pinch to zoom, right-drag or two fingers to pan"
        @click="scene?.resetView()"
      >
        Reset view
      </button>
    </div>
    <div class="office-legend">
      <span v-for="name in KNOWN_AGENTS" :key="name" class="agent-tag" :class="`a-${name}`">{{ name }}</span>
      <span class="agent-tag a-other">other</span>
    </div>
  </div>
</template>

<style scoped>
.office {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: hidden;
  border-radius: 16px;
  background:
    radial-gradient(ellipse at 40% 30%, #1d2236 0%, #11131d 60%, #0b0c12 100%);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.06);
}
.office-scene { position: absolute; inset: 0; cursor: grab; }
.office-scene:active { cursor: grabbing; }
.office-bar, .office-legend {
  position: absolute;
  left: 14px;
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
}
.office-bar { top: 14px; }
.office-legend { bottom: 14px; }
.pill, .office-bar button {
  font: inherit;
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(20, 22, 32, 0.75);
  color: #d6dae6;
  backdrop-filter: blur(8px);
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.office-bar button { cursor: pointer; }
.office-bar button:hover:not(:disabled) { border-color: rgba(255, 255, 255, 0.25); }
.office-bar button:disabled { color: #6b7086; cursor: not-allowed; }
.office-bar button.active { background: rgba(107, 156, 255, 0.25); border-color: #6b9cff; }
.live-dot { width: 7px; height: 7px; border-radius: 50%; background: #3fdc6a; box-shadow: 0 0 6px #3fdc6a; }
.pill.error { color: #ff9a8a; }
.scene-error { color: #ffb4a8; padding: 60px 16px; margin: 0; font-size: 13px; }
</style>

<style>
/* Elements created by utils/officeScene.ts (not scoped: they are made in JS). */
.office3d-canvas { position: absolute; inset: 0; width: 100%; height: 100%; display: block; }
.office3d-labels { position: absolute; inset: 0; pointer-events: none; overflow: hidden; }
.office3d-label {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
.office3d-tag {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px 2px 6px;
  border-radius: 999px;
  background: rgba(22, 20, 38, 0.82);
  color: #f1f3f8;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.3);
}
.office3d-dot { width: 7px; height: 7px; border-radius: 50%; box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.25); }
.office3d-status { font-weight: 400; color: #a9adc6; }
.office3d-tag[data-status="working"] .office3d-status { color: #7ee2a8; }
.office3d-tag[data-status="talking"] .office3d-status { color: #79c0ff; }
.office3d-tag[data-status="walking"] .office3d-status { color: #f2cc60; }
.office3d-bubble {
  position: relative;
  max-width: 220px;
  padding: 5px 10px;
  border-radius: 10px;
  background: #ffffff;
  color: #1f2328;
  font-size: 12px;
  line-height: 1.3;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}
.office3d-bubble::after {
  content: "";
  position: absolute;
  left: 50%;
  bottom: -5px;
  width: 10px;
  height: 10px;
  background: #ffffff;
  transform: translateX(-50%) rotate(45deg);
}
.office3d-bubble[hidden] { display: none; }
.office3d-alert {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: #cf222e;
  color: #fff;
  font: 700 15px/22px -apple-system, BlinkMacSystemFont, sans-serif;
  text-align: center;
  box-shadow: 0 0 0 3px rgba(255, 255, 255, 0.85), 0 2px 8px rgba(0, 0, 0, 0.4);
}
</style>
