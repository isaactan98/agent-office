# Running agent-office

How to run the backend and the built frontend on the Mac, and how to reach
them from my phone over my tailnet. Both servers bind to `127.0.0.1` only;
`tailscale serve` is the only way in from other devices.

## Before you start
- `claude auth status` shows `loggedIn: true`, `authMethod: claude.ai` (Pro).
- `ANTHROPIC_API_KEY` must **not** be set. The backend refuses to start if it is
  (the check looks at the name only, never the value).
- Start the servers from a plain Terminal window, not from inside Claude Code
  (its shell exports `ANTHROPIC_BASE_URL` and `CLAUDE_CODE_*` variables).
  If you start the backend with a cleaned environment (`env -i ...`), pass
  `USER` and `LOGNAME` through: the CLI reads the Pro login from the macOS
  keychain and, without `USER`, every task fails with "Not logged in".
- `backend/app/config.py` reads environment variables only. A `.env` file is
  **not** loaded automatically: export the variables in the shell.

## Settings

Backend (environment variables):

| Variable | Default | Meaning |
|---|---|---|
| `TASKS_DIR` | `<repo>/tasks` | task dirs and `usage.jsonl` |
| `HOST` | `127.0.0.1` | keep it at `127.0.0.1` |
| `PORT` | `8000` | backend port |
| `FRONTEND_ORIGIN` | `http://localhost:3000` | the one origin allowed by CORS and the WebSocket check |
| `DAILY_TASK_CAP` | `20` | tasks per day; more → HTTP 429 |

Built frontend (environment variables, read when it starts):

| Variable | Use |
|---|---|
| `HOST` | set to `127.0.0.1` — Nuxt's server listens on all interfaces otherwise |
| `PORT` | frontend port, `3000` |
| `NUXT_PUBLIC_API_BASE` | backend URL **as the browser sees it** |

## 1. On the Mac only

Terminal 1 — backend:
```bash
cd backend && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Terminal 2 — build the frontend once (again after every frontend change), then run it:
```bash
cd frontend && npm run build
```
```bash
cd frontend && HOST=127.0.0.1 PORT=3000 node .output/server/index.mjs
```

Open `http://localhost:3000` (not `127.0.0.1:3000`: that is a different
origin and fails CORS unless `FRONTEND_ORIGIN` says so).

Check that nothing listens beyond localhost:
```bash
lsof -nP -iTCP -sTCP:LISTEN | grep -E ':(8000|3000) '
```
Every line must show `127.0.0.1:` (or `[::1]:`), never `*:`.

## 2. From my phone, over the tailnet

The phone cannot reach `127.0.0.1` on the Mac, so both servers go through
`tailscale serve` on the Mac's tailnet name, on two HTTPS ports:

| URL on the tailnet | Proxies to |
|---|---|
| `https://<mac>.<tailnet>.ts.net` (port 443) | frontend `http://127.0.0.1:3000` |
| `https://<mac>.<tailnet>.ts.net:8443` | backend `http://127.0.0.1:8000` |

Find the name with `tailscale status` (or the admin console → Machines). Below,
`MAC=<mac>.<tailnet>.ts.net`.

1. Start the backend with the tailnet origin:
   ```bash
   cd backend && FRONTEND_ORIGIN=https://$MAC uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```
2. Start the built frontend pointing at the tailnet backend URL:
   ```bash
   cd frontend && HOST=127.0.0.1 PORT=3000 NUXT_PUBLIC_API_BASE=https://$MAC:8443 node .output/server/index.mjs
   ```
3. Expose both to the tailnet (documented here, not yet run in this project):
   ```bash
   tailscale serve --bg --https=443 http://127.0.0.1:3000
   ```
   ```bash
   tailscale serve --bg --https=8443 http://127.0.0.1:8000
   ```
   If it asks to enable HTTPS certificates for the tailnet, follow its link.
4. Check: `tailscale serve status` should list only those two entries, both
   "tailnet only". Then open `https://$MAC` on the phone (Tailscale app on).

With this setup the Mac must also use `https://$MAC`, because the backend
accepts only that one origin.

Stop exposing:
```bash
tailscale serve reset
```
(or one port: `tailscale serve --https=8443 off`). `--bg` keeps the serve
config across reboots until it is turned off.

### Never
- `tailscale funnel` — that makes it public on the internet.
- Cloudflare Tunnel, port forwarding, or `--host 0.0.0.0`.

### Unverified
- The live feed uses a WebSocket (`wss://$MAC:8443/ws/tasks/...`). The Tailscale
  serve docs do not say whether serve proxies WebSockets. If the feed shows
  `error`, the rest of the UI (task list, files, usage) still works.

## Leaving it running
- One task runs at a time. A task sent while another runs gets status `queued`
  and starts when the earlier ones finish (FIFO). Queued tasks live in memory:
  after a backend restart they stay `queued` until cancelled with the Cancel button.
- Cancel (button, or `POST /tasks/{id}/cancel`) works for queued and running
  tasks. A running task is stopped with the SDK's interrupt; if it has not
  stopped after 15 s, its asyncio task is cancelled.
- `TASKS_DIR/usage.jsonl` gets one line per finished SDK session (fields as the
  SDK returns them). `GET /usage` and the sidebar show today/month totals.
  `total_cost_usd` is the SDK's list-price estimate, not a bill.
- The Mac stops serving when it sleeps.
