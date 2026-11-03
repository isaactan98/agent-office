# Plan

Each phase has one prompt in `prompts/`. Finish and commit a phase before
starting the next. A phase is done only when every acceptance check passes.

| Phase | Prompt | Outcome |
|---|---|---|
| 0 | `00-bootstrap.md` | Repo skeleton, toolchain verified |
| 1 | `01-sdk-spike.md` | Proof that the Agent SDK runs on my Pro login, sandboxed |
| 2 | `02-task-runner.md` | `POST /tasks` → isolated task dir → output + manifest |
| 3 | `03-events.md` | Hooks → event schema → `events.jsonl` + in-memory bus |
| 4 | `04-web-ui.md` | Nuxt: chat input, live text event stream, task list, file viewer |
| 5 | `05-orchestrator.md` | Orchestrator + 2 subagents, events tagged per agent |
| 6 | `06-office-2d.md` | 2D office canvas driven by events, replay from `events.jsonl` |
| 7 | `07-hardening.md` | Queue, usage log, path checks, Tailscale access |

## Task directory contract
```
TASKS_DIR/<task_id>/          task_id = YYYYMMDD-HHMMSS-<slug>
  manifest.json               task text, status, agents, timestamps, error
  events.jsonl                one event per line (schema below)
  summary.md                  orchestrator's final report
  output/                     files the agents produced
```
`status` values: `queued | running | done | failed | cancelled`.

## Event schema (contract between backend and frontend)
```json
{
  "seq": 12,
  "ts": "2026-11-03T21:14:05.123+08:00",
  "task_id": "20261103-211400-route-page",
  "agent": "orchestrator",
  "agent_id": null,
  "type": "tool_start",
  "tool": "Write",
  "path": "output/index.html",
  "summary": "Writing output/index.html"
}
```
- `agent`: `orchestrator` or the subagent's name (e.g. `writer`, `reviewer`).
- `agent_id`: SDK-provided id when inside a subagent, else `null`.
- `type`: `task_queued | task_started | agent_message | tool_start | tool_end |
  tool_denied | subagent_start | subagent_stop | task_done | task_failed`.
- `path`: relative to the task dir, or `null`.
- `summary`: one short human-readable line. Never include full file contents.
- `seq` is strictly increasing per task. The frontend must tolerate unknown types.

Changing this schema = update this file in the same commit.
