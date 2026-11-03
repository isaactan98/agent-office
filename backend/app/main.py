import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app import events, runner, tasks

app = FastAPI(title="agent-office")

# The one task currently running, if any. One task at a time.
_running: asyncio.Task | None = None


class TaskIn(BaseModel):
    text: str = Field(min_length=1)


def _is_busy() -> bool:
    return _running is not None and not _running.done()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/tasks")
async def create_task(body: TaskIn) -> dict[str, str]:
    global _running
    if _is_busy():
        raise HTTPException(status_code=409, detail="a task is already running")
    manifest = tasks.create_task(body.text)
    _running = asyncio.create_task(runner.run_task(manifest["task_id"]))
    return {"task_id": manifest["task_id"], "status": manifest["status"]}


@app.get("/tasks")
def list_tasks() -> list[dict[str, Any]]:
    return tasks.list_manifests()


def _existing_task_dir(task_id: str) -> Path:
    """The task's directory. 400 for a malformed id, 404 if there is no such task."""
    try:
        directory = tasks.task_dir(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid task_id")
    if not (directory / "manifest.json").is_file():
        raise HTTPException(status_code=404, detail="task not found")
    return directory


@app.get("/tasks/{task_id}")
def get_task(task_id: str) -> dict[str, Any]:
    _existing_task_dir(task_id)
    return tasks.read_manifest(task_id)


@app.get("/tasks/{task_id}/events")
def get_task_events(task_id: str) -> list[dict[str, Any]]:
    return events.read_events(_existing_task_dir(task_id))
