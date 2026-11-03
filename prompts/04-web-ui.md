## Session Strategy
New session. Read `CLAUDE.md` and `docs/PLAN.md` first.

## Objective
First usable website: type a task, watch a live text feed of what the agent does,
browse finished tasks and their output files. No graphics yet.

## Context
Backend: `POST/GET /tasks`, `GET /tasks/{id}/events`, in-memory pub/sub per task.
Frontend: default Nuxt starter.

## Target State
Backend:
- `WS /ws/tasks/{task_id}`: on connect, send all past events from `events.jsonl`,
  then stream new ones from pub/sub until `task_done`/`task_failed`.
- `GET /tasks/{task_id}/files` → list of files under the task dir (relative paths, sizes)
- `GET /tasks/{task_id}/files/{path}` → file content as text, only for text files under
  1 MB, path-guarded to the task dir.
- CORS for the Nuxt dev origin only.

Frontend (single page is fine):
- Chat box + Send → `POST /tasks`; disabled while a task is running (show the 409 reason)
- Live feed: one row per event — time, agent, type, summary; auto-scroll; colour by type
- Sidebar: task list (status badge) → click to open: replay events, file list, view a
  file (plain `<pre>`, no markdown rendering libraries)
- Backend base URL from runtime config, default `http://127.0.0.1:8000`

## Scope
- Work only in: `backend/app/`, `backend/tests/`, `frontend/`.
- Do NOT touch: `docs/`, `backend/spikes/`.

## Constraints
- No UI component libraries and no new frontend dependencies unless you ask first.
  Plain Vue + CSS.
- Unknown event types must render as a generic row, not crash.
- Only make changes directly requested.

## Acceptance Criteria
- [ ] Submitting "Write output/plan.md listing 5 Skudai cafes for a Sunday drive
      (fictional names are fine)" shows events streaming live in the browser
- [ ] Reloading the page mid-task reconnects and shows full history
- [ ] Finished task is in the sidebar; its files open and display
- [ ] Requesting `/tasks/{id}/files/../../CLAUDE.md` is rejected
- [ ] Backend tests pass

## Action Boundaries
- At most 2 real task runs. Stop and ask before any new dependency.

## Progress Evidence
End with test output, the traversal-rejection response, and a short description of
what you saw in the browser (or ask me to confirm the browser checks).
