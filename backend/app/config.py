"""Runtime settings, read from environment variables."""

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent

# Where each task gets its own directory. Default: <repo>/tasks
TASKS_DIR = Path(os.environ.get("TASKS_DIR") or BACKEND_DIR.parent / "tasks").resolve()

# Bind to localhost only. Remote access goes through `tailscale serve`, never a public URL.
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))
