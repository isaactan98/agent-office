"""Task directories and manifests (see docs/PLAN.md, "Task directory contract")."""

import json
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import TASKS_DIR

SLUG_MAX = 30
TASK_ID_RE = re.compile(r"^\d{8}-\d{6}-[a-z0-9]+(?:-[a-z0-9]+)*$")

# Allowed status changes. Anything else is a bug and raises.
TRANSITIONS = {
    "queued": {"running"},
    "running": {"done", "failed"},
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def slugify(text: str) -> str:
    """ASCII, lowercase, words joined by '-', at most SLUG_MAX chars."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    slug = slug[:SLUG_MAX].strip("-")
    return slug or "task"


def new_task_id(text: str, when: datetime | None = None) -> str:
    when = when or datetime.now()
    return f"{when:%Y%m%d-%H%M%S}-{slugify(text)}"


def task_dir(task_id: str) -> Path:
    """Return TASKS_DIR/<task_id>. Rejects anything that is not a valid task_id."""
    if not TASK_ID_RE.fullmatch(task_id):
        raise ValueError(f"invalid task_id: {task_id!r}")
    return TASKS_DIR / task_id


def _write_manifest(directory: Path, manifest: dict[str, Any]) -> None:
    # Write to a temp file, then rename, so readers never see half a file.
    tmp = directory / "manifest.json.tmp"
    tmp.write_text(json.dumps(manifest, indent=2) + "\n")
    os.replace(tmp, directory / "manifest.json")


def create_task(text: str) -> dict[str, Any]:
    """Create the task directory, output/ and a manifest with status 'queued'."""
    task_id = new_task_id(text)
    directory = task_dir(task_id)
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    directory.mkdir()  # fails if the id already exists
    (directory / "output").mkdir()
    manifest = {
        "task_id": task_id,
        "text": text,
        "status": "queued",
        "agents": {},  # agent name -> number of runs, filled in while the task runs
        "created_at": now_iso(),
        "started_at": None,
        "finished_at": None,
        "error": None,
    }
    _write_manifest(directory, manifest)
    return manifest


def read_manifest(task_id: str) -> dict[str, Any]:
    return json.loads((task_dir(task_id) / "manifest.json").read_text())


def set_status(task_id: str, status: str, error: str | None = None) -> dict[str, Any]:
    manifest = read_manifest(task_id)
    current = manifest["status"]
    if status not in TRANSITIONS.get(current, set()):
        raise ValueError(f"bad status change {current!r} -> {status!r}")
    manifest["status"] = status
    if status == "running":
        manifest["started_at"] = now_iso()
    else:
        manifest["finished_at"] = now_iso()
    if error is not None:
        manifest["error"] = error
    _write_manifest(task_dir(task_id), manifest)
    return manifest


def record_agent_run(task_id: str, agent: str) -> dict[str, Any]:
    """Count one run of `agent` in the manifest's `agents` map."""
    manifest = read_manifest(task_id)
    manifest["agents"][agent] = manifest["agents"].get(agent, 0) + 1
    _write_manifest(task_dir(task_id), manifest)
    return manifest


def list_manifests() -> list[dict[str, Any]]:
    """All task manifests, newest first. Skips dirs that are not tasks (e.g. spikes)."""
    if not TASKS_DIR.is_dir():
        return []
    manifests = []
    for entry in TASKS_DIR.iterdir():
        if TASK_ID_RE.fullmatch(entry.name) and (entry / "manifest.json").is_file():
            manifests.append(read_manifest(entry.name))
    # task_id starts with YYYYMMDD-HHMMSS, so name order is time order.
    return sorted(manifests, key=lambda m: m["task_id"], reverse=True)
