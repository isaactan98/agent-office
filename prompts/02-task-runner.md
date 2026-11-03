## Session Strategy
New session. Read `CLAUDE.md` and `docs/PLAN.md` (Task directory contract) first.

## Objective
Turn the spike into a real backend service: submit a task over HTTP, run it in an
isolated task directory, save output + manifest. Single agent only, no subagents yet.

## Context
Phase 1 proved the SDK runs on my Pro login. Reuse the verified option names from
`backend/spikes/README.md`. Do not re-discover them unless something fails.

## Target State
- `app/tasks.py`: create task dir per the contract (`manifest.json`, `output/`),
  task_id format `YYYYMMDD-HHMMSS-<slug>` (slug from task text, ascii, max 30 chars),
  manifest status transitions `queued → running → done|failed`.
- `app/runner.py`: async function `run_task(task_id)` that runs one Agent SDK session:
  - working dir = `TASKS_DIR/<task_id>/`; agent instructed to write deliverables under `output/`
  - file read/write/edit/search tools only; settings isolation on (same as spike)
  - a PreToolUse hook that denies any tool call whose file path resolves outside the
    task dir (resolve `..`, absolute paths, symlinks)
  - writes `summary.md` from the final result; on exception, status `failed` + error in manifest
- `app/main.py` endpoints:
  - `POST /tasks` `{ "text": "..." }` → creates task, starts it in the background,
    returns `{ task_id, status }`. Reject if a task is already running (HTTP 409).
  - `GET /tasks` → list manifests, newest first
  - `GET /tasks/{task_id}` → manifest
- Tests in `tests/`: task dir creation, slug, manifest transitions, path-guard function
  (unit-test the guard directly with `../`, absolute path, symlink cases). Tests must NOT
  call the real SDK — mock the runner.

## Scope
- Work only in: `backend/app/`, `backend/tests/`.
- Do NOT touch: `backend/spikes/`, `frontend/`, `docs/`.

## Constraints
- No new dependencies. Never set `ANTHROPIC_API_KEY`.
- Validate `task_id` path params (reject anything not matching the format) to prevent
  path traversal through the API.
- Only make changes directly requested.

## Acceptance Criteria
- [ ] `uv run pytest` passes, including the path-guard tests
- [ ] One manual run: `curl -X POST /tasks` with "Write output/hello.md with a two-line
      greeting" → task finishes `done`, file exists in `output/`, `summary.md` exists
- [ ] A second POST while the first is running returns 409
- [ ] Nothing written outside `TASKS_DIR`

## Action Boundaries
- At most 2 real task runs this session.
- Stop and ask before adding dependencies, deleting files, or changing the contract in PLAN.md.

## Progress Evidence
End with test output, the curl commands + responses, and `ls -R` of the finished task dir.
