<script setup lang="ts">
// Single page: the 3D office fills the screen; the chat panel inside it holds
// the task input, live event feed and file viewer; the sidebar holds the task
// list and usage. Data is loaded in the browser only (onMounted), never during SSR.

interface Task {
  task_id: string
  text: string
  status: string
  created_at: string
  error: string | null
}

// One event (docs/PLAN.md "Event schema"). Typed loosely on purpose:
// unknown types or missing fields must still render as a row.
interface TaskEvent {
  seq?: number
  ts?: string
  agent?: string
  type?: string
  tool?: string | null
  path?: string | null
  summary?: string
  [key: string]: unknown
}

interface TaskFile {
  path: string
  size: number
}

// GET /usage. `usage` holds summed numeric fields of the SDK's raw usage dicts.
interface UsageTotals {
  sessions: number
  duration_ms: number
  num_turns: number
  total_cost_usd: number
  usage: Record<string, number>
}
interface Usage {
  today: UsageTotals
  month: UsageTotals
  daily_task_cap: number
  tasks_created_today: number
}

const KNOWN_TYPES = new Set([
  'task_queued', 'task_started', 'agent_message', 'tool_start', 'tool_end',
  'tool_denied', 'subagent_start', 'subagent_stop', 'task_done', 'task_failed'
])
const TERMINAL_TYPES = new Set(['task_done', 'task_failed'])
// Agents defined in backend/app/agents.py. Any other name gets the grey tag.
const AGENTS = ['orchestrator', 'writer', 'reviewer']

const apiBase = useRuntimeConfig().public.apiBase as string
const wsBase = apiBase.replace(/^http/, 'ws')

useHead({ title: 'agent-office' })

const tasks = ref<Task[]>([])
const selectedId = ref<string | null>(null)
const feed = ref<TaskEvent[]>([])
const connection = ref<'idle' | 'connecting' | 'live' | 'closed' | 'error'>('idle')
const files = ref<TaskFile[]>([])
const openFile = ref<{ path: string, content: string | null, error: string | null } | null>(null)

const input = ref('')
const sending = ref(false)
const sendError = ref<string | null>(null)
const cancelling = ref(false)
const cancelError = ref<string | null>(null)
const usage = ref<Usage | null>(null)

const feedEl = ref<HTMLElement | null>(null)
const tab = ref<'chat' | 'files'>('chat')
const panelCollapsed = ref(false)
const isNarrow = ref(false) // ≤ 900 px: panel goes below the office instead of over it
// Chat panel width + its right margin + a gap; the office frames the room in
// the space left of it.
const PANEL_INSET = 400 + 16 + 16
const panelInset = computed(() => (isNarrow.value || panelCollapsed.value ? 0 : PANEL_INSET))
let narrowQuery: MediaQueryList | null = null
function onNarrowChange(e: MediaQueryListEvent) {
  isNarrow.value = e.matches
}
let stickToBottom = true
let socket: WebSocket | null = null
let seenSeq = new Set<number>()
let pollTimer: ReturnType<typeof setInterval> | undefined

const runningTask = computed(() =>
  tasks.value.find(t => t.status === 'running' || t.status === 'queued') ?? null
)
const queuedCount = computed(() => tasks.value.filter(t => t.status === 'queued').length)
const selectedTask = computed(() =>
  tasks.value.find(t => t.task_id === selectedId.value) ?? null
)

function errorText(err: unknown): string {
  const e = err as { statusCode?: number, data?: { detail?: unknown }, message?: string }
  const detail = typeof e?.data?.detail === 'string' ? e.data.detail : e?.message ?? String(err)
  return e?.statusCode ? `${e.statusCode}: ${detail}` : detail
}

async function refreshTasks() {
  try {
    tasks.value = await $fetch<Task[]>(`${apiBase}/tasks`)
  } catch (err) {
    console.error('could not load tasks', err)
  }
}

async function refreshUsage() {
  try {
    usage.value = await $fetch<Usage>(`${apiBase}/usage`)
  } catch (err) {
    console.error('could not load usage', err)
  }
}

async function loadFiles(taskId: string) {
  try {
    const list = await $fetch<TaskFile[]>(`${apiBase}/tasks/${taskId}/files`)
    if (selectedId.value === taskId) files.value = list
  } catch (err) {
    console.error('could not load files', err)
  }
}

