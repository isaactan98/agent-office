## Session Strategy
New session. Read `CLAUDE.md` and `docs/PLAN.md` first.

## Objective
Add the visual layer: a 2D office where each agent is a character whose animation
follows the event stream, plus replay of finished tasks.

## Context
Events already stream over WebSocket with `agent`, `type`, `tool`, `summary`.
The text feed stays — the office is an extra panel, not a replacement.

## Target State
- `frontend/components/Office.vue` using plain Canvas 2D (no game engine):
  - fixed layout: 3 desks (orchestrator, writer, reviewer), a meeting table, a door
  - characters = simple shapes or placeholder sprites I can replace later
  - state machine per character, driven only by events:
    `idle` (at desk) → `walking` → `working` (tool_start..tool_end, small typing animation)
    → `talking` (agent_message: speech bubble with first 40 chars, 3 s)
    `subagent_start` → character walks from door to desk; `subagent_stop` → back to idle
    `tool_denied` → red "!" above the character
  - unknown agents get a spare desk; unknown event types are ignored
- Replay: for a finished task, play `events.jsonl` with original relative timing,
  with 1×/4× speed and pause
- Rendering logic separated from state logic: `frontend/utils/officeState.ts`
  (pure functions: `reduce(state, event) → state`) with unit tests

## Scope
- Work only in: `frontend/`.
- Do NOT touch: `backend/`, `docs/`.

## Constraints
- No new dependencies without asking (if you think a test runner is needed for the
  reducer tests, ask which one first).
- Assets: no copyrighted or recognisable characters. Simple original shapes only.
- 60 fps is not required; correctness of state is.
- Only make changes directly requested.

## Acceptance Criteria
- [ ] Replaying the Phase 5 task shows the writer and reviewer walking in, working, and leaving
- [ ] Live task animates in sync with the text feed
- [ ] `reduce()` unit tests cover every event type in PLAN.md plus an unknown type
- [ ] No backend changes

## Action Boundaries
- No real task runs required — use existing `events.jsonl` files for development.
  If you need a new run, ask me first.

## Progress Evidence
End with reducer test output and a list of states each character passed through
during replay of the Phase 5 task.
