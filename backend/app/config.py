"""Runtime settings, read from environment variables."""

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent

# Where each task gets its own directory. Default: <repo>/tasks
TASKS_DIR = Path(os.environ.get("TASKS_DIR") or BACKEND_DIR.parent / "tasks").resolve()

# Bind to localhost only. Remote access goes through `tailscale serve`, never a public URL.
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))

# The Nuxt dev server. The only origin allowed by CORS and on the WebSocket.
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000")

# At most this many tasks may be created per day (POST /tasks answers 429 after that).
DAILY_TASK_CAP = int(os.environ.get("DAILY_TASK_CAP", "20"))


def check_no_api_key() -> None:
    """Refuse to start if ANTHROPIC_API_KEY is set: usage must go through the Pro login.
    Checks the name only; never reads or prints the value."""
    if "ANTHROPIC_API_KEY" in os.environ:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is set in the environment. agent-office uses the Claude "
            "Pro login only. Unset it and start again."
        )