async function showFile(path: string) {
  const taskId = selectedId.value
  if (!taskId) return
  openFile.value = { path, content: null, error: null }
  const encoded = path.split('/').map(encodeURIComponent).join('/')
  try {
    const content = await $fetch<string>(`${apiBase}/tasks/${taskId}/files/${encoded}`, {
      responseType: 'text'
    })
    if (openFile.value?.path === path) openFile.value.content = content
  } catch (err) {
    if (openFile.value?.path === path) openFile.value.error = errorText(err)
  }
}

function closeSocket() {
  if (socket) {
    const old = socket
    socket = null // handlers below ignore events from a socket that is not current
    old.close()
  }
}

// Open the task's WebSocket. The server sends every past event first, then
// live ones, and closes after task_done / task_failed.
function connect(taskId: string) {
  closeSocket()
  connection.value = 'connecting'
  const ws = new WebSocket(`${wsBase}/ws/tasks/${taskId}`)
  socket = ws
  ws.onopen = () => {
    if (socket === ws) connection.value = 'live'
  }
  ws.onmessage = (message) => {
    if (socket !== ws) return
    let event: TaskEvent
    try {
      event = JSON.parse(message.data)
    } catch {
      return
    }
    if (typeof event !== 'object' || event === null) return
    if (typeof event.seq === 'number') {
      if (seenSeq.has(event.seq)) return
      seenSeq.add(event.seq)
    }
    feed.value.push(event)
    if (event.type && TERMINAL_TYPES.has(event.type)) {
      refreshTasks()
      refreshUsage()
      loadFiles(taskId)
    } else if (event.type === 'tool_end') {
      loadFiles(taskId) // a tool may have written a file
    }
  }
  ws.onerror = () => {
    if (socket === ws) connection.value = 'error'
  }
  ws.onclose = () => {
    if (socket !== ws) return
    socket = null
    if (connection.value !== 'error') connection.value = 'closed'
    refreshTasks()
  }
}

function selectTask(taskId: string) {
  selectedId.value = taskId
  feed.value = []
  seenSeq = new Set()
  stickToBottom = true
  files.value = []
  openFile.value = null
  cancelError.value = null
  // Keep the open task in the URL so a reload comes back to it.
  const url = new URL(window.location.href)
  url.searchParams.set('task', taskId)
  window.history.replaceState(null, '', url)
  connect(taskId)
  loadFiles(taskId)
}

async function send() {
  const text = input.value.trim()
  if (!text || sending.value) return
  sending.value = true
  sendError.value = null
  try {
    const created = await $fetch<{ task_id: string }>(`${apiBase}/tasks`, {
      method: 'POST',
      body: { text }
    })
    input.value = ''
    await refreshTasks()
    refreshUsage()
    selectTask(created.task_id)
  } catch (err) {
    sendError.value = errorText(err) // e.g. "429: daily task cap reached …"
    refreshTasks()
  } finally {
    sending.value = false
  }
}

// Cancel a queued or running task. The backend answers once it is cancelled.
async function cancelTask(taskId: string) {
  if (cancelling.value) return
  cancelling.value = true
  cancelError.value = null
  try {
    await $fetch(`${apiBase}/tasks/${taskId}/cancel`, { method: 'POST' })
  } catch (err) {
    cancelError.value = errorText(err)
  } finally {
    cancelling.value = false
    refreshTasks()
    refreshUsage()
  }
}

function onFeedScroll() {
  const el = feedEl.value
  if (el) stickToBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40
}

watch([() => feed.value.length, tab, panelCollapsed], async () => {
  await nextTick()
  if (stickToBottom && feedEl.value) feedEl.value.scrollTop = feedEl.value.scrollHeight
})

function eventTime(event: TaskEvent): string {
  // ts is ISO 8601 with offset, e.g. 2026-11-03T21:14:05.123+08:00
  return typeof event.ts === 'string' ? event.ts.slice(11, 19) : ''
}

function eventClass(event: TaskEvent): string {
  return typeof event.type === 'string' && KNOWN_TYPES.has(event.type) ? `t-${event.type}` : 't-unknown'
}

function agentClass(event: TaskEvent): string {
  return typeof event.agent === 'string' && AGENTS.includes(event.agent) ? `a-${event.agent}` : 'a-other'
}

function eventSummary(event: TaskEvent): string {
  return typeof event.summary === 'string' ? event.summary : JSON.stringify(event)
}

