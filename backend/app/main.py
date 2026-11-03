import asyncio
import logging
import os
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app import config, events, runner, tasks, usage

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.check_no_api_key()  # raising here stops uvicorn before it serves anything
    yield


app = FastAPI(title="agent-office", lifespan=lifespan)
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

# How long POST /tasks/{id}/cancel waits for a running task to stop before it
# cancels the asyncio task instead.
CANCEL_WAIT_SECONDS = 15.0

# One task runs at a time; the rest wait in _pending (FIFO). _worker runs them in
# order; _running is the run_task of the current one, named after its task_id.
_pending: deque[str] = deque()
_worker: asyncio.Task | None = None
_running: asyncio.Task | None = None


class TaskIn(BaseModel):
    text: str = Field(min_length=1)


def _is_busy() -> bool:
    return _running is not None and not _running.done()


def _is_running(task_id: str) -> bool:
    """True if task_id is the task running in this process right now."""
    return _is_busy() and _running.get_name() == task_id


def _is_active(task_id: str) -> bool:
    """True if task_id is running or waiting in the queue of this process."""
    return _is_running(task_id) or task_id in _pending


async def _work() -> None:
    """Run queued tasks one after another until the queue is empty."""
    global _running
    while _pending:
        task_id = _pending.popleft()
        _running = asyncio.create_task(runner.run_task(task_id), name=task_id)
        # wait() does not raise if run_task fails or is cancelled; the next task runs.
        await asyncio.wait([_running])
        if not _running.cancelled() and _running.exception() is not None:
            log.error("run_task %s raised", task_id, exc_info=_running.exception())


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/tasks")
async def create_task(body: TaskIn) -> dict[str, str]:
    """Create a task with status 'queued'. It runs when the tasks before it are done."""
    global _worker
    if tasks.count_created_today() >= config.DAILY_TASK_CAP:
        raise HTTPException(
            status_code=429,
            detail=f"daily task cap reached ({config.DAILY_TASK_CAP} tasks today). "
            "Try again tomorrow or raise DAILY_TASK_CAP.",
        )
    manifest = tasks.create_task(body.text)
    _pending.append(manifest["task_id"])
    if _worker is None or _worker.done():
        _worker = asyncio.create_task(_work())
    return {"task_id": manifest["task_id"], "status": manifest["status"]}


@app.get("/usage")
def get_usage() -> dict[str, Any]:
    """SDK usage totals for today and this month, from TASKS_DIR/usage.jsonl."""
    return {
        **usage.summary(),
        "daily_task_cap": config.DAILY_TASK_CAP,
        "tasks_created_today": tasks.count_created_today(),
    }


@app.get("/tasks")
def list_tasks() -> list[dict[str, Any]]:
    return tasks.list_manifests()


def _existing_task_dir(task_id: str) -> Path:
    """The task's directory. 400 for a malformed id, 404 if there is no such task."""
    try:
        directory = tasks.task_dir(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid task_id")
    # A symlinked task dir could point anywhere; task dirs are always real dirs.
    if directory.is_symlink() or not (directory / "manifest.json").is_file():
        raise HTTPException(status_code=404, detail="task not found")
    return directory


@app.get("/tasks/{task_id}")
def get_task(task_id: str) -> dict[str, Any]:
    _existing_task_dir(task_id)
    return tasks.read_manifest(task_id)


@app.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str) -> dict[str, str]:
    """Cancel a queued or running task. Answers once it is 'cancelled'."""
    _existing_task_dir(task_id)
    if _is_running(task_id):
        current = _running
        try:
            # Ask the SDK session to stop; run_task then marks the task cancelled.
            await asyncio.wait_for(runner.request_cancel(task_id), CANCEL_WAIT_SECONDS)
            await asyncio.wait([current], timeout=CANCEL_WAIT_SECONDS)
        except Exception:
            log.exception("interrupt failed for %s", task_id)
        if not current.done():  # the session did not stop: cancel the asyncio task
            current.cancel()
            await asyncio.wait([current])
        if tasks.read_manifest(task_id)["status"] == "queued":  # cancelled before it began
            runner.cancel_queued(task_id)
    elif tasks.read_manifest(task_id)["status"] == "queued":
        if task_id in _pending:
            _pending.remove(task_id)
        runner.cancel_queued(task_id)
    else:
        raise HTTPException(status_code=409, detail="task is not queued or running")
    manifest = tasks.read_manifest(task_id)
    return {"task_id": task_id, "status": manifest["status"]}


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
    task_done/task_failed, or once the task is neither running nor queued and
    nothing is left."""
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
                if not _is_active(task_id) and queue.empty():
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
