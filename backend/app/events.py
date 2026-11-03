"""Task events (see docs/PLAN.md, "Event schema").

Each task gets one EventEmitter. It numbers events, appends them to
TASKS_DIR/<task_id>/events.jsonl and publishes them to in-memory subscribers.

Check a file: uv run python -m app.events <path/to/events.jsonl>
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.tasks import TASK_ID_RE

SGT = ZoneInfo("Asia/Singapore")
SUMMARY_MAX = 120
DEFAULT_AGENT = "orchestrator"

EventType = Literal[
    "task_queued",
    "task_started",
    "agent_message",
    "tool_start",
    "tool_end",
    "tool_denied",
    "subagent_start",
    "subagent_stop",
    "task_done",
    "task_failed",
]


class Event(BaseModel):
    """One event. Field names and order match the PLAN.md schema."""

    model_config = ConfigDict(extra="forbid")

    seq: int = Field(ge=1)
    ts: str
    task_id: str = Field(pattern=TASK_ID_RE.pattern)
    agent: str = Field(min_length=1)
    agent_id: str | None
    type: EventType
    tool: str | None
    path: str | None
    summary: str

    @field_validator("ts")
    @classmethod
    def _ts_has_offset(cls, value: str) -> str:
        if datetime.fromisoformat(value).tzinfo is None:
            raise ValueError("ts must include a UTC offset")
        return value

    @field_validator("path")
    @classmethod
    def _path_is_relative(cls, value: str | None) -> str | None:
        if value is not None and (value.startswith(("/", "~")) or ".." in Path(value).parts):
            raise ValueError("path must be relative to the task dir")
        return value


def now_sgt() -> str:
    return datetime.now(SGT).isoformat(timespec="milliseconds")


def one_line(text: str, limit: int = SUMMARY_MAX) -> str:
    """Collapse whitespace and cut to `limit` chars."""
    return " ".join(text.split())[:limit]


def relative_path(path: Any, task_dir: Path) -> str | None:
    """`path` (relative to task_dir, or absolute) as a task-relative path, or None
    if it is not a string or points outside task_dir. Does not follow symlinks:
    this names the file for the UI, the path guard does the security check."""
    if not isinstance(path, str) or not path or path.startswith("~"):
        return None
    root = task_dir.resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        return Path(os.path.normpath(candidate)).relative_to(root).as_posix()
    except ValueError:
        return None


# --- in-memory pub/sub (one subscriber list per task) ----------------------

_subscribers: dict[str, list[asyncio.Queue]] = {}


def subscribe(task_id: str) -> asyncio.Queue:
    """Return a queue that receives every event emitted for task_id from now on."""
    queue: asyncio.Queue = asyncio.Queue()
    _subscribers.setdefault(task_id, []).append(queue)
    return queue


def unsubscribe(task_id: str, queue: asyncio.Queue) -> None:
    queues = _subscribers.get(task_id, [])
    if queue in queues:
        queues.remove(queue)
    if not queues:
        _subscribers.pop(task_id, None)


def publish(event: Event) -> None:
    for queue in list(_subscribers.get(event.task_id, [])):
        queue.put_nowait(event)


# --- emitter ---------------------------------------------------------------


class EventEmitter:
    """Numbers, stores and publishes the events of one task run."""

    def __init__(self, task_id: str, task_dir: Path) -> None:
        self.task_id = task_id
        self.file = task_dir / "events.jsonl"
        self._seq = 0

    def emit(
        self,
        type: EventType,
        summary: str,
        *,
        agent: str = DEFAULT_AGENT,
        agent_id: str | None = None,
        tool: str | None = None,
        path: str | None = None,
    ) -> Event:
        seq = self._seq + 1
        event = Event(
            seq=seq,
            ts=now_sgt(),
            task_id=self.task_id,
            agent=agent,
            agent_id=agent_id,
            type=type,
            tool=tool,
            path=path,
            summary=one_line(summary),
        )
        with self.file.open("a") as f:
            f.write(event.model_dump_json() + "\n")
        self._seq = seq  # only advance once the event is stored, so seq has no gaps
        publish(event)
        return event


def read_events(task_dir: Path) -> list[dict[str, Any]]:
    """All events of a task, in file order. [] if there is no events.jsonl yet."""
    file = task_dir / "events.jsonl"
    if not file.is_file():
        return []
    return [json.loads(line) for line in file.read_text().splitlines() if line.strip()]


def validate_file(file: Path) -> list[Event]:
    """Parse every line against the schema and check seq is strictly increasing.
    Raises ValueError naming the first bad line."""
    result: list[Event] = []
    for number, line in enumerate(file.read_text().splitlines(), start=1):
        try:
            event = Event.model_validate_json(line)
        except ValueError as exc:
            raise ValueError(f"line {number}: {exc}") from exc
        if result and event.seq <= result[-1].seq:
            raise ValueError(f"line {number}: seq {event.seq} is not greater than {result[-1].seq}")
        result.append(event)
    return result


if __name__ == "__main__":
    checked = validate_file(Path(sys.argv[1]))
    print(f"OK: {len(checked)} events, seq strictly increasing")
    if checked:
        print(f"first: {checked[0].type}, last: {checked[-1].type}")
