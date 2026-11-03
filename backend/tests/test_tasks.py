import json
from datetime import datetime

import pytest

from app import tasks


def test_slugify() -> None:
    assert tasks.slugify("Write output/hello.md with a greeting") == "write-output-hello-md-with-a-g"
    assert tasks.slugify("  Café   déjà vu!! ") == "cafe-deja-vu"
    assert tasks.slugify("你好") == "task"
    assert tasks.slugify("") == "task"
    long = tasks.slugify("a" * 29 + " bbbb")
    assert len(long) <= 30 and not long.endswith("-")


def test_new_task_id_format() -> None:
    task_id = tasks.new_task_id("Hello World", datetime(2026, 11, 3, 21, 14, 0))
    assert task_id == "20261103-211400-hello-world"
    assert tasks.TASK_ID_RE.fullmatch(task_id)


@pytest.mark.parametrize(
    "bad",
    ["", "..", "../etc", "20261103-211400-../x", "20261103-211400-a/b", "spike-20261103-184208",
     "20261103-211400-UPPER", "/abs/20261103-211400-x"],
)
def test_task_dir_rejects_bad_ids(tasks_dir, bad) -> None:
    with pytest.raises(ValueError):
        tasks.task_dir(bad)


def test_create_task_makes_dir_and_manifest(tasks_dir) -> None:
    manifest = tasks.create_task("Write a haiku")
    directory = tasks_dir / manifest["task_id"]
    assert (directory / "output").is_dir()
    on_disk = json.loads((directory / "manifest.json").read_text())
    assert on_disk == manifest
    assert manifest["status"] == "queued"
    assert manifest["text"] == "Write a haiku"
    assert manifest["started_at"] is None and manifest["error"] is None


def test_status_transitions_done(tasks_dir) -> None:
    task_id = tasks.create_task("x")["task_id"]
    assert tasks.set_status(task_id, "running")["started_at"] is not None
    manifest = tasks.set_status(task_id, "done")
    assert manifest["status"] == "done" and manifest["finished_at"] is not None
    assert tasks.read_manifest(task_id)["status"] == "done"


def test_status_transitions_failed_records_error(tasks_dir) -> None:
    task_id = tasks.create_task("x")["task_id"]
    tasks.set_status(task_id, "running")
    manifest = tasks.set_status(task_id, "failed", error="boom")
    assert manifest["status"] == "failed" and manifest["error"] == "boom"


@pytest.mark.parametrize(
    "path",
    [["done"], ["failed"], ["running", "running"], ["running", "done", "running"]],
)
def test_bad_status_transitions_raise(tasks_dir, path) -> None:
    task_id = tasks.create_task("x")["task_id"]
    with pytest.raises(ValueError):
        for status in path:
            tasks.set_status(task_id, status)


def test_list_manifests_newest_first_and_skips_non_tasks(tasks_dir) -> None:
    tasks_dir.mkdir()
    for task_id in ["20261101-000000-old", "20261103-000000-new"]:
        (tasks_dir / task_id).mkdir()
        (tasks_dir / task_id / "manifest.json").write_text(json.dumps({"task_id": task_id}))
    (tasks_dir / "spike-20261103-184208").mkdir()
    ids = [m["task_id"] for m in tasks.list_manifests()]
    assert ids == ["20261103-000000-new", "20261101-000000-old"]