function formatSize(bytes: number): string {
  return bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB`
}

function formatDuration(ms: number): string {
  const minutes = Math.floor(ms / 60000)
  const seconds = Math.round((ms % 60000) / 1000)
  return minutes ? `${minutes}m ${seconds}s` : `${seconds}s`
}

// Token fields of the SDK's usage dict (e.g. input_tokens). The month includes today.
function tokenKeys(totals: UsageTotals): string[] {
  return Object.keys(totals.usage).filter(key => key.endsWith('_tokens'))
}

function tokenLabel(key: string): string {
  return key.replace(/_tokens$/, '').replace(/_/g, ' ') // cache_read_input_tokens -> "cache read input"
}

onMounted(async () => {
  narrowQuery = window.matchMedia('(max-width: 900px)')
  isNarrow.value = narrowQuery.matches
  narrowQuery.addEventListener('change', onNarrowChange)
  await refreshTasks()
  refreshUsage()
  const fromUrl = new URLSearchParams(window.location.search).get('task')
  const initial = fromUrl ?? runningTask.value?.task_id
  if (initial) selectTask(initial)
  // While a task runs, keep the task list (and the Send button) up to date.
  pollTimer = setInterval(() => {
    if (runningTask.value) refreshTasks()
  }, 3000)
})

onBeforeUnmount(() => {
  narrowQuery?.removeEventListener('change', onNarrowChange)
  clearInterval(pollTimer)
  closeSocket()
})
</script>

<template>
  <div class="layout">
    <aside class="sidebar">
      <div class="brand">
        <span class="logo" aria-hidden="true"><i /><i /></span>
        <div>
          <h1>agent-office</h1>
          <p class="muted small">orchestrator + subagents</p>
        </div>
      </div>

      <section v-if="usage" class="card usage">
        <h2>Usage</h2>
        <p :class="{ error: usage.tasks_created_today >= usage.daily_task_cap }">
          Tasks today: <strong>{{ usage.tasks_created_today }}</strong> / {{ usage.daily_task_cap }}
        </p>
        <table>
          <thead>
            <tr><th /><th>today</th><th>month</th></tr>
          </thead>
          <tbody>
            <tr><td>sessions</td><td>{{ usage.today.sessions }}</td><td>{{ usage.month.sessions }}</td></tr>
            <tr><td>turns</td><td>{{ usage.today.num_turns }}</td><td>{{ usage.month.num_turns }}</td></tr>
            <tr>
              <td>time</td>
              <td>{{ formatDuration(usage.today.duration_ms) }}</td>
              <td>{{ formatDuration(usage.month.duration_ms) }}</td>
            </tr>
            <tr v-for="key in tokenKeys(usage.month)" :key="key">
              <td>{{ tokenLabel(key) }}</td>
              <td>{{ (usage.today.usage[key] ?? 0).toLocaleString() }}</td>
              <td>{{ (usage.month.usage[key] ?? 0).toLocaleString() }}</td>
            </tr>
            <tr>
              <td>est. $</td>
              <td>{{ usage.today.total_cost_usd.toFixed(2) }}</td>
              <td>{{ usage.month.total_cost_usd.toFixed(2) }}</td>
            </tr>
          </tbody>
        </table>
        <p class="muted small">est. $ = the SDK's list-price estimate, not a bill (Pro plan).</p>
      </section>

      <h2 class="section-title">Tasks</h2>
      <p v-if="tasks.length === 0" class="muted">No tasks yet.</p>
      <ul class="task-list">
        <li
          v-for="task in tasks"
          :key="task.task_id"
          :class="{ selected: task.task_id === selectedId }"
          @click="selectTask(task.task_id)"
        >
          <span class="badge" :class="`s-${task.status}`">{{ task.status }}</span>
          <span class="task-text">{{ task.text }}</span>
          <span class="task-id">{{ task.task_id }}</span>
        </li>
      </ul>
    </aside>

    <main class="stage">
      <Office
        :key="selectedId ?? 'none'"
        :task-id="selectedId"
        :events="feed"
        :finished="['done', 'failed', 'cancelled'].includes(selectedTask?.status ?? '')"
        :inset-right="panelInset"
      />

      <button v-if="panelCollapsed && !isNarrow" class="panel-open" @click="panelCollapsed = false">
        ‹ Chat
      </button>

      <section v-show="!panelCollapsed || isNarrow" class="panel">
        <header class="panel-head">
          <div class="tabs">
            <button :class="{ active: tab === 'chat' }" @click="tab = 'chat'">Chat</button>
            <button :class="{ active: tab === 'files' }" :disabled="!selectedId" @click="tab = 'files'">
              Files<span v-if="files.length" class="count">{{ files.length }}</span>
            </button>
          </div>
          <button v-if="!isNarrow" class="icon" title="Hide panel" @click="panelCollapsed = true">›</button>
        </header>

        <div v-if="selectedId" class="task-head">
          <div class="task-head-row">
            <span v-if="selectedTask" class="badge" :class="`s-${selectedTask.status}`">{{ selectedTask.status }}</span>
            <span class="muted small mono">feed: {{ connection }}</span>
            <button
              v-if="selectedTask && (selectedTask.status === 'queued' || selectedTask.status === 'running')"
              class="cancel"
              :disabled="cancelling"
              @click="cancelTask(selectedTask.task_id)"
            >
              {{ cancelling ? 'Cancelling…' : 'Cancel' }}
            </button>
          </div>
          <p v-if="selectedTask" class="task-prompt">{{ selectedTask.text }}</p>
          <p class="task-id">{{ selectedId }}</p>
          <p v-if="cancelError" class="error small">{{ cancelError }}</p>
          <p v-if="selectedTask?.error" class="error small">{{ selectedTask.error }}</p>
        </div>

        <div v-show="tab === 'chat'" ref="feedEl" class="feed" @scroll="onFeedScroll">
          <p v-if="!selectedId" class="muted empty">Pick a task on the left, or describe a new one below.</p>
          <p v-else-if="feed.length === 0" class="muted empty">No events yet.</p>
          <div
            v-for="(event, index) in feed"
            :key="event.seq ?? `i${index}`"
            class="row"
            :class="eventClass(event)"
          >
            <div class="row-head">
              <span class="agent-tag" :class="agentClass(event)">{{ event.agent ?? '?' }}</span>
              <span class="type">{{ event.type ?? '?' }}</span>
              <span class="time">{{ eventTime(event) }}</span>
            </div>
            <div class="summary">{{ eventSummary(event) }}</div>
          </div>
        </div>

        <div v-show="tab === 'files'" class="files">
          <p v-if="files.length === 0" class="muted empty">No files.</p>
          <ul class="file-list">
            <li v-for="file in files" :key="file.path">
              <button class="link" :class="{ selected: openFile?.path === file.path }" @click="showFile(file.path)">
                {{ file.path }}
              </button>
              <span class="muted small">{{ formatSize(file.size) }}</span>
            </li>
          </ul>
          <div v-if="openFile" class="file-view">
            <h2>{{ openFile.path }}</h2>
            <p v-if="openFile.error" class="error">{{ openFile.error }}</p>
            <p v-else-if="openFile.content === null" class="muted">Loading…</p>
            <pre v-else>{{ openFile.content }}</pre>
          </div>
        </div>

        <form class="composer" @submit.prevent="send">
          <textarea
            v-model="input"
            rows="2"
            placeholder="Describe a task…  (⌘↵ to send)"
            :disabled="sending"
            @keydown.enter.meta.prevent="send"
          />
          <div class="composer-row">
            <span v-if="sendError" class="error small">{{ sendError }}</span>
            <span v-else-if="runningTask" class="muted small">
              A task is running<template v-if="queuedCount">, {{ queuedCount }} queued</template>. New tasks wait in the queue.
            </span>
            <span v-else class="muted small">One task runs at a time.</span>
            <button type="submit" :disabled="sending || !input.trim()">
              {{ runningTask ? 'Queue' : 'Send' }}
            </button>
          </div>
        </form>
      </section>
    </main>
  </div>
</template>

<style>
* { box-sizing: border-box; }
:root {
  --bg: #0b0c12;
  --surface: #12141c;
  --surface-2: #181b25;
  --border: rgba(255, 255, 255, 0.08);
  --text: #e4e7ef;
  --muted: #8a90a6;
  --accent: #6b9cff;
  --green: #3fdc6a;
  --red: #ff7b72;
}
html, body { height: 100%; }
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 14px;
  color: var(--text);
  background: var(--bg);
}
h1 { font-size: 16px; margin: 0; letter-spacing: 0.01em; }
h2 { font-size: 13px; margin: 0 0 8px; }
.muted { color: var(--muted); }
.error { color: var(--red); }
.small { font-size: 12px; }
.mono { font-family: ui-monospace, monospace; }

.layout { display: flex; height: 100vh; }

/* ---- Sidebar ---- */
.sidebar {
  width: 280px;
  flex-shrink: 0;
  padding: 18px 14px;
  background: var(--surface);
  border-right: 1px solid var(--border);
  overflow-y: auto;
}
.brand { display: flex; gap: 10px; align-items: center; margin-bottom: 18px; }
.brand p { margin: 2px 0 0; }
.logo {
  width: 34px;
  height: 30px;
  border-radius: 9px;
  background: linear-gradient(145deg, #8fb4ff, #5b7fe0);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  box-shadow: 0 4px 14px rgba(107, 156, 255, 0.35);
}
.logo i { width: 5px; height: 8px; border-radius: 1px; background: #0f1220; }
.card {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 12px;
}
.usage { margin-bottom: 18px; font-size: 12px; }
.usage p { margin: 0 0 6px; }
.usage table { border-collapse: collapse; width: 100%; }
.usage th { color: var(--muted); font-weight: 500; }
.usage th, .usage td { text-align: right; padding: 1px 4px; font-variant-numeric: tabular-nums; }
.usage th:first-child, .usage td:first-child { text-align: left; color: var(--muted); }
.section-title { text-transform: uppercase; font-size: 11px; letter-spacing: 0.08em; color: var(--muted); margin: 0 4px 6px; }
.task-list { list-style: none; margin: 0; padding: 0; }
.task-list li {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 8px;
  align-items: center;
  padding: 8px 10px;
  border-radius: 10px;
  cursor: pointer;
  border: 1px solid transparent;
}
.task-list li:hover { background: rgba(255, 255, 255, 0.04); }
.task-list li.selected { background: rgba(107, 156, 255, 0.12); border-color: rgba(107, 156, 255, 0.35); }
.task-text { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-id { width: 100%; font-size: 11px; color: var(--muted); font-family: ui-monospace, monospace; word-break: break-all; margin: 0; }

.badge {
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.08);
  color: #b7bcce;
}
.s-running, .s-queued { background: rgba(242, 204, 96, 0.15); color: #f2cc60; }
.s-done { background: rgba(63, 220, 106, 0.14); color: #6fe08f; }
.s-failed, .s-cancelled { background: rgba(255, 123, 114, 0.14); color: #ff9a92; }

/* ---- Stage: the office fills it; the panel floats inside on the right ---- */
.stage { position: relative; flex: 1; min-width: 0; padding: 12px; }
.panel {
  position: absolute;
  top: 28px;
  right: 28px;
  bottom: 28px;
  width: 400px;
  display: flex;
  flex-direction: column;
  background: rgba(16, 18, 27, 0.82);
  border: 1px solid var(--border);
  border-radius: 14px;
  backdrop-filter: blur(14px);
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.45);
  overflow: hidden;
}
.panel-open {
  position: absolute;
  top: 28px;
  right: 28px;
  font: inherit;
  font-size: 13px;
  padding: 6px 14px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: rgba(16, 18, 27, 0.85);
  color: var(--text);
  cursor: pointer;
  backdrop-filter: blur(10px);
}
.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 10px 0;
}
.tabs { display: flex; gap: 4px; }
.tabs button, .icon {
  font: inherit;
  font-size: 13px;
  padding: 5px 12px;
  border-radius: 8px;
  border: none;
  background: none;
  color: var(--muted);
  cursor: pointer;
}
.tabs button.active { background: rgba(255, 255, 255, 0.08); color: var(--text); }
.tabs button:disabled { opacity: 0.4; cursor: not-allowed; }
.icon { font-size: 18px; line-height: 1; padding: 4px 10px; }
.icon:hover, .tabs button:hover:not(:disabled) { color: var(--text); }
.count {
  margin-left: 6px;
  font-size: 10px;
  padding: 0 6px;
  border-radius: 8px;
  background: rgba(107, 156, 255, 0.2);
  color: #9bbcff;
}
.task-head { padding: 10px 14px; border-bottom: 1px solid var(--border); }
.task-head p { margin: 4px 0 0; }
.task-head-row { display: flex; gap: 10px; align-items: center; }
.task-prompt { font-size: 13px; line-height: 1.4; }
.cancel {
  margin-left: auto;
  font: inherit;
  font-size: 12px;
  padding: 2px 10px;
  border: 1px solid rgba(255, 123, 114, 0.5);
  border-radius: 8px;
  background: none;
  color: var(--red);
  cursor: pointer;
}
.cancel:disabled { opacity: 0.6; cursor: not-allowed; }

.feed, .files { flex: 1; min-height: 0; overflow-y: auto; padding: 8px 10px; }
.empty { padding: 8px 4px; margin: 0; }
.row {
  padding: 6px 8px;
  margin-bottom: 4px;
  border-radius: 8px;
  border-left: 2px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.025);
}
.row-head { display: flex; gap: 8px; align-items: center; font-size: 11px; }
.row .type { font-family: ui-monospace, monospace; font-weight: 600; color: #c5cadb; }
.row .time { margin-left: auto; font-family: ui-monospace, monospace; color: var(--muted); }
.row .summary { margin-top: 3px; font-size: 12px; line-height: 1.4; white-space: pre-wrap; word-break: break-word; color: #cfd3df; }
.t-task_queued, .t-task_started { border-left-color: #6b9cff; }
.t-agent_message { border-left-color: #b18cff; background: rgba(177, 140, 255, 0.06); }
.t-tool_start { border-left-color: #d6a23a; }
.t-tool_end { border-left-color: #8a6d2c; }
.t-tool_end .summary { color: var(--muted); }
.t-tool_denied { border-left-color: var(--red); background: rgba(255, 123, 114, 0.08); }
.t-subagent_start, .t-subagent_stop { border-left-color: #39c5cf; }
.t-task_done { border-left-color: var(--green); background: rgba(63, 220, 106, 0.07); }
.t-task_failed { border-left-color: var(--red); background: rgba(255, 123, 114, 0.1); }
.t-unknown { border-left-color: #6b7086; font-style: italic; }
.t-unknown .summary { color: var(--muted); }

.agent-tag {
  display: inline-block;
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 6px;
  font-family: ui-monospace, monospace;
  font-style: normal;
}
/* Same hues as the robots in the office. */
.a-orchestrator { background: rgba(107, 156, 255, 0.18); color: #9bbcff; }
.a-writer { background: rgba(177, 140, 255, 0.18); color: #c9b0ff; }
.a-reviewer { background: rgba(255, 154, 92, 0.18); color: #ffb488; }
.a-other { background: rgba(227, 231, 238, 0.12); color: #d0d5de; }

.file-list { list-style: none; margin: 0 0 10px; padding: 0; }
.file-list li { display: flex; justify-content: space-between; gap: 8px; padding: 4px; border-radius: 6px; }
.file-list li:hover { background: rgba(255, 255, 255, 0.04); }
.link {
  font: inherit;
  font-family: ui-monospace, monospace;
  font-size: 12px;
  background: none;
  border: none;
  padding: 0;
  color: #9bbcff;
  cursor: pointer;
  text-align: left;
  word-break: break-all;
}
.link.selected { font-weight: 700; color: #c4d7ff; }
.file-view h2 { font-family: ui-monospace, monospace; font-size: 12px; color: var(--muted); }
.file-view pre {
  margin: 0;
  padding: 12px;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid var(--border);
  border-radius: 8px;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.5;
  color: #d8dce6;
}

.composer { padding: 10px; border-top: 1px solid var(--border); background: rgba(0, 0, 0, 0.15); }
.composer textarea {
  width: 100%;
  font: inherit;
  padding: 10px 12px;
  color: var(--text);
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--border);
  border-radius: 10px;
  resize: none;
  outline: none;
}
.composer textarea:focus { border-color: rgba(107, 156, 255, 0.6); }
.composer textarea::placeholder { color: #6b7086; }
.composer-row { display: flex; gap: 10px; align-items: center; justify-content: space-between; margin-top: 8px; }
.composer button {
  font: inherit;
  font-weight: 600;
  padding: 6px 18px;
  border: none;
  border-radius: 9px;
  background: linear-gradient(145deg, #7aa7ff, #5a82e6);
  color: #0d1020;
  cursor: pointer;
  flex-shrink: 0;
}
.composer button:disabled { opacity: 0.4; cursor: not-allowed; }

/* Narrow screens: sidebar on top, office, then the panel below it. */
@media (max-width: 900px) {
  .layout { flex-direction: column; height: auto; min-height: 100vh; }
  .sidebar { width: auto; max-height: 38vh; border-right: none; border-bottom: 1px solid var(--border); }
  .stage { padding: 10px; display: flex; flex-direction: column; gap: 10px; }
  .stage > .office { height: auto; aspect-ratio: 4 / 3; }
  .panel { position: static; width: auto; height: 70vh; }
}
</style>
