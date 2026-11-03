## Session Strategy
New session. Read `CLAUDE.md` first.

## Objective
Create the repo skeleton for agent-office and verify the toolchain on this Mac.
No agent logic yet.

## Context
Empty repo except `CLAUDE.md`, `docs/`, `prompts/`. Machine: personal M3 MacBook
Air, macOS. Claude Code CLI is installed and logged in with my Pro subscription.

## Target State
```
backend/
  pyproject.toml        (uv project, Python >=3.10)
  app/__init__.py
  app/main.py           FastAPI app with GET /health -> {"status":"ok"}
  app/config.py         reads TASKS_DIR (default ../tasks), HOST=127.0.0.1, PORT=8000
  tests/test_health.py
frontend/               fresh Nuxt app (official create command), default page only
.gitignore              Python, Node, Nuxt, .env, tasks/, .DS_Store
.env.example            TASKS_DIR=, HOST=127.0.0.1, PORT=8000
README.md               one paragraph + how to run backend and frontend
```

## Scope
- Work only in: `backend/`, `frontend/`, `.gitignore`, `.env.example`, `README.md`,
  and the Commands section of `CLAUDE.md`.
- Do NOT touch: `docs/`, `prompts/`, anything outside the repo.

## Constraints
- Allowed dependencies: backend `fastapi`, `uvicorn[standard]`, `pytest`, `httpx`;
  frontend whatever the official Nuxt starter installs. Anything else: ask first.
- If `uv`, `node` or `npm` is missing, stop and tell me how to install it. Do not
  install toolchains yourself.
- Record the exact versions you used (python, uv, node, nuxt, fastapi) in README.md.
- Only make changes directly requested.

## Acceptance Criteria
- [ ] `cd backend && uv run pytest` passes
- [ ] `uv run uvicorn app.main:app --host 127.0.0.1 --port 8000` serves `/health`
- [ ] `cd frontend && npm run dev` starts without errors
- [ ] `git status` shows no ignored artifacts staged (no .venv, node_modules, tasks/)
- [ ] `claude --version` output recorded in README.md

## Action Boundaries
- Proceed with in-scope file creation, dependency install of the listed packages,
  and running the checks above.
- Stop and ask before any other dependency, deleting files, or `git push`.

## Progress Evidence
End with: the command outputs proving each acceptance check, and a proposed commit message.
