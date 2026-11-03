# agent-office

A personal, self-hosted web app: type a task into a chat box, an orchestrator agent
(Claude Agent SDK) splits it across subagents, the browser shows each agent working,
and every task's results land in their own directory under `tasks/`. See `CLAUDE.md`
and `docs/PLAN.md` for the rules and phases.

## Run

Backend (binds to 127.0.0.1 only):

```bash
cd backend
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Backend tests:

```bash
cd backend
uv run pytest
```

Frontend:

```bash
cd frontend
npm run dev
```

## Versions (Phase 0, M3 MacBook Air)

| Tool | Version |
|---|---|
| Python | 3.12.11 (via uv) |
| uv | 0.12.10 |
| Node | 24.21.0 |
| npm | 11.19.0 |
| Nuxt | 4.6.4 |
| FastAPI | 0.162.0 |
| uvicorn | 0.54.0 |
| Claude Code CLI | TBD — `claude` not on PATH yet |
