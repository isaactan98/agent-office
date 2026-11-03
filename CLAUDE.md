# agent-office — project memory for Claude Code

Read this file, then `docs/PROGRESS.md`, at the start of every session.

## What this is
A personal, self-hosted web app. I type a task into a chat box in the browser.
An orchestrator agent splits the work across subagents. The browser shows each
agent working (text event stream first, 2D office later). Every task's results
are saved in its own directory.

Learning project. Priorities, in order: correct and safe > understandable > pretty.

## Locked decisions (do not change without asking me)
- Agent runtime: **Claude Agent SDK for Python** (`claude-agent-sdk`), driven from
  the backend. Authentication is my **personal Claude Pro subscription** through the
  Claude Code CLI login.
- **NEVER set or read `ANTHROPIC_API_KEY`.** No pay-per-token API usage. If the SDK
  refuses to run without an API key, stop and tell me. Do not work around it.
- Backend: Python 3.10+, FastAPI, uvicorn. Env/deps with `uv`.
- Frontend: Nuxt (Vue 3, TypeScript).
- Pattern: one orchestrator + named subagents (defined in code, not in ~/.claude).
- UI order: text event stream → 2D canvas office → (maybe) 3D. Never skip ahead.
- One task runs at a time (simple FIFO queue). No parallel tasks.
- Machines: personal M3 MacBook Air (16GB) now; maybe a Mac mini later. I work
  from both JB and SG and sync through GitHub only.
- This repo must NEVER be opened, cloned or run on my work laptop.

## Security rules (apply to every phase)
- Each task runs with its working directory locked to `TASKS_DIR/<task_id>/`.
- Agent tools in v1: file read/write/edit/search only. **No Bash, no web tools**
  until I explicitly approve a phase that adds them.
- Defense in depth: a PreToolUse hook denies any file path that resolves outside
  the task directory (handle `..`, absolute paths, symlinks).
- The SDK must not load my personal Claude Code settings, CLAUDE.md, or hooks from
  `~/.claude` (I have other tools hooked in there). Use the SDK's settings-isolation
  option; verify it in the installed version.
- Backend binds to `127.0.0.1` only. Remote access later through `tailscale serve`.
  Never expose through Cloudflare Tunnel or any public URL.
- No secrets in the repo. `.env` is gitignored; commit `.env.example` only.

## Layout
```
backend/      FastAPI app (app/), tests (tests/)
frontend/     Nuxt app
docs/         PLAN.md (phases + event schema), PROGRESS.md (session log)
prompts/      phase prompts I paste into Claude Code
tasks/        default TASKS_DIR — runtime output, gitignored
```

## Working rules for you (Claude Code)
- Only make changes the current prompt asks for. No extra features, refactors,
  abstractions or files.
- Stop and ask before: adding a dependency not named in the prompt, deleting any
  file, changing a locked decision, touching anything outside this repo, or any
  `git push`.
- Verify SDK class names, option names and hook names against the **installed**
  package (`types.py` and the official docs) before using them. Do not guess.
- Keep test tasks tiny (a few hundred words of output) — every run spends my
  subscription usage.
- Ground every "done" claim in a command output, test result or file you created.
- At the end of a session, update `docs/PROGRESS.md` when I ask (see
  `prompts/session-end.md`).

## Commands
Fill these in as they are created:
- Backend dev: `TBD`
- Backend tests: `TBD`
- Frontend dev: `TBD`
