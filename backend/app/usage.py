"""Usage log: one line per finished SDK session in TASKS_DIR/usage.jsonl.

Each line keeps the usage/cost fields the SDK's ResultMessage returns, as they
are. total_cost_usd is the CLI's list-price estimate, not a bill (Pro plan).
"""

import json
import logging
from datetime import datetime
from typing import Any

from claude_agent_sdk import ResultMessage

from app import tasks

log = logging.getLogger(__name__)

FILE_NAME = "usage.jsonl"


def record(task_id: str, result: ResultMessage) -> None:
    """Append one line for a finished session. Never raises."""
    try:
        entry = {
            "task_id": task_id,
            "recorded_at": tasks.now_iso(),  # ours, used for the today/month totals
            "status": tasks.read_manifest(task_id)["status"],  # after the run
            # Below: copied from the SDK result.
            "subtype": result.subtype,
            "duration_ms": result.duration_ms,
            "duration_api_ms": result.duration_api_ms,
            "num_turns": result.num_turns,
            "total_cost_usd": result.total_cost_usd,
            "usage": result.usage,
            "model_usage": result.model_usage,
        }
        tasks.TASKS_DIR.mkdir(parents=True, exist_ok=True)
        with (tasks.TASKS_DIR / FILE_NAME).open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        log.exception("could not write the usage log for %s", task_id)


def read_entries() -> list[dict[str, Any]]:
    file = tasks.TASKS_DIR / FILE_NAME
    if not file.is_file():
        return []
    return [json.loads(line) for line in file.read_text().splitlines() if line.strip()]


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _totals(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Sums over entries. `usage` sums every numeric top-level key of the raw
    usage dicts (token counts); nested or text values are skipped."""
    usage: dict[str, float] = {}
    for entry in entries:
        for key, value in (entry.get("usage") or {}).items():
            if _number(value):
                usage[key] = usage.get(key, 0) + value
    return {
        "sessions": len(entries),
        "duration_ms": sum(e["duration_ms"] for e in entries if _number(e.get("duration_ms"))),
        "num_turns": sum(e["num_turns"] for e in entries if _number(e.get("num_turns"))),
        "total_cost_usd": sum(
            e["total_cost_usd"] for e in entries if _number(e.get("total_cost_usd"))
        ),
        "usage": usage,
    }


def summary(now: datetime | None = None) -> dict[str, Any]:
    """Totals for today and this month (local time, like task ids)."""
    now = now or datetime.now().astimezone()
    today, month = [], []
    for entry in read_entries():
        when = datetime.fromisoformat(entry["recorded_at"]).astimezone(now.tzinfo)
        if (when.year, when.month) == (now.year, now.month):
            month.append(entry)
            if when.day == now.day:
                today.append(entry)
    return {"today": _totals(today), "month": _totals(month)}
