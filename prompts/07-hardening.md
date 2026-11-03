## Session Strategy
New session. Read `CLAUDE.md` first.

## Objective
Make it safe and practical to leave running and use from my phone over Tailscale.

## Context
Phases 0–6 done. Single-task 409 rejection exists. Backend binds 127.0.0.1.

## Target State
- FIFO queue: `POST /tasks` while busy → status `queued` instead of 409; cancel
  endpoint `POST /tasks/{id}/cancel` for queued or running tasks (running = interrupt
  the SDK session using its documented interrupt method; status `cancelled`).
- Usage log: after each task, append to `TASKS_DIR/usage.jsonl` whatever usage/cost
  fields the SDK result message provides (task_id, duration, turns, raw usage dict).
  `GET /usage` returns totals for today and this month. Do not invent fields the SDK
  does not return.
- Daily task cap from config (default 20); over the cap → HTTP 429 with a clear message.
- Startup check: refuse to start if `ANTHROPIC_API_KEY` is set in the environment.
- Re-audit every endpoint that takes a path or task_id; add tests for each.
- `docs/RUNNING.md`: how to run backend + built frontend on the Mac, and how to expose
  it to my tailnet only via `tailscale serve` (document the command; do not run it).

## Scope
- Work only in: `backend/`, `frontend/` (queue status, cancel button, usage panel),
  `docs/RUNNING.md`.

## Constraints
- No new dependencies without asking. Never configure Cloudflare Tunnel or any public exposure.
- Only make changes directly requested.

## Acceptance Criteria
- [ ] Two quick submissions → second shows `queued`, then runs after the first
- [ ] Cancel works for both queued and running tasks
- [ ] Backend refuses to start with `ANTHROPIC_API_KEY=x` set (test it)
- [ ] Traversal tests pass for every path-taking endpoint
- [ ] `/usage` totals match `usage.jsonl`

## Action Boundaries
- At most 2 real runs. Stop and ask before running any `tailscale` command or
  changing network settings.

## Progress Evidence
End with tests, the queue/cancel demo output, and the startup-refusal output.
