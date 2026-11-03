import asyncio
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app import config, events, runner, tasks

app = FastAPI(title="agent-office")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.FRONTEND_ORIGIN],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

# Files bigger than this are not served by GET /tasks/{id}/files/{path}.
MAX_FILE_BYTES = 1024 * 1024
TERMINAL_EVENTS = {"task_done", "task_failed"}
# How often the WebSocket re-checks whether its task is still running.
WS_POLL_SECONDS = 1.0

# The one task currently running, if any. One task at a time.
_running: asyncio.Task | None = None


class TaskIn(BaseModel):
    text: str = Field(min_length=1)


def _is_busy() -> bool:
    return _running is not None and not _running.done()


def _is_running(task_id: str) -> bool:
    """True if task_id is the task running in this process right now."""
    return _is_busy() and _running.get_name() == task_id


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/tasks")
async def create_task(body: TaskIn) -> dict[str, str]:
    global _running
    if _is_busy():
        raise HTTPException(status_code=409, detail="a task is already running")
    manifest = tasks.create_task(body.text)
    # Named after the task so _is_running() can tell which task it is.
    _running = asyncio.create_task(runner.run_task(manifest["task_id"]), name=manifest["task_id"])
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


@app.get("/tasks/{task_id}/files")
def list_task_files(task_id: str) -> list[dict[str, Any]]:
    """Every file under the task dir: path relative to it, and size in bytes."""
    directory = _existing_task_dir(task_id)
    files = []
    # os.walk does not descend into symlinked dirs; symlinked files that point
    # outside the task dir are skipped by is_path_inside.
    for dirpath, _dirnames, filenames in os.walk(directory):
        for name in filenames:
            path = Path(dirpath) / name
            if path.is_file() and runner.is_path_inside(str(path), directory):
                files.append(
                    {"path": path.relative_to(directory).as_posix(), "size": path.stat().st_size}
                )
    return sorted(files, key=lambda f: f["path"])


@app.get("/tasks/{task_id}/files/{file_path:path}", response_class=PlainTextResponse)
def get_task_file(task_id: str, file_path: str) -> str:
    """A text file under the task dir, if it is UTF-8 text and under MAX_FILE_BYTES."""
    directory = _existing_task_dir(task_id)
    # Same check as the agents' path guard: handles .., absolute paths and symlinks.
    if not runner.is_path_inside(file_path, directory):
        raise HTTPException(status_code=400, detail="path is outside the task directory")
    target = (directory / file_path).resolve()
    if not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    with target.open("rb") as f:
        data = f.read(MAX_FILE_BYTES)  # read at most the limit, even if the file grows
    if len(data) >= MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="file is 1 MB or larger")
    if b"\0" in data:
        raise HTTPException(status_code=415, detail="not a text file")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=415, detail="not a text file")


@app.websocket("/ws/tasks/{task_id}")
async def task_events_ws(websocket: WebSocket, task_id: str) -> None:
    """Send the task's past events, then new ones as they happen. Closes after
    task_done/task_failed, or once the task is not running and nothing is left."""
    # Browsers do not apply CORS to WebSockets, so check the origin here.
    # No Origin header means a non-browser client (curl, tests): allowed.
    origin = websocket.headers.get("origin")
    if origin is not None and origin != config.FRONTEND_ORIGIN:
        await websocket.close(code=1008)
        return
    try:
        directory = _existing_task_dir(task_id)
    except HTTPException:
        await websocket.close(code=1008)
        return

    # Subscribe before reading events.jsonl, so no event falls in between.
    # Events seen in both are skipped by seq.
    queue = events.subscribe(task_id)
    try:
        await websocket.accept()
        last_seq = 0
        for event in events.read_events(directory):
            await websocket.send_json(event)
            last_seq = event["seq"]
            if event["type"] in TERMINAL_EVENTS:
                await websocket.close()
                return
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=WS_POLL_SECONDS)
            except asyncio.TimeoutError:
                if not _is_running(task_id) and queue.empty():
                    break  # nothing more will be emitted for this task
                continue
            if event.seq <= last_seq:
                continue
            await websocket.send_json(event.model_dump(mode="json"))
            last_seq = event.seq
            if event.type in TERMINAL_EVENTS:
                break
        await websocket.close()
    except WebSocketDisconnect:
        pass  # the browser went away
    finally:
        events.unsubscribe(task_id, queue)
