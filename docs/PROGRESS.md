# Progress log

Newest entry on top. Updated at the end of each session (`prompts/session-end.md`).

## Current state
- Phase: 0 done
- Machine last used: M3 MacBook Air (SG)
- Blockers: none. Claude Code CLI 2.1.317 installed; Pro login unverified.

## Log

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
