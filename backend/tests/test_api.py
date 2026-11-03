"""Endpoint tests. runner.run_task is replaced, so the real SDK is never called."""

import asyncio
import json
import os
import time
from collections import deque

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import config, events, main, runner, tasks, usage


@pytest.fixture
def client(tasks_dir, monkeypatch):
    calls = []

    async def fake_run_task(task_id: str) -> None:
        calls.append(task_id)

    monkeypatch.setattr(runner, "run_task", fake_run_task)
    monkeypatch.setattr(main, "_running", None)
    monkeypatch.setattr(main, "_worker", None)
    monkeypatch.setattr(main, "_pending", deque())
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
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


def wait_until(condition, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


@pytest.fixture
def gated(client, monkeypatch):
    """run_task replaced by one that runs until `gate.open` is set, like a real
    task (queued -> running -> done). `started` lists task_ids in run order."""

    class Gate:
        open = False
        started: list[str] = []

    gate = Gate()

    async def gated_run_task(task_id: str) -> None:
        gate.started.append(task_id)
        tasks.set_status(task_id, "running")
        while not gate.open:
            await asyncio.sleep(0.01)
        tasks.set_status(task_id, "done")

    monkeypatch.setattr(runner, "run_task", gated_run_task)
    return gate


def status_of(client, task_id: str) -> str:
    return client.get(f"/tasks/{task_id}").json()["status"]


def test_second_task_is_queued_then_runs(client, gated) -> None:
    first = client.post("/tasks", json={"text": "first"}).json()
    second = client.post("/tasks", json={"text": "second"})
    assert second.status_code == 200 and second.json()["status"] == "queued"
    second_id = second.json()["task_id"]
    wait_until(lambda: gated.started == [first["task_id"]])
    assert status_of(client, first["task_id"]) == "running"
    assert status_of(client, second_id) == "queued"
    gated.open = True
    wait_until(lambda: status_of(client, second_id) == "done")
    assert gated.started == [first["task_id"], second_id]  # FIFO


def test_tasks_run_in_fifo_order(client, gated) -> None:
    ids = [client.post("/tasks", json={"text": f"t{i}"}).json()["task_id"] for i in range(3)]
    gated.open = True
    wait_until(lambda: len(gated.started) == 3)
    assert gated.started == ids


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


# --- cancel -----------------------------------------------------------------


def test_cancel_queued_task(client, gated, tasks_dir) -> None:
    first = client.post("/tasks", json={"text": "first"}).json()["task_id"]
    second = client.post("/tasks", json={"text": "second"}).json()["task_id"]
    response = client.post(f"/tasks/{second}/cancel")
    assert response.status_code == 200
    assert response.json() == {"task_id": second, "status": "cancelled"}
    manifest = tasks.read_manifest(second)
    assert manifest["status"] == "cancelled" and manifest["started_at"] is None
    assert [e["type"] for e in events.read_events(tasks_dir / second)] == ["task_failed"]
    gated.open = True
    wait_until(lambda: status_of(client, first) == "done")
    time.sleep(0.1)
    assert gated.started == [first]  # the cancelled task never ran


def test_cancel_queued_task_left_from_before_restart(client) -> None:
    """A manifest still 'queued' that this process does not know about."""
    task_id = tasks.create_task("orphan")["task_id"]
    assert client.post(f"/tasks/{task_id}/cancel").json()["status"] == "cancelled"


def interruptible_session(ignore_interrupt: bool = False):
    async def session(prompt, options, client):
        if ignore_interrupt:
            await asyncio.Event().wait()
        await client.interrupted.wait()
        from claude_agent_sdk import ResultMessage
        yield ResultMessage(subtype="error_during_execution", duration_ms=5, duration_api_ms=4,
                            is_error=True, num_turns=1, session_id="s", usage={"input_tokens": 7})
    return session


@pytest.fixture
def real_runner(client, monkeypatch):
    """Use the real runner.run_task (with a fake SDK client) instead of the fake."""
    monkeypatch.setattr(runner, "run_task", RUN_TASK)


RUN_TASK = runner.run_task


def test_cancel_running_task_interrupts(client, real_runner, fake_sdk, tasks_dir) -> None:
    fake = fake_sdk(interruptible_session())
    task_id = client.post("/tasks", json={"text": "long"}).json()["task_id"]
    wait_until(lambda: task_id in runner._clients)
    response = client.post(f"/tasks/{task_id}/cancel")
    assert response.json() == {"task_id": task_id, "status": "cancelled"}
    assert fake.instances[0].interrupted.is_set()
    assert events.read_events(tasks_dir / task_id)[-1]["summary"] == "Task cancelled"
    assert [e["status"] for e in usage.read_entries()] == ["cancelled"]


def test_cancel_running_task_falls_back_to_asyncio_cancel(
    client, real_runner, fake_sdk, monkeypatch
) -> None:
    monkeypatch.setattr(main, "CANCEL_WAIT_SECONDS", 0.2)
    fake_sdk(interruptible_session(ignore_interrupt=True))
    task_id = client.post("/tasks", json={"text": "stuck"}).json()["task_id"]
    wait_until(lambda: task_id in runner._clients)
    assert client.post(f"/tasks/{task_id}/cancel").json()["status"] == "cancelled"


def test_cancel_running_then_next_task_runs(client, real_runner, fake_sdk) -> None:
    fake_sdk(interruptible_session())
    first = client.post("/tasks", json={"text": "first"}).json()["task_id"]
    second = client.post("/tasks", json={"text": "second"}).json()["task_id"]
    wait_until(lambda: first in runner._clients)
    client.post(f"/tasks/{first}/cancel")
    wait_until(lambda: second in runner._clients)
    assert status_of(client, second) == "running"
    client.post(f"/tasks/{second}/cancel")
    assert status_of(client, second) == "cancelled"


@pytest.mark.parametrize("status", ["done", "failed"])
def test_cancel_finished_task_is_409(client, status) -> None:
    task_id = tasks.create_task("x")["task_id"]
    tasks.set_status(task_id, "running")
    tasks.set_status(task_id, status)
    assert client.post(f"/tasks/{task_id}/cancel").status_code == 409


def test_cancel_stale_running_task_is_409(client) -> None:
    """'running' in the manifest but not running in this process (after a crash)."""
    task_id = tasks.create_task("x")["task_id"]
    tasks.set_status(task_id, "running")
    assert client.post(f"/tasks/{task_id}/cancel").status_code == 409


def test_ws_for_queued_task_stays_open_until_cancelled(client, gated) -> None:
    client.post("/tasks", json={"text": "first"})
    second = client.post("/tasks", json={"text": "second"}).json()["task_id"]
    with client.websocket_connect(f"/ws/tasks/{second}") as ws:
        time.sleep(main.WS_POLL_SECONDS + 0.5)  # a non-active task would be closed by now
        client.post(f"/tasks/{second}/cancel")
        received = _receive_all(ws)
    assert [(e["type"], e["summary"]) for e in received] == [
        ("task_failed", "Task cancelled before it started")]
    gated.open = True


# --- daily cap --------------------------------------------------------------


def test_daily_cap_429(client, monkeypatch) -> None:
    monkeypatch.setattr(config, "DAILY_TASK_CAP", 2)
    assert client.post("/tasks", json={"text": "a"}).status_code == 200
    assert client.post("/tasks", json={"text": "b"}).status_code == 200
    response = client.post("/tasks", json={"text": "c"})
    assert response.status_code == 429
    assert "daily task cap reached (2 tasks today)" in response.json()["detail"]
    assert len(tasks.list_manifests()) == 2  # nothing was created


def test_daily_cap_skips_cancelled_before_start_and_other_days(client, monkeypatch, tasks_dir) -> None:
    monkeypatch.setattr(config, "DAILY_TASK_CAP", 1)
    old = tasks_dir / "20200101-000000-old"
    old.mkdir(parents=True)
    (old / "manifest.json").write_text(json.dumps(
        {"task_id": old.name, "status": "done", "started_at": "x"}))
    task_id = tasks.create_task("never ran")["task_id"]
    tasks.set_status(task_id, "cancelled")
    assert client.post("/tasks", json={"text": "a"}).status_code == 200
    assert client.post("/tasks", json={"text": "b"}).status_code == 429


# --- usage ------------------------------------------------------------------


def write_usage(tasks_dir, entries) -> None:
    tasks_dir.mkdir(parents=True, exist_ok=True)
    with (tasks_dir / "usage.jsonl").open("a") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def usage_entry(recorded_at: str, **kw) -> dict:
    return {"task_id": "20261104-100000-x", "recorded_at": recorded_at, "status": "done",
            "subtype": "success", "duration_ms": 1000, "duration_api_ms": 900, "num_turns": 2,
            "total_cost_usd": 0.5, "usage": {"input_tokens": 10, "output_tokens": 4,
            "service_tier": "standard", "server_tool_use": {"web_search_requests": 0}},
            "model_usage": None, **kw}


def test_usage_empty(client) -> None:
    body = client.get("/usage").json()
    assert body["today"] == {"sessions": 0, "duration_ms": 0, "num_turns": 0,
                             "total_cost_usd": 0, "usage": {}}
    assert body["daily_task_cap"] == config.DAILY_TASK_CAP
    assert body["tasks_created_today"] == 0


def test_usage_totals_today_and_month(client, tasks_dir) -> None:
    from datetime import datetime, timedelta
    now = datetime.now().astimezone()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month = month_start - timedelta(days=1)
    other_day = now - timedelta(days=1) if now.day > 1 else None
    entries = [usage_entry(now.isoformat()), usage_entry(now.isoformat(), num_turns=5,
               total_cost_usd=None, usage={"input_tokens": 1})]
    entries.append(usage_entry(last_month.isoformat(), duration_ms=99999))
    if other_day:
        entries.append(usage_entry(other_day.isoformat(), duration_ms=500))
    write_usage(tasks_dir, entries)
    body = client.get("/usage").json()
    assert body["today"] == {"sessions": 2, "duration_ms": 2000, "num_turns": 7,
                             "total_cost_usd": 0.5,
                             "usage": {"input_tokens": 11, "output_tokens": 4}}
    month = body["month"]
    assert month["sessions"] == (3 if other_day else 2)
    assert month["duration_ms"] == (2500 if other_day else 2000)


def test_usage_matches_runner_log(client, real_runner, fake_sdk, tasks_dir) -> None:
    """End to end: a task run (fake SDK) appends to usage.jsonl, /usage sums it."""
    from claude_agent_sdk import ResultMessage

    async def session(prompt, options, client):
        yield ResultMessage(subtype="success", duration_ms=1500, duration_api_ms=1400,
                            is_error=False, num_turns=4, session_id="s", total_cost_usd=0.03,
                            usage={"input_tokens": 20, "output_tokens": 8}, result="ok")

    fake_sdk(session)
    for text in ("a", "b"):
        task_id = client.post("/tasks", json={"text": text}).json()["task_id"]
        wait_until(lambda: status_of(client, task_id) == "done")
    lines = [json.loads(l) for l in (tasks_dir / "usage.jsonl").read_text().splitlines()]
    today = client.get("/usage").json()["today"]
    assert today["sessions"] == len(lines) == 2
    assert today["duration_ms"] == sum(l["duration_ms"] for l in lines) == 3000
    assert today["num_turns"] == 8
    assert today["total_cost_usd"] == pytest.approx(0.06)
    assert today["usage"] == {"input_tokens": 40, "output_tokens": 16}


# --- startup ----------------------------------------------------------------


def test_startup_refuses_with_api_key(tasks_dir, monkeypatch) -> None:
    monkeypatch.setitem(os.environ, "ANTHROPIC_API_KEY", "x")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY is set"):
        with TestClient(main.app):
            pass


def test_startup_error_does_not_print_the_key(tasks_dir, monkeypatch) -> None:
    monkeypatch.setitem(os.environ, "ANTHROPIC_API_KEY", "sk-should-never-appear")
    with pytest.raises(RuntimeError) as info:
        with TestClient(main.app):
            pass
    assert "sk-should-never-appear" not in str(info.value)


# --- traversal: every endpoint that takes a task_id or path ----------------

BAD_TASK_IDS = [
    "..",
    "%2E%2E",
    "..%2F..%2Fetc",
    "%2E%2E%2F%2E%2E%2Fetc",
    "20261103-211400-x%2F..%2F..",
    "%2Fetc%2Fpasswd",
    "~",
    "spike-20261103-184208",
    "20261103-211400-A",
    "20261103-211400-x%00",
]

ENDPOINTS = [
    ("GET", "/tasks/{id}"),
    ("GET", "/tasks/{id}/events"),
    ("GET", "/tasks/{id}/files"),
    ("GET", "/tasks/{id}/files/output/plan.md"),
    ("POST", "/tasks/{id}/cancel"),
]


@pytest.mark.parametrize("method,template", ENDPOINTS)
@pytest.mark.parametrize("bad", BAD_TASK_IDS)
def test_bad_task_id_rejected_everywhere(client, method, template, bad) -> None:
    response = client.request(method, template.format(id=bad))
    assert response.status_code in (400, 404)


@pytest.mark.parametrize("bad", BAD_TASK_IDS)
def test_ws_bad_task_id_rejected(client, bad) -> None:
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws/tasks/{bad}") as ws:
            ws.receive_json()


@pytest.fixture
def symlinked_task(client, tasks_dir, tmp_path):
    """A dir outside TASKS_DIR that looks like a task, linked in under a valid id."""
    outside = tmp_path / "outside"
    (outside / "output").mkdir(parents=True)
    (outside / "manifest.json").write_text(json.dumps({"task_id": "x", "status": "done"}))
    (outside / "output" / "plan.md").write_text("TOP SECRET")
    tasks_dir.mkdir(parents=True, exist_ok=True)
    link = tasks_dir / "20261103-211400-linked"
    link.symlink_to(outside, target_is_directory=True)
    return link.name


@pytest.mark.parametrize("method,template", ENDPOINTS)
def test_symlinked_task_dir_is_404(client, symlinked_task, method, template) -> None:
    response = client.request(method, template.format(id=symlinked_task))
    assert response.status_code == 404
    assert "TOP SECRET" not in response.text


def test_ws_symlinked_task_dir_rejected(client, symlinked_task) -> None:
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws/tasks/{symlinked_task}") as ws:
            ws.receive_json()
