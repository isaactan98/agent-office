"""Endpoint tests. runner.run_task is replaced, so the real SDK is never called."""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import config, events, main, runner, tasks


@pytest.fixture
def client(tasks_dir, monkeypatch):
    calls = []

    async def fake_run_task(task_id: str) -> None:
        calls.append(task_id)

    monkeypatch.setattr(runner, "run_task", fake_run_task)
    monkeypatch.setattr(main, "_running", None)
    with TestClient(main.app) as c:
        c.calls = calls
        yield c


def test_post_creates_task(client) -> None:
    response = client.post("/tasks", json={"text": "Say hi"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert tasks.TASK_ID_RE.fullmatch(body["task_id"])
    assert client.get(f"/tasks/{body['task_id']}").json()["text"] == "Say hi"


def test_post_rejects_empty_text(client) -> None:
    assert client.post("/tasks", json={"text": ""}).status_code == 422


def test_post_409_while_running(client, monkeypatch) -> None:
    class Busy:
        def done(self) -> bool:
            return False

    monkeypatch.setattr(main, "_running", Busy())
    assert client.post("/tasks", json={"text": "second"}).status_code == 409


def test_list_tasks(client) -> None:
    assert client.get("/tasks").json() == []
    task_id = client.post("/tasks", json={"text": "one"}).json()["task_id"]
    assert [m["task_id"] for m in client.get("/tasks").json()] == [task_id]


@pytest.mark.parametrize("bad", ["..%2F..%2Fetc", "spike-20261103-184208", "20261103-211400-A"])
def test_get_task_rejects_bad_id(client, bad) -> None:
    assert client.get(f"/tasks/{bad}").status_code in (400, 404)


def test_get_task_invalid_format_is_400(client) -> None:
    assert client.get("/tasks/not-a-task").status_code == 400


def test_get_task_missing_is_404(client) -> None:
    assert client.get("/tasks/20261103-211400-missing").status_code == 404


def test_get_events(client, tasks_dir) -> None:
    task_id = client.post("/tasks", json={"text": "one"}).json()["task_id"]
    assert client.get(f"/tasks/{task_id}/events").json() == []
    emitter = events.EventEmitter(task_id, tasks_dir / task_id)
    emitter.emit("task_started", "Task started")
    emitter.emit("task_done", "Task done")
    body = client.get(f"/tasks/{task_id}/events").json()
    assert [e["seq"] for e in body] == [1, 2]
    assert [e["type"] for e in body] == ["task_started", "task_done"]


def test_get_events_bad_or_missing_task(client) -> None:
    assert client.get("/tasks/not-a-task/events").status_code == 400
    assert client.get("/tasks/20261103-211400-missing/events").status_code == 404


# --- files ------------------------------------------------------------------


@pytest.fixture
def task_with_files(client, tasks_dir, tmp_path):
    """A task with a few output files, a secret file just outside TASKS_DIR and
    a symlink inside the task dir that points at it."""
    task_id = client.post("/tasks", json={"text": "files"}).json()["task_id"]
    directory = tasks_dir / task_id
    (directory / "output" / "plan.md").write_text("# Plan\n- cafe\n")
    (directory / "output" / "sub").mkdir()
    (directory / "output" / "sub" / "x.txt").write_text("x")
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP SECRET")
    (directory / "output" / "link.txt").symlink_to(secret)
    return task_id


def test_list_files(client, task_with_files) -> None:
    files = client.get(f"/tasks/{task_with_files}/files").json()
    by_path = {f["path"]: f["size"] for f in files}
    assert by_path["output/plan.md"] == len("# Plan\n- cafe\n")
    assert by_path["output/sub/x.txt"] == 1
    assert "manifest.json" in by_path
    assert "output/link.txt" not in by_path  # symlink to outside the task dir
    assert [f["path"] for f in files] == sorted(by_path)


def test_list_files_bad_or_missing_task(client) -> None:
    assert client.get("/tasks/not-a-task/files").status_code == 400
    assert client.get("/tasks/20261103-211400-missing/files").status_code == 404


def test_get_file(client, task_with_files) -> None:
    response = client.get(f"/tasks/{task_with_files}/files/output/plan.md")
    assert response.status_code == 200
    assert response.text == "# Plan\n- cafe\n"
    assert response.headers["content-type"].startswith("text/plain")


@pytest.mark.parametrize(
    "bad",
    [
        "..%2F..%2FCLAUDE.md",
        "..%2F..%2Fsecret.txt",  # exists: tmp_path/secret.txt
        "output%2F..%2F..%2F..%2Fsecret.txt",
        "%2Fetc%2Fpasswd",
        "~%2F.zshrc",
        "output/link.txt",  # symlink pointing outside
    ],
)
def test_get_file_outside_task_dir_is_400(client, task_with_files, bad) -> None:
    response = client.get(f"/tasks/{task_with_files}/files/{bad}")
    assert response.status_code == 400
    assert "TOP SECRET" not in response.text


def test_get_file_missing_or_directory_is_404(client, task_with_files) -> None:
    assert client.get(f"/tasks/{task_with_files}/files/output/nope.md").status_code == 404
    assert client.get(f"/tasks/{task_with_files}/files/output").status_code == 404


def test_get_file_too_big_is_413(client, task_with_files, tasks_dir) -> None:
    (tasks_dir / task_with_files / "output" / "big.txt").write_text("a" * main.MAX_FILE_BYTES)
    assert client.get(f"/tasks/{task_with_files}/files/output/big.txt").status_code == 413


@pytest.mark.parametrize("data", [b"PNG\x00\x01", b"\xff\xfe\xfa"])
def test_get_file_binary_is_415(client, task_with_files, tasks_dir, data) -> None:
    (tasks_dir / task_with_files / "output" / "bin").write_bytes(data)
    assert client.get(f"/tasks/{task_with_files}/files/output/bin").status_code == 415


def test_get_file_bad_or_missing_task(client) -> None:
    assert client.get("/tasks/not-a-task/files/a.md").status_code == 400
    assert client.get("/tasks/20261103-211400-missing/files/a.md").status_code == 404


# --- CORS -------------------------------------------------------------------


def test_cors_allows_frontend_origin(client) -> None:
    response = client.options(
        "/tasks",
        headers={
            "Origin": config.FRONTEND_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == config.FRONTEND_ORIGIN


def test_cors_ignores_other_origins(client) -> None:
    response = client.get("/tasks", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in response.headers


# --- WebSocket --------------------------------------------------------------


def _receive_all(ws) -> list[dict]:
    """Every message until the server closes the socket."""
    received = []
    with pytest.raises(WebSocketDisconnect):
        while True:
            received.append(ws.receive_json())
    return received


def _wait_unsubscribed(task_id: str) -> None:
    deadline = time.monotonic() + 2
    while task_id in events._subscribers and time.monotonic() < deadline:
        time.sleep(0.01)
    assert task_id not in events._subscribers


def test_ws_replays_finished_task_then_closes(client, tasks_dir) -> None:
    task_id = client.post("/tasks", json={"text": "done"}).json()["task_id"]
    emitter = events.EventEmitter(task_id, tasks_dir / task_id)
    emitter.emit("task_started", "Task started")
    emitter.emit("task_done", "Task done")
    with client.websocket_connect(f"/ws/tasks/{task_id}") as ws:
        received = _receive_all(ws)
    assert [e["type"] for e in received] == ["task_started", "task_done"]
    _wait_unsubscribed(task_id)


def test_ws_streams_live_events_until_done(client, tasks_dir, monkeypatch) -> None:
    async def fake_run_task(task_id: str) -> None:
        emitter = events.EventEmitter(task_id, tasks_dir / task_id)
        emitter.emit("task_started", "Task started")  # before the socket: replayed
        while task_id not in events._subscribers:
            await asyncio.sleep(0.01)
        emitter.emit("tool_start", "Write output/a.md", tool="Write", path="output/a.md")
        emitter.emit("task_done", "Task done")

    monkeypatch.setattr(runner, "run_task", fake_run_task)
    task_id = client.post("/tasks", json={"text": "live"}).json()["task_id"]
    events_file = tasks_dir / task_id / "events.jsonl"
    while not events_file.exists():
        time.sleep(0.01)
    with client.websocket_connect(f"/ws/tasks/{task_id}") as ws:
        received = _receive_all(ws)
    assert [e["seq"] for e in received] == [1, 2, 3]
    assert [e["type"] for e in received] == ["task_started", "tool_start", "task_done"]
    assert received[1]["path"] == "output/a.md"
    _wait_unsubscribed(task_id)


def test_ws_closes_when_task_is_not_running(client, tasks_dir) -> None:
    """A task left 'running' by a crash never gets task_done: replay, then close."""
    task_id = client.post("/tasks", json={"text": "stale"}).json()["task_id"]
    events.EventEmitter(task_id, tasks_dir / task_id).emit("task_started", "Task started")
    with client.websocket_connect(f"/ws/tasks/{task_id}") as ws:
        received = _receive_all(ws)
    assert [e["type"] for e in received] == ["task_started"]


def test_ws_allows_frontend_origin(client, tasks_dir) -> None:
    task_id = client.post("/tasks", json={"text": "o"}).json()["task_id"]
    events.EventEmitter(task_id, tasks_dir / task_id).emit("task_done", "Task done")
    headers = {"Origin": config.FRONTEND_ORIGIN}
    with client.websocket_connect(f"/ws/tasks/{task_id}", headers=headers) as ws:
        assert [e["type"] for e in _receive_all(ws)] == ["task_done"]


def test_ws_rejects_other_origin(client) -> None:
    task_id = client.post("/tasks", json={"text": "o"}).json()["task_id"]
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/ws/tasks/{task_id}", headers={"Origin": "http://evil.example"}
        ) as ws:
            ws.receive_json()


@pytest.mark.parametrize("bad", ["not-a-task", "20261103-211400-missing"])
def test_ws_rejects_bad_or_missing_task(client, bad) -> None:
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws/tasks/{bad}") as ws:
            ws.receive_json()
