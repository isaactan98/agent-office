## Session Strategy
New session. Read `CLAUDE.md` first.

> Written after the fact (Phase 9). Phase 8 was asked for in chat; this file
> records what was built in session 9 (2026-11-05) so every phase has a prompt.

## Objective
Replace the 2D canvas office with a 3D isometric office (three.js), and make the
UI office-first: a dark theme with the chat panel floating inside the office.

## Context
Phases 0–7 done. The office is driven by the `OfficeState` reducer in
`frontend/app/utils/officeState.ts` (events in, characters/status out), which
has its own tests and does not change in this phase.

## Target State
- `three` added, pinned exact (0.186.1). No asset files: everything is built
  from primitives and canvas textures.
- `frontend/app/utils/officeScene.ts` draws `OfficeState` with three.js:
  - orthographic camera at an isometric angle; a dark night office with glass
    outer walls, a glass meeting room (8 seats for unknown agents), lounge,
    coffee counter, a back-to-back desk cluster, and the orchestrator's
    3-monitor desk by the windows; warm point lights and soft moonlight shadows;
  - robots in lighter versions of the feed tag colours, with poses for
    walking / working / talking / idle, blinking, and walks that follow
    waypoints so nobody walks through desks;
  - name tag + status, speech bubble and the `tool_denied` "!" as HTML labels
    (CSS2DRenderer).
- Camera: OrbitControls (three's `examples/jsm`, no new dependency) — drag to
  rotate (polar 18°–75°), scroll/pinch to zoom towards the cursor (0.6×–4×),
  right-drag/two fingers to pan (clamped to the floor), "Reset view"; walls
  between the camera and the room are hidden.
- `Office.vue` keeps live/replay logic, loads three.js in `onMounted` only (no
  WebGL during SSR), disposes the scene on unmount, works with no task open,
  shows replay controls and the agent legend as overlays, and takes
  `insetRight` so the camera frames the room left of the chat panel.
- `app.vue`: dark theme; sidebar = brand, usage, task list; the office fills the
  main area; the chat panel (Chat tab: task header + Cancel, feed, input; Files
  tab: list + viewer) floats on the right, collapsible; at ≤900 px it moves
  below the office.

## Scope
- Work only in: `frontend/`.

## Constraints
- Only new dependency: `three`. The reducer and its tests stay unchanged.
- Only make changes directly requested.

## Acceptance Criteria
- [x] `npm test` and `npm run build` pass
- [x] Replay of a finished task shows each agent's status changing and the
      speech bubble; no console errors
- [x] Switching tasks leaves one WebGL canvas and one label layer
- [x] 375 px wide: no horizontal page scroll
- [x] Live task watched in the office (verified 2026-11-11)

## Action Boundaries
- No real task runs needed (replay an existing task).

## Progress Evidence
Test/build output and what was seen in the browser (logged in PROGRESS.md,
session 9).
