## Session Strategy
New session. Read `CLAUDE.md`, then `docs/PROGRESS.md`.

## Objective
Clear the open questions carried in PROGRESS.md since session 2: cheaper default
models, restart recovery, a proper cancel event, small config/docs gaps, and one
live proof that the path guard denies a real escape attempt.

## Context
Phases 0–8 done. Verified on 2026-11-11: 242 backend + 20 frontend tests pass; a
live task shows in the 3D office; Cancel works for queued and running tasks.
Decisions below were made in chat on 2026-11-12 — do not re-open them.
- No model is pinned today, so every agent runs on Opus.
- Queued tasks live only in memory (`_pending` in `app/main.py`); after a restart
  they stay `queued`, and stale `running` manifests can't be cancelled (409).
- Cancelling logs `task_failed` "Task cancelled", shown in red in the feed.
- The `Agent` tool guard in `app/agents.py` already refuses a `model` key, so the
  orchestrator cannot override a subagent's model.

## Target State
1. **Models.** Orchestrator on `sonnet`; `writer` and `reviewer` on `haiku`.
   Use `ClaudeAgentOptions.model` (built in `app/runner.py`) and
   `AgentDefinition.model` (in `app/agents.py`). Verify both field names in the
   installed `types.py` first. Use the aliases, not full model IDs. Keep them in
   one place (constants in `agents.py` or `config.py`) — not new env vars.
2. **Restart recovery.** On backend startup (the existing `lifespan`):
   - manifests with status `queued` → appended to `_pending` in `created_at`
     order, so the worker runs them;
   - manifests with status `running` → status `failed`, `error` "Server
     restarted", `finished_at` set, and a `task_failed` event appended to
     `events.jsonl` with the next `seq`.
   Skip non-task dirs (e.g. `spike-*`) the same way `GET /tasks` does.
3. **`task_cancelled` event.** New event type, emitted instead of `task_failed`
   "Task cancelled" for queued and running cancels.
   - `docs/PLAN.md` event schema: add it to the `type` list (same commit).
   - Backend: `EventType` in `app/events.py`; the cancel paths in `app/main.py` /
     `app/runner.py`.
   - Frontend: `app.vue` (event type list, `TERMINAL_TYPES` so the live feed
     closes, a neutral non-red feed style), `officeState.ts` (treat like the end
     of a task). Old `events.jsonl` files with `task_failed` "Task cancelled"
     must still replay.
4. **`.env.example`.** Add `DAILY_TASK_CAP=20` and
   `FRONTEND_ORIGIN=http://localhost:3000`, each with a one-line comment.
5. **`@types/three`.** Add as a devDependency, pinned exact, matching three
   `0.186.x`. Use a version published at least two weeks ago; if none matches
   0.186, stop and ask.
6. **Docs.**
   - `prompts/08-office-3d.md`: describe Phase 8 as built (from the session 9
     entry in PROGRESS.md), in the same format as the other prompts. Update the
     Phase 8 row in `docs/PLAN.md` to point at it.
   - `docs/PLAN.md`: state the manifest `agents` shape (map of agent name →
     number of times started, e.g. `{"orchestrator": 1, "writer": 1}`; verify
     against the code) and that an event's `tool` may be `null`.
   - Add a Phase 9 row for this prompt.
   - `docs/RUNNING.md`: note that the `tailscale` CLI is not on PATH with the
     Mac app install (`/Applications/Tailscale.app/Contents/MacOS/Tailscale`).
7. **Live path-guard proof** (last, after item 1 lands). One tiny task asking
   the agents to write `../escape.md` (and nothing else of note). Confirm:
   - the hook denied it and a `tool_denied` event is in `events.jsonl`;
   - no `escape.md` exists in `TASKS_DIR` or the repo (check with `find`);
   - `usage.jsonl`'s `model_usage` for that run names Sonnet and Haiku models,
     not Opus.

## Scope
- Work only in: `backend/`, `frontend/`, `docs/PLAN.md`, `docs/RUNNING.md`,
  `.env.example`, `prompts/08-office-3d.md`.
- Keep Node's built-in test runner (decided; no vitest).

## Constraints
- Only new dependency allowed: `@types/three`. Ask before any other.
- Never set or read `ANTHROPIC_API_KEY`. Start the backend for the live run with
  a cleaned environment that passes `HOME`, `USER`, `LOGNAME`, `PATH` (see
  `docs/RUNNING.md`).
- If ports 8000/3000 are already in use, they are my servers: do not kill them —
  ask me to restart them.
- Only make changes directly requested.

## Acceptance Criteria
- [ ] Tests cover: model fields set on the options and both subagents; startup
      re-queues `queued` in order and fails stale `running`; queued and running
      cancel emit `task_cancelled`; the frontend reducer handles `task_cancelled`
      and an old `task_failed` "Task cancelled" replay.
- [ ] `cd backend && uv run pytest` and `cd frontend && npm test` pass;
      `npm run build` completes.
- [ ] Cancel a queued task in the browser → feed shows `task_cancelled` (not
      red) and closes; no task run spent.
- [ ] Live run (item 7) evidence: the `tool_denied` event line, the `find`
      output, the `model_usage` model names.
- [ ] `.env.example`, `docs/PLAN.md`, `docs/RUNNING.md` and
      `prompts/08-office-3d.md` updated as above.

## Action Boundaries
- At most 1 real task run (item 7). Queued-task cancels don't count.
- No `tailscale` commands, no network changes, no `git push`.

## Progress Evidence
End with test output, the queued-cancel check, and the item 7 evidence. Commit
when everything passes (not pushed).
