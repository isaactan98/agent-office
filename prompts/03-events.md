## Session Strategy
New session. Read `CLAUDE.md` and the Event schema in `docs/PLAN.md` first.

## Objective
Capture what the agent does as structured events, using SDK hooks plus the message
stream, so a UI can show it live and replay it later.

## Context
Phase 2: tasks run via `app/runner.py` with a PreToolUse path guard. No events yet.

## Target State
- `app/events.py`:
  - `Event` model matching the PLAN.md schema exactly
  - per-task emitter: assigns increasing `seq`, timestamps (Asia/Singapore offset),
    appends one JSON line to `events.jsonl`, and publishes to an in-memory async
    pub/sub (one subscriber list per task) for the WebSocket phase
- `app/runner.py` emits:
  - `task_started`, `task_done` / `task_failed`
  - `tool_start` from PreToolUse, `tool_end` from PostToolUse, `tool_denied` when the guard blocks
  - `agent_message` for assistant text blocks (summary = first 120 chars)
  - fill `agent` / `agent_id` from hook input when the SDK provides them (verify which
    hooks carry these fields in the installed version; default `agent="orchestrator"`)
- `GET /tasks/{task_id}/events` → full `events.jsonl` as a JSON array
- Tests: emitter seq ordering, jsonl append, pub/sub delivery, schema validation.
  Use synthetic hook inputs — no real SDK calls in tests.

## Scope
- Work only in: `backend/app/`, `backend/tests/`.
- Do NOT touch: `frontend/`, `docs/` (unless the schema must change — then ask first).

## Constraints
- `summary` and `path` only. Never put file contents or full prompts in events.
- Hooks must never raise into the SDK; log and continue.
- No new dependencies. Only make changes directly requested.

## Acceptance Criteria
- [ ] `uv run pytest` passes
- [ ] One real run produces `events.jsonl` where `seq` is strictly increasing and the
      first/last events are `task_started` / `task_done`
- [ ] Every event validates against the schema (add a small script or test to check a file)

## Action Boundaries
- At most 1 real task run. Stop and ask before schema changes or new dependencies.

## Progress Evidence
End with test output and the first 15 lines of the real `events.jsonl`.
