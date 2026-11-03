"""Endpoint tests. runner.run_task is replaced, so the real SDK is never called."""

import pytest
from fastapi.testclient import TestClient

from app import events, main, runner, tasks


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
