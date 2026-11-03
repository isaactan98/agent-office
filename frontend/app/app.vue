<script setup lang="ts">
// Single page: task input, live event feed, task list, file viewer, usage.
// Data is loaded in the browser only (onMounted), never during SSR.

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

watch(() => feed.value.length, async () => {
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
  clearInterval(pollTimer)
  closeSocket()
})
</script>

<template>
  <div class="layout">
    <aside class="sidebar">
      <h1>agent-office</h1>
      <section v-if="usage" class="usage">
        <h2>Usage</h2>
        <p :class="{ error: usage.tasks_created_today >= usage.daily_task_cap }">
          Tasks today: {{ usage.tasks_created_today }} / {{ usage.daily_task_cap }}
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

    <main class="main">
      <form class="chat" @submit.prevent="send">
        <textarea
          v-model="input"
          rows="3"
          placeholder="Describe a task…"
          :disabled="sending"
          @keydown.enter.meta.prevent="send"
        />
        <div class="chat-row">
          <button type="submit" :disabled="sending || !input.trim()">
            {{ runningTask ? 'Queue' : 'Send' }}
          </button>
          <span v-if="runningTask" class="muted">
            A task is running<template v-if="queuedCount">, {{ queuedCount }} queued</template>.
            New tasks wait in the queue.
          </span>
          <span v-if="sendError" class="error">{{ sendError }}</span>
        </div>
      </form>

      <section v-if="selectedId" class="task">
        <header class="task-header">
          <strong>{{ selectedId }}</strong>
          <span v-if="selectedTask" class="badge" :class="`s-${selectedTask.status}`">
            {{ selectedTask.status }}
          </span>
          <span class="muted">feed: {{ connection }}</span>
          <button
            v-if="selectedTask && (selectedTask.status === 'queued' || selectedTask.status === 'running')"
            class="cancel"
            :disabled="cancelling"
            @click="cancelTask(selectedTask.task_id)"
          >
            {{ cancelling ? 'Cancelling…' : 'Cancel' }}
          </button>
        </header>
        <p v-if="cancelError" class="error">{{ cancelError }}</p>
        <p v-if="selectedTask" class="task-prompt">{{ selectedTask.text }}</p>
        <p v-if="selectedTask?.error" class="error">{{ selectedTask.error }}</p>

        <Office
          :key="selectedId"
          :task-id="selectedId"
          :events="feed"
          :finished="['done', 'failed', 'cancelled'].includes(selectedTask?.status ?? '')"
        />

        <div class="legend">
          <span v-for="name in AGENTS" :key="name" class="agent-tag" :class="`a-${name}`">{{ name }}</span>
          <span class="agent-tag a-other">other</span>
        </div>
        <div ref="feedEl" class="feed" @scroll="onFeedScroll">
          <p v-if="feed.length === 0" class="muted">No events yet.</p>
          <div
            v-for="(event, index) in feed"
            :key="event.seq ?? `i${index}`"
            class="row"
            :class="eventClass(event)"
          >
            <span class="time">{{ eventTime(event) }}</span>
            <span class="agent"><span class="agent-tag" :class="agentClass(event)">{{ event.agent ?? '?' }}</span></span>
            <span class="type">{{ event.type ?? '?' }}</span>
            <span class="summary">{{ eventSummary(event) }}</span>
          </div>
        </div>

        <div class="files">
          <div class="file-list">
            <h2>Files</h2>
            <p v-if="files.length === 0" class="muted">No files.</p>
            <ul>
              <li v-for="file in files" :key="file.path">
                <button
                  class="link"
                  :class="{ selected: openFile?.path === file.path }"
                  @click="showFile(file.path)"
                >
                  {{ file.path }}
                </button>
                <span class="muted">{{ formatSize(file.size) }}</span>
              </li>
            </ul>
          </div>
          <div v-if="openFile" class="file-view">
            <h2>{{ openFile.path }}</h2>
            <p v-if="openFile.error" class="error">{{ openFile.error }}</p>
            <p v-else-if="openFile.content === null" class="muted">Loading…</p>
            <pre v-else>{{ openFile.content }}</pre>
          </div>
        </div>
      </section>
      <p v-else class="muted">Pick a task on the left, or send a new one.</p>
    </main>
  </div>
</template>

