# Progress log

Newest entry on top. Updated at the end of each session (`prompts/session-end.md`).

## Current state
- Phase: 3 done
- Machine last used: M3 MacBook Air (SG)
- Blockers: none. `uv run pytest` → 98 passed; `npm run build` → build complete.

## Log

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
