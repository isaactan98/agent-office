"""Event model, emitter, jsonl file and pub/sub tests. No SDK calls."""

import asyncio
import json
from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from app import events

TASK_ID = "20261103-211400-route-page"


@pytest.fixture
def task_dir(tmp_path):
    return tmp_path.resolve()


@pytest.fixture
def emitter(task_dir):
    return events.EventEmitter(TASK_ID, task_dir)


def valid_event(**overrides) -> dict:
    data = {"seq": 12, "ts": "2026-11-03T21:14:05.123+08:00", "task_id": TASK_ID,
            "agent": "orchestrator", "agent_id": None, "type": "tool_start", "tool": "Write",
            "path": "output/index.html", "summary": "Writing output/index.html"}
    return {**data, **overrides}


# --- schema -----------------------------------------------------------------


def test_plan_example_validates() -> None:
    event = events.Event(**valid_event())
    assert list(json.loads(event.model_dump_json())) == [
        "seq", "ts", "task_id", "agent", "agent_id", "type", "tool", "path", "summary"]


@pytest.mark.parametrize("overrides", [
    {"type": "tool_started"},                  # unknown type
    {"seq": 0},
    {"ts": "2026-11-03T21:14:05.123"},         # no offset
    {"ts": "yesterday"},
    {"task_id": "../etc"},
    {"agent": ""},
    {"path": "/etc/passwd"},
    {"path": "output/../../x"},
    {"path": "~/notes.md"},
    {"extra": "field"},
])
def test_invalid_events_rejected(overrides) -> None:
    with pytest.raises(ValidationError):
        events.Event(**valid_event(**overrides))


def test_missing_field_rejected() -> None:
    data = valid_event()
    del data["agent_id"]
    with pytest.raises(ValidationError):
        events.Event(**data)


# --- emitter ----------------------------------------------------------------


def test_seq_strictly_increasing(emitter) -> None:
    seqs = [emitter.emit("agent_message", f"msg {i}").seq for i in range(5)]
    assert seqs == [1, 2, 3, 4, 5]


def test_appends_one_json_line_per_event(emitter, task_dir) -> None:
    first = emitter.emit("task_started", "Task started")
    second = emitter.emit("tool_start", "Write output/a.md", tool="Write", path="output/a.md")
    lines = (task_dir / "events.jsonl").read_text().splitlines()
    assert [json.loads(line) for line in lines] == [first.model_dump(), second.model_dump()]
    assert events.read_events(task_dir) == [first.model_dump(), second.model_dump()]


def test_timestamp_is_singapore_offset(emitter) -> None:
    ts = datetime.fromisoformat(emitter.emit("task_started", "Task started").ts)
    assert ts.utcoffset() == timedelta(hours=8)


def test_summary_is_one_short_line(emitter) -> None:
    event = emitter.emit("agent_message", "line one\n\nline   two " + "y" * 300)
    assert event.summary.startswith("line one line two ")
    assert len(event.summary) == events.SUMMARY_MAX


def test_invalid_emit_does_not_advance_seq(emitter, task_dir) -> None:
    with pytest.raises(ValidationError):
        emitter.emit("not_a_type", "x")
    assert emitter.emit("task_started", "Task started").seq == 1
    assert len(events.read_events(task_dir)) == 1


def test_read_events_without_file(task_dir) -> None:
    assert events.read_events(task_dir) == []


# --- validate_file ------------------------------------------------------------


def test_validate_file_accepts_emitted_file(emitter, task_dir) -> None:
    emitter.emit("task_started", "Task started")
    emitter.emit("task_done", "Task done")
    checked = events.validate_file(task_dir / "events.jsonl")
    assert [e.type for e in checked] == ["task_started", "task_done"]


def test_validate_file_rejects_non_increasing_seq(task_dir) -> None:
    file = task_dir / "events.jsonl"
    file.write_text("\n".join(json.dumps(valid_event(seq=s)) for s in (1, 2, 2)) + "\n")
    with pytest.raises(ValueError, match="line 3"):
        events.validate_file(file)


def test_validate_file_rejects_bad_line(task_dir) -> None:
    file = task_dir / "events.jsonl"
    file.write_text(json.dumps(valid_event(seq=1)) + "\n" + json.dumps(valid_event(seq=2, type="x")) + "\n")
    with pytest.raises(ValueError, match="line 2"):
        events.validate_file(file)


# --- relative_path ------------------------------------------------------------


def test_relative_path(task_dir) -> None:
    assert events.relative_path("output/a.md", task_dir) == "output/a.md"
    assert events.relative_path(str(task_dir / "output" / "a.md"), task_dir) == "output/a.md"
    assert events.relative_path("output/../summary.md", task_dir) == "summary.md"
    for outside in ["../x.md", "/etc/passwd", "~/x", "", None, 3]:
        assert events.relative_path(outside, task_dir) is None


# --- pub/sub ------------------------------------------------------------------


def test_pubsub_delivers_to_task_subscribers_only(emitter) -> None:
    async def scenario():
        mine_a = events.subscribe(TASK_ID)
        mine_b = events.subscribe(TASK_ID)
        other = events.subscribe("20261103-211400-other")
        try:
            sent = emitter.emit("task_started", "Task started")
            assert await asyncio.wait_for(mine_a.get(), 1) == sent
            assert await asyncio.wait_for(mine_b.get(), 1) == sent
            assert other.empty()
        finally:
            events.unsubscribe(TASK_ID, mine_a)
            events.unsubscribe(TASK_ID, mine_b)
            events.unsubscribe("20261103-211400-other", other)

    asyncio.run(scenario())


def test_pubsub_preserves_order_and_unsubscribe_stops(emitter) -> None:
    queue = events.subscribe(TASK_ID)
    emitter.emit("task_started", "a")
    emitter.emit("task_done", "b")
    events.unsubscribe(TASK_ID, queue)
    emitter.emit("agent_message", "after unsubscribe")
    assert [queue.get_nowait().seq for _ in range(2)] == [1, 2]
    assert queue.empty()
    assert TASK_ID not in events._subscribers