<style>
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 14px;
  color: #1f2328;
  background: #f6f8fa;
}
h1 { font-size: 18px; margin: 0 0 12px; }
h2 { font-size: 14px; margin: 0 0 8px; }
.muted { color: #6e7781; }
.error { color: #cf222e; }

.layout { display: flex; min-height: 100vh; }
.sidebar {
  width: 280px;
  flex-shrink: 0;
  padding: 16px;
  border-right: 1px solid #d0d7de;
  background: #fff;
  overflow-y: auto;
  max-height: 100vh;
  position: sticky;
  top: 0;
}
.task-list { list-style: none; margin: 0; padding: 0; }
.task-list li {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 8px;
  align-items: center;
  padding: 8px;
  border-radius: 6px;
  cursor: pointer;
}
.task-list li:hover { background: #f3f4f6; }
.task-list li.selected { background: #ddf4ff; }
.task-text { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-id { width: 100%; font-size: 11px; color: #6e7781; font-family: ui-monospace, monospace; }

.badge {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 10px;
  background: #eaeef2;
  color: #57606a;
}
.s-running, .s-queued { background: #fff8c5; color: #7d4e00; }
.s-done { background: #dafbe1; color: #116329; }
.s-failed, .s-cancelled { background: #ffebe9; color: #a40e26; }

.main { flex: 1; min-width: 0; padding: 16px; display: flex; flex-direction: column; gap: 16px; }
.chat textarea {
  width: 100%;
  font: inherit;
  padding: 8px;
  border: 1px solid #d0d7de;
  border-radius: 6px;
  resize: vertical;
}
.chat-row { display: flex; gap: 12px; align-items: center; margin-top: 8px; flex-wrap: wrap; }
.chat button {
  font: inherit;
  padding: 6px 16px;
  border: 1px solid #1f883d;
  border-radius: 6px;
  background: #1f883d;
  color: #fff;
  cursor: pointer;
}
.chat button:disabled { background: #94d3a2; border-color: #94d3a2; cursor: not-allowed; }

.task-header { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; font-family: ui-monospace, monospace; }
.task-header strong { word-break: break-all; }
.cancel {
  font: inherit;
  padding: 2px 10px;
  border: 1px solid #cf222e;
  border-radius: 6px;
  background: #fff;
  color: #cf222e;
  cursor: pointer;
}
.cancel:disabled { opacity: 0.6; cursor: not-allowed; }

.usage { margin-bottom: 16px; font-size: 12px; }
.usage p { margin: 0 0 6px; }
.usage table { border-collapse: collapse; width: 100%; }
.usage th, .usage td { text-align: right; padding: 1px 4px; font-variant-numeric: tabular-nums; }
.usage th:first-child, .usage td:first-child { text-align: left; color: #6e7781; }
.small { font-size: 11px; }
.task-prompt { margin: 8px 0; }

.feed {
  height: 45vh;
  overflow-y: auto;
  background: #fff;
  border: 1px solid #d0d7de;
  border-radius: 6px;
  font-family: ui-monospace, monospace;
  font-size: 12px;
}
.feed > .muted { padding: 8px; margin: 0; }
.row {
  display: grid;
  grid-template-columns: 64px 100px 110px 1fr;
  gap: 8px;
  padding: 3px 8px;
  border-left: 3px solid #d0d7de;
}
.row .summary { white-space: pre-wrap; word-break: break-word; }
.row .type { font-weight: 600; }
.t-task_queued, .t-task_started { border-left-color: #0969da; background: #f0f7ff; }
.t-agent_message { border-left-color: #8250df; }
.t-tool_start { border-left-color: #bf8700; }
.t-tool_end { border-left-color: #9a6700; color: #57606a; }
.t-tool_denied { border-left-color: #cf222e; background: #fff5f5; }
.t-subagent_start, .t-subagent_stop { border-left-color: #1b7c83; }
.t-task_done { border-left-color: #1f883d; background: #f0fff4; }
.t-task_failed { border-left-color: #cf222e; background: #ffebe9; }
.t-unknown { border-left-color: #8c959f; color: #57606a; font-style: italic; }

.legend { display: flex; gap: 6px; align-items: center; margin-bottom: 6px; }
.agent-tag {
  display: inline-block;
  font-size: 11px;
  padding: 0 6px;
  border-radius: 4px;
  font-family: ui-monospace, monospace;
  font-style: normal;
}
.a-orchestrator { background: #ddf4ff; color: #0550ae; }
.a-writer { background: #fbefff; color: #8250df; }
.a-reviewer { background: #fff1e5; color: #bc4c00; }
.a-other { background: #eaeef2; color: #57606a; }

.files { display: flex; gap: 16px; align-items: flex-start; }
.file-list { width: 280px; flex-shrink: 0; }
.file-list ul { list-style: none; margin: 0; padding: 0; }
.file-list li { display: flex; justify-content: space-between; gap: 8px; padding: 2px 0; }
.link {
  font: inherit;
  font-family: ui-monospace, monospace;
  font-size: 12px;
  background: none;
  border: none;
  padding: 0;
  color: #0969da;
  cursor: pointer;
  text-align: left;
  word-break: break-all;
}
.link.selected { font-weight: 700; }
.file-view { flex: 1; min-width: 0; }
/* Phone width: sidebar above the main column. */
@media (max-width: 720px) {
  .layout { flex-direction: column; }
  .sidebar { width: auto; max-height: 40vh; position: static; border-right: none; border-bottom: 1px solid #d0d7de; }
  .files { flex-direction: column; }
  .file-list { width: auto; }
  .row { grid-template-columns: 56px 80px 1fr; }
  .row .summary { grid-column: 1 / -1; }
}

.file-view pre {
  margin: 0;
  padding: 12px;
  background: #fff;
  border: 1px solid #d0d7de;
  border-radius: 6px;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  max-height: 60vh;
  overflow: auto;
}
</style>
