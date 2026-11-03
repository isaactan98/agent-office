## Session Strategy
New session. Read `CLAUDE.md` and `docs/PLAN.md` first.

## Objective
Switch from a single agent to orchestrator + subagents, with every event tagged by
which agent did it, so the UI can tell them apart.

## Context
Phases 0–4 done: tasks run in isolated dirs, events stream to the browser.
Currently one agent does everything.

## Target State
- `app/agents.py`: subagents defined in code via the SDK's programmatic subagent option
  (verify the exact option and type names in the installed SDK first):
  - `writer`: produces the deliverable files under `output/`. Tools: file read/write/edit.
  - `reviewer`: reads `output/`, writes `output/review.md` with concrete issues
    (max 10 bullets). Tools: file read/search only — it cannot edit deliverables.
- Orchestrator system prompt (in `app/agents.py`, plain string, under 40 lines):
  plan in at most 5 steps, delegate writing to `writer`, then call `reviewer`, then
  ask `writer` to fix at most once, then write `summary.md`. Hard cap: no more than
  4 subagent invocations per task.
- Events: `subagent_start` / `subagent_stop` emitted (use the SDK's subagent hooks if
  available in Python; otherwise derive from the delegation tool call — document which).
  `agent` field = subagent name, `agent_id` = SDK id.
- Manifest records which agents ran and how many times.
- Frontend feed: show agent name as a coloured tag per row; legend at top.

## Scope
- Work only in: `backend/app/`, `backend/tests/`, `frontend/` (feed tag/legend only).
- Do NOT touch: `docs/` (except PLAN.md if an event type must be added — ask first).

## Constraints
- Same tool restrictions as before: no Bash, no web. Settings isolation stays on.
- Subagents inherit the path guard — verify the PreToolUse hook also fires inside
  subagents; if it does not, stop and tell me.
- No new dependencies. Only make changes directly requested.

## Acceptance Criteria
- [ ] Task "Write output/route.md: a short guide to a 30-minute evening drive around
      Kangkar Pulai, with 3 stops" produces events from `orchestrator`, `writer`, `reviewer`
- [ ] `output/review.md` exists; the reviewer never wrote to any other file
- [ ] Subagent invocations ≤ 4 (count from events)
- [ ] A path-guard test proves subagent tool calls outside the task dir are denied
- [ ] Tests pass

## Action Boundaries
- At most 2 real runs — multi-agent runs use noticeably more of my usage.
- Stop and ask if the subagent hook/agent_id behaviour differs from what this prompt assumes.

## Progress Evidence
End with tests, an event count per agent for the real run, and the reviewer's file listing.
