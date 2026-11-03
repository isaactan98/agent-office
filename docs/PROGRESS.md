# Progress log

Newest entry on top. Updated at the end of each session (`prompts/session-end.md`).

## Current state
- Phase: 7 done (all phases in PLAN.md done)
- Machine last used: M3 MacBook Air (SG)
- Blockers: none. `uv run pytest` → 242 passed; `npm test` → 20 passed;
  `npm run build` → build complete.

## Log

### 2026-11-04 — SG — M3 MacBook Air (session 8)
- Done: Phase 7 hardening. `app/main.py`: `POST /tasks` always creates a
  `queued` task; a single worker runs `_pending` (deque) FIFO, one at a
  time (no more 409). `POST /tasks/{id}/cancel`: queued → removed and
  marked `cancelled` (also a `queued` manifest left from before a restart);
  running → `runner.request_cancel` (SDK `interrupt()`), waits up to 15 s,
  then cancels the asyncio task; done/failed/stale `running` → 409.
  `GET /usage` → today/month totals + `daily_task_cap` +
  `tasks_created_today`. `DAILY_TASK_CAP` (default 20, `app/config.py`) →
  429 with message; tasks cancelled before they started don't count.
  FastAPI lifespan calls `config.check_no_api_key()` → startup fails if the
  name `ANTHROPIC_API_KEY` is in the environment (value never read).
  `_existing_task_dir` now 404s a symlinked task dir (audit finding: a
  symlink in TASKS_DIR with a valid id exposed its target via `/files`).
  WS stays open while a task is queued. `app/runner.py`: session moved from
  `query()` to `ClaudeSDKClient` (only the client has `interrupt()`);
  status `cancelled` (transitions queued/running → cancelled in
  `tasks.py`); ending event `task_failed` "Task cancelled" (or "… before it
  started"). New `app/usage.py`: one line per SDK `ResultMessage` in
  `TASKS_DIR/usage.jsonl` (task_id, recorded_at, status, subtype,
  duration_ms, duration_api_ms, num_turns, total_cost_usd, usage,
  model_usage — SDK values as returned); totals sum numeric top-level keys
  of `usage`. Frontend `app.vue`: input stays enabled ("Queue" while busy,
  queued count), Cancel button for queued/running, usage panel in the
  sidebar, ≤720 px stacked layout (not asked for; added for phone use);
  replay offered for `cancelled` too. New `docs/RUNNING.md` (local run,
  built frontend with `HOST=127.0.0.1`, `tailscale serve` on 443 → :3000
  and 8443 → :8000, never funnel). Committed as 462bb6b (not pushed).
- Verified by: installed SDK 0.2.177 `client.py` (`interrupt()` on
  `ClaudeSDKClient` only; `query()` docstring: no interrupts) and
  `types.py` `ResultMessage` fields. `uv run pytest` → 242 passed (new:
  FIFO order, cancel queued/running/fallback/orphan, 409s, cap, usage
  totals, startup refusal, 10 bad task_ids × 5 endpoints + WS, symlinked
  task dir × 5 endpoints + WS → all 400/404). `npm test` → 20 passed;
  `npm run build` → build complete. `ANTHROPIC_API_KEY=x uv run uvicorn …`
  → "RuntimeError: ANTHROPIC_API_KEY is set …", "Application startup
  failed. Exiting.", exit code 3, nothing listening on 8000. Built frontend
  with `HOST=127.0.0.1 PORT=3123 NUXT_PUBLIC_API_BASE=…` → `lsof` listen
  127.0.0.1 only, page carries the runtime apiBase. 2 real runs (of 2),
  backend 127.0.0.1:8000: A, B, C posted → `queued` ×3; C cancelled while
  queued → 200 `cancelled`, `started_at` null; A cancelled after
  `subagent_start writer` → 200 `cancelled` in 0.9 s (no "interrupt
  failed" in log, result `error_during_execution`, no output file); B
  `queued` while A ran, then `running`, `done` in ~33 s, 6 turns, 26 events
  (writer + reviewer). `python -m app.events` OK for A (4), B (26), C (1).
  `GET /usage` today == sums from `usage.jsonl` (5 sessions, 37303 ms, 12
  turns, $0.1700576 est., identical token sums); month == today.
- Notes: the first live attempt failed "Not logged in" for all 3 tasks (0
  tokens, $0): `env -i PATH HOME` drops `USER`, and the CLI needs it to read
  the Pro login from the macOS keychain. Starting with `USER`/`LOGNAME`
  fixed it (noted in RUNNING.md). Those 3 tasks (`20261104-062534-*`,
  `failed`) stay in `tasks/` and in `usage.jsonl`; they count toward
  today's cap (5/20 after the demo). Usage today/month uses local time (task
  ids too); event `ts` stays Asia/Singapore. `.env` is not loaded by
  `config.py`; `DAILY_TASK_CAP` not added to `.env.example` (outside
  scope). Queued tasks are in memory only: after a restart they stay
  `queued` until cancelled. Stale `running` manifests still can't be
  cancelled (409). Unverified: usage panel, Cancel button and phone layout
  in a browser (build only); `tailscale serve` (not run) and whether it
  proxies the WebSocket (docs silent).
- Next: run the app from my phone over the tailnet per `docs/RUNNING.md`
  (I run the `tailscale serve` commands myself). No Phase 8 prompt exists.
- Open questions: add a `task_cancelled` event type to PLAN.md instead of
  `task_failed` "Task cancelled"? Add `DAILY_TASK_CAP`/`FRONTEND_ORIGIN` to
  `.env.example`? Should restart re-queue `queued` manifests or let me cancel
  stale `running` ones? (Still open: keep Node's test runner or vitest;
  manifest `agents` shape in PLAN.md; `tool` may be `null` in PLAN.md; pin a
  cheaper default model; live hook deny; claude.ai login terms;
  `CLAUDE_CONFIG_DIR`.)

### 2026-11-04 — SG — M3 MacBook Air (session 7)
- Done: Phase 6 2D office. `frontend/app/utils/officeState.ts`: pure
  `reduce(state, event)` + `tick(state, nowMs)`; time comes only from event
  `ts` (or the `nowMs` passed in). Per character: `idle | walking | working
  | talking` (derived by `characterStatus`), red "!" for 3 s after
  `tool_denied`, bubble = first 40 chars of `summary` for 3 s, walks take
  2 s (door ↔ desk). `subagent_start` → walk door → desk; `subagent_stop`
  → walk desk → door, then leaves the room (not drawn). Orchestrator is
  always in the room. Unknown agents → spare desk 1–3, then meeting table
  seats; unknown event types → same state object returned. `task_done`/
  `task_failed` reset open tools. `frontend/app/components/Office.vue`:
  plain Canvas 2D (3 named desks, 3 spare, meeting table, door), original
  simple shapes in the feed's agent colours; live mode reduces the feed
  array (scene clock = `Date.now()` + max offset from event `ts`); replay
  (done/failed tasks only) fetches `GET /tasks/{id}/events` and plays it
  with original relative timing, 1×/4×, pause, restart, back to live.
  Placed above the feed in `app.vue` (`:key` = task id). Reducer tests in
  `frontend/tests/officeState.test.ts` with Node's built-in runner
  (`npm test` → `node --test 'tests/*.test.ts'`, Node 24 strips types; no
  new dependency). Committed as 4f8cb0d (not pushed).
- Verified by: `npm test` → 20 passed, 0 failed (all 10 PLAN.md types,
  unknown type, unknown agents, bad/missing `ts`, no mutation via deep
  freeze). `npm run build` → build complete. `uv run pytest` → 152 passed.
  `git diff -- backend docs` empty before the Phase 6 commit. Reducer replay of
  `20261103-231235-write-output-route-md-a-short` (scratch script, 50 ms
  samples): orchestrator idle → working (+8.2s) → idle → working → idle →
  working → idle → working → idle → talking (+119.0s) → idle; writer
  walking (+8.3s) → idle → working → idle → walking (+31.6s) → away →
  walking (+81.5s) → working → idle → working → idle → walking → away;
  reviewer walking (+35.6s) → idle → working → idle → working → idle →
  working → idle → walking (+74.5s) → away. In-app browser, real backend
  (`env -i`, 127.0.0.1:8000): replay of that task showed reviewer walking,
  writer idle at desk, orchestrator working, ended at 31/31 with only the
  orchestrator. Live mode: a throwaway fake backend in the scratchpad (not
  in the repo, no agent run) streamed the same events at 4× with fresh
  `ts`; office matched the feed (writer walks in on `subagent_start`,
  walks out on the orchestrator's `tool_end Agent`, bubble on
  `agent_message`). A second fake stream with an injected `tool_denied`,
  unknown agent `researcher` and unknown type showed the red "!", a spare
  desk, and no errors.
- Notes: tools finish in ~15 ms, so a character keeps "working" for at
  least 1.5 s after `tool_start` (`MIN_WORK_MS`), else it is never visible.
  Prompt paths `frontend/components/`, `frontend/utils/` moved under
  `frontend/app/` (Nuxt 4 srcDir). The browser pane ran at ~2 fps (hidden/
  throttled), so the writer walking/typing in replay was not seen on
  screen (reducer output only); smoothness unverified. Replay frame step
  clamp raised from 100 ms to 1 s after replay crawled at 2 fps. A real
  live task with the office: unverified (no run spent).
- Next: Phase 7 (`prompts/07-hardening.md`) in a new session.
- Open questions: keep Node's built-in test runner, or switch to vitest?
  (Still open: manifest `agents` shape in PLAN.md; `FRONTEND_ORIGIN` in
  `.env.example`; `tool` may be `null` in PLAN.md; pin a cheaper default
  model; spend a run on a live hook deny; claude.ai login terms;
  `CLAUDE_CONFIG_DIR`.)

### 2026-11-03 — SG — M3 MacBook Air (session 6)
- Done: Phase 5 orchestrator + subagents. New `app/agents.py`: orchestrator
  system prompt (33 lines, passed as `system_prompt`), `writer`
  (Read/Write/Edit, maxTurns 10) and `reviewer` (Read/Glob/Grep/Write,
  maxTurns 8) as `AgentDefinition`s in `ClaudeAgentOptions.agents`. Session
  tools = Read/Write/Edit/Glob/Grep + `Agent` (the delegation tool).
  `subagent_start`/`subagent_stop` come from the SDK's SubagentStart/
  SubagentStop hooks (`agent` = `agent_type`, `agent_id` = SDK id; stop
  summary includes the subagent's last reply). Path guard additions:
  reviewer may Write only `output/review.md` (literal path, so a symlinked
  review.md is denied); `Agent` calls only from the orchestrator, only
  `writer`/`reviewer`, only fields description/prompt/subagent_type/
  run_in_background, `run_in_background` must be false, max 4 allowed
  per task (5th denied). Manifest `agents` is now a map name → run count
  (was a list). The orchestrator writes `summary.md`; the runner writes the
  result text only if it is missing. `agent_message` is emitted only for
  messages without `parent_tool_use_id`. Frontend: coloured agent tag per
  feed row + legend. 31 new tests. Committed as 61863a3 (not pushed).
- Verified by: installed SDK 0.2.177 `types.py` (`agents: dict[str,
  AgentDefinition]`, SubagentStart/Stop inputs with required `agent_id`/
  `agent_type`, optional on tool hooks); bundled CLI strings: tool name
  `Agent` (legacy `Task`), input keys description/prompt/subagent_type/
  model/effort/run_in_background/name/team_name/mode/isolation/cwd, agents
  run in the background unless `run_in_background` is false.
  `uv run pytest` → 152 passed. `npm run build` → build complete. 1 real
  run (of 2 allowed), backend started with `env -i`, `lsof` → 127.0.0.1:8000
  only: Kangkar Pulai prompt → task
  `20261103-231235-write-output-route-md-a-short` `done` in ~2 min, 5 turns;
  `python -m app.events` → "OK: 31 events, seq strictly increasing"; per
  agent: orchestrator 11, writer 12, reviewer 8; 3 `subagent_start`
  (writer, reviewer, writer fix); no `tool_denied`; manifest agents
  `{"orchestrator": 1, "writer": 2, "reviewer": 1}`; reviewer's only
  Write was `output/review.md` (plus Glob `output/**`, Read
  `output/route.md`). PreToolUse fires inside subagents: their
  `tool_start` events carry their own agent/agent_id.
- Notes: the prompt says the reviewer is read/search only, but it must write
  review.md, so it has Write limited by the guard. Subagent text is not in
  the feed (`forward_subagent_text` off). `subagent_stop` summaries can
  contain absolute paths (from the subagent's reply). Writer output was
  ~490 words, above "a few hundred". The 4-call cap and the background
  deny were not hit in the live run (unit tests only). The UI tags/legend
  were checked by build only, not seen in a browser: unverified.
- Next: Phase 6 (`prompts/06-office-2d.md`) in a new session.
- Open questions: should PLAN.md state the manifest `agents` shape
  (name → count)? (Still open: `FRONTEND_ORIGIN` in `.env.example`;
  `tool` may be `null` in PLAN.md; pin a cheaper default model — multi-agent
  runs now cost more; spend a run on a live hook deny; claude.ai login
  terms; `CLAUDE_CONFIG_DIR`.)

### 2026-11-03 — SG — M3 MacBook Air (session 5)
- Done: Phase 4 web UI. Backend (`app/main.py`): `WS /ws/tasks/{task_id}`
  subscribes first, replays `events.jsonl`, then streams pub/sub events
  (dedup by seq) and closes after `task_done`/`task_failed`, or once the
  task is not running in this process (checked every 1 s; the asyncio task
  is now named after the task_id). `GET /tasks/{id}/files` → sorted
  `{path, size}` list via `os.walk` (symlinks resolving outside skipped).
  `GET /tasks/{id}/files/{path}` → text/plain; same `is_path_inside` check
  as the agent guard → 400 outside, 404 missing/dir, 413 ≥ 1 MiB, 415
  NUL byte or not UTF-8. CORS: only `FRONTEND_ORIGIN` (new in
  `app/config.py`, default `http://localhost:3000`). Not asked for in the
  prompt, added because browsers don't apply CORS to WebSockets: the WS
  closes (1008) on any `Origin` other than `FRONTEND_ORIGIN`; no Origin
  (curl, tests) is allowed. Frontend (`app/app.vue`, plain Vue + CSS, no
  new deps): chat box (disabled while a task is queued/running, shows the
  reason; POST errors shown as "409: …"), live feed (time/agent/type/
  summary, colour per type, unknown types → grey generic row with raw
  JSON, auto-scroll when near bottom), task sidebar with status badges,
  file list + `<pre>` viewer; open task kept in `?task=` for reloads;
  `runtimeConfig.public.apiBase` default `http://127.0.0.1:8000`.
  23 new tests in `test_api.py` (files, traversal, 413/415, CORS, WS
  replay/live/stale/origin/bad id). Committed as 465f036 (not pushed).
- Verified by: `uv run pytest` → 121 passed. `npm run build` → build
  complete. `lsof` → backend 127.0.0.1:8000, Nuxt dev [::1]:3000 only;
  backend started with `env -i`. `curl --path-as-is
  /tasks/<id>/files/../../CLAUDE.md` → `400 {"detail":"path is outside the
  task directory"}`; `%2F`-encoded and absolute forms → same 400. Browser
  (in-app browser): finished task replayed with its files; 1 real run (of 2
  allowed) with the Skudai cafes prompt → task
  `20261103-222842-write-output-plan-md-listing-5`: `task_started` showed
  live, Send disabled with reason; reload mid-task → reconnected
  (`feed: live`), then seq 2–5 arrived live and the socket closed;
  sidebar → `done`, `output/plan.md` (3.1 KB) opened in the viewer; no
  console errors. `python -m app.events` → "OK: 5 events, seq strictly
  increasing".
- Notes: the reload happened when only 1 event existed, so the replay part
  after reload was small (replay of a full finished task was seen
  separately). Unknown-type rows and the 409 message in the UI were not
  seen in the browser: unverified (409 itself is unit-tested). Opening the
  UI at `127.0.0.1:3000` instead of `localhost:3000` will fail CORS
  unless `FRONTEND_ORIGIN` is changed. A manifest left `running` after a
  crash still disables Send in the UI (Phase 2 gap). No frontend tests or
  typecheck (`vue-tsc` not installed).
- Next: Phase 5 (`prompts/05-orchestrator.md`) in a new session.
- Open questions: add `FRONTEND_ORIGIN` to `.env.example`? (Still open:
  should PLAN.md state that `tool` may be `null`; pin a cheaper default
  model; spend a run on a live hook deny; claude.ai login terms;
  `CLAUDE_CONFIG_DIR`.)

### 2026-11-03 — SG — M3 MacBook Air (session 4)
- Done: Phase 3 events. `app/events.py`: `Event` pydantic model with the
  PLAN.md fields in order (`extra="forbid"`, `type` Literal of the 10 types,
  `ts` must have an offset, `path` must be relative, `task_id` matches the id
  regex); `EventEmitter` (seq from 1, no gaps, Asia/Singapore `ts`, appends
  to `events.jsonl`, publishes to `subscribe(task_id)` queues); summaries
  collapsed to one line, ≤120 chars; `read_events`, `validate_file`
  (`uv run python -m app.events <file>`). `app/runner.py`: `task_started`,
  `task_done`/`task_failed`, `agent_message` per assistant `TextBlock`,
  `tool_start`/`tool_denied` from the PreToolUse guard, `tool_end` from
  PostToolUse and PostToolUseFailure (summary "… failed: path"; not asked
  for in the prompt, added so failed tools don't leave an open
  `tool_start`). Hooks never raise: a guard error now logs and returns an
  explicit deny; event write errors are logged and the decision still
  goes through. `GET /tasks/{task_id}/events` → JSON array (400/404 like
  `GET /tasks/{id}`). Tests: `test_events.py`, hook/run_task event tests in
  `test_runner.py` (synthetic hook inputs, fake `query`), endpoint tests in
  `test_api.py`. Committed as 1ad9265 (not pushed).
- Verified by: installed `types.py` — `agent_id`/`agent_type` are optional on
  PreToolUse/PostToolUse/PostToolUseFailure/PermissionRequest (set only
  inside a subagent) and required on SubagentStart/SubagentStop;
  `agent = agent_type or "orchestrator"`. `uv run pytest` → 98 passed.
  1 real run (of 1 allowed), backend started with `env -i`, `lsof` → listen
  on 127.0.0.1:8000 only: task
  `20261103-222005-write-output-hello-md-with-a-t` → `done` in ~12 s, 3
  turns; `events.jsonl` 8 events (task_started, tool_start/tool_end Write,
  agent_message, tool_start/tool_end Read, agent_message, task_done);
  `python -m app.events` → "OK: 8 events, seq strictly increasing";
  `GET /tasks/<id>/events` → list of 8, seq 1–8. `npm run build` → build
  complete.
- Notes: `tool` is treated as nullable (PLAN.md doesn't say; schema text
  unchanged). `agent_message` is always `orchestrator`: `AssistantMessage`
  has `parent_tool_use_id` but no `agent_id` (Phase 5). Whether a guard
  deny also fires PostToolUseFailure in a live session: unverified; a live
  deny is still unit-tested only. Pub/sub queues are unbounded; nothing
  subscribes yet. The `find -newer` check for files outside `tasks/` was
  not repeated this session: unverified.
- Next: Phase 4 (`prompts/04-web-ui.md`) in a new session.
- Open questions: should PLAN.md state that `tool` may be `null`? (Still
  open: pin a cheaper default model; spend a run on a live hook deny;
  claude.ai login terms; `CLAUDE_CONFIG_DIR`.)

### 2026-11-03 — SG — M3 MacBook Air (session 3)
- Done: Phase 2 task runner. `app/tasks.py` (task_id
  `YYYYMMDD-HHMMSS-<slug>`, slug ascii ≤30 chars; task dir with
  `manifest.json` + `output/`; status `queued → running → done|failed`, other
  changes raise; `task_dir()` rejects invalid ids). `app/runner.py`
  (`run_task()`: one SDK session, cwd = task dir, tools
  Read/Write/Edit/Glob/Grep, same isolation options as the spike,
  `max_turns=20`; PreToolUse hook `HookMatcher(matcher=None,
  on_failure="block")` denies paths outside the task dir — `..`, absolute,
  `~`, symlinks incl. dangling/loops, Glob `pattern`/Grep `glob`+`path` —
  and denies unknown tools; writes `summary.md`; errors → `failed` + `error`;
  refuses if `ANTHROPIC_API_KEY` name is present). `app/main.py`
  (`POST /tasks` → 409 while running, `GET /tasks` newest first skipping
  non-task dirs like `spike-*`, `GET /tasks/{id}` → 400 bad format / 404
  missing). Tests: `conftest.py`, `test_tasks.py`, `test_runner.py`
  (path guard + `run_task` with a fake `query`), `test_api.py` (fake
  `run_task`). Committed as 3cbcaf8 (not pushed).
- Verified by: Glob/Grep input keys (`pattern`, `path`, `glob`) checked in the
  bundled CLI binary; hook types in installed `types.py`. `uv run pytest` →
  63 passed. 1 real run (of 2 allowed), backend started with `env -i`:
  `POST /tasks` "Write output/hello.md with a two-line greeting" → 200
  `20261103-185053-write-output-hello-md-with-a-t`; immediate second POST →
  409; task `done` in ~12 s, `output/hello.md` (2 lines) and `summary.md`
  exist; `lsof` → listen on 127.0.0.1:8000 only. `find -newer` marker: no new
  repo files outside `tasks/`; in `$HOME` (depth 2, excl. `~/.claude`,
  `~/Library`) only `~/.claude.json` (CLI bookkeeping, as in Phase 1).
  `npm run build` → build complete.
- Notes: the live run never attempted an outside path, so a hook **deny**
  in a real SDK session is unverified (unit tests only). `agents` in the
  manifest is `["orchestrator"]`. Model still not pinned (default Opus).
  No `events.jsonl` yet (Phase 3). A manifest left `running` after a server
  crash is not recovered.
- Next: Phase 3 (`prompts/03-events.md`) in a new session.
- Open questions: pin a cheaper default model? Spend a run to verify a live
  hook deny? (Still open from session 2: claude.ai login terms;
  `CLAUDE_CONFIG_DIR`.)

### 2026-11-03 — SG — M3 MacBook Air (session 2)
- Done: Phase 1 SDK spike. Added `claude-agent-sdk` 0.2.177 (bundles CLI
  2.1.317). `backend/spikes/sdk_spike.py` runs one haiku task in a fresh
  `tasks/spike-<timestamp>/` with `tools=["Read","Write"]`,
  `permission_mode="dontAsk"`, `setting_sources=[]`, `strict_mcp_config=True`,
  `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`. `backend/spikes/README.md` lists verified
  SDK names and surprises. Committed as cdeead3 (not pushed).
- Verified by: `env | grep -i anthropic` → no `ANTHROPIC_API_KEY` (names only).
  1 spike run (of 2 allowed), launched with `env -i` because the Claude desktop
  app shell exports `ANTHROPIC_BASE_URL` and `CLAUDE_CODE_*` vars: init reported
  `apiKeySource='none'`, `tools=['Read','Write']`, `mcp_servers=[]`, cwd = spike
  dir; one `Write` to `<spike dir>/notes.md`; result `success`, 2 turns, 8.6 s,
  `permission_denials: []`; no `~/.claude/skills` entries in init `skills`.
  `git status` → only pyproject.toml, uv.lock, spikes/; `find -newer` in repo →
  only notes.md plus gitignored `.pyc`. `claude auth status` (installed and
  SDK-bundled CLI, clean env) → `loggedIn: true`, `authMethod: claude.ai`,
  `subscriptionType: pro`. `uv run pytest` → 1 passed; `npm run build` → build
  complete.
- Notes: `allowed_tools` only auto-approves; `tools` restricts. Default
  `setting_sources=None` loads `~/.claude`. CLI still writes its own transcript
  and `.claude.json` backup under `~/.claude`. Default model was claude-opus-5-5;
  `total_cost_usd` (~$0.021) is a list-price estimate, not a bill. No PreToolUse
  path hook yet. Start the backend from a plain terminal, not inside Claude Code.
- Next: Phase 2 (`prompts/02-task-runner.md`) in a new session.
- Open questions: the Agent SDK quickstart says third-party developers may not
  offer claude.ai login in their products without approval; this project is
  personal/single-user, so assumed not to apply (your call). Whether to pin a
  cheaper default model, and whether to relocate CLI state via
  `CLAUDE_CONFIG_DIR` (may move the login; untested).

### 2026-11-03 — SG — M3 MacBook Air
- Done: Phase 0 skeleton. `backend/` (uv, FastAPI `GET /health`, `app/config.py`
  with TASKS_DIR/HOST/PORT, pytest), `frontend/` (Nuxt 4.6.4 minimal starter),
  `.gitignore`, `.env.example`, `README.md` with tool versions, Commands section
  of `CLAUDE.md`. Committed as 988be0a (not pushed).
- Verified by: `uv run pytest` → 1 passed (1 warning: Starlette suggests `httpx2`);
  `curl 127.0.0.1:8000/health` → `{"status":"ok"}`, `lsof` shows listen on
  127.0.0.1:8000 only; `npm run dev` → HTTP 200 on localhost:3000; `npm run build`
  → build complete; `git add -A --dry-run` → no .venv/node_modules/.nuxt/tasks/.env.
- CLI: Claude Code's attempt to run the installer was blocked by its permission
  system; I ran it myself. `claude --version` → `2.1.317 (Claude Code)`, on PATH at
  `~/.local/bin/claude`. Recorded in README.
- Next: run `claude` once and log in with Pro (unverified); then Phase 1
  (`prompts/01-sdk-spike.md`) in a new session.
- Open questions: none.
<!--
### YYYY-MM-DD — <JB|SG> — <machine>
- Done:
- Verified by:
- Next:
- Open questions:
-->
