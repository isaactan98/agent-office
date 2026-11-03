"""Path guard and run_task tests. The real SDK is never called."""

import asyncio
import json
import os

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

from app import events, runner, tasks


@pytest.fixture
def task_dir(tmp_path):
    directory = tmp_path / "task"
    (directory / "output").mkdir(parents=True)
    return directory.resolve()


@pytest.fixture
def emitter(task_dir):
    return events.EventEmitter("20261103-211400-test", task_dir)


def logged(task_dir) -> list[dict]:
    return events.read_events(task_dir)


# --- is_path_inside -------------------------------------------------------


def test_relative_and_absolute_inside(task_dir) -> None:
    assert runner.is_path_inside("output/hello.md", task_dir)
    assert runner.is_path_inside(str(task_dir / "output" / "hello.md"), task_dir)
    assert runner.is_path_inside(str(task_dir), task_dir)
    assert runner.is_path_inside("output/../summary.md", task_dir)


@pytest.mark.parametrize(
    "path",
    ["../escape.md", "output/../../escape.md", "../../../../etc/passwd", "..", "/etc/passwd"],
)
def test_dotdot_and_absolute_outside(task_dir, path) -> None:
    assert not runner.is_path_inside(path, task_dir)


def test_absolute_dotdot_outside(task_dir) -> None:
    assert not runner.is_path_inside(str(task_dir / ".." / "other" / "x.md"), task_dir)


def test_sibling_with_same_prefix_outside(task_dir) -> None:
    # /tmp/x/task-evil must not count as inside /tmp/x/task
    assert not runner.is_path_inside(str(task_dir) + "-evil/x.md", task_dir)


@pytest.mark.parametrize("path", ["", "~", "~/notes.md", "out\x00put", None, 123])
def test_weird_paths_outside(task_dir, path) -> None:
    assert not runner.is_path_inside(path, task_dir)


def test_symlink_to_outside_dir(task_dir, tmp_path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (task_dir / "link").symlink_to(outside)
    assert not runner.is_path_inside("link/secret.txt", task_dir)
    assert not runner.is_path_inside(str(task_dir / "link" / "secret.txt"), task_dir)


def test_symlink_to_outside_file(task_dir, tmp_path) -> None:
    target = tmp_path / "secret.txt"
    target.write_text("x")
    (task_dir / "output" / "notes.md").symlink_to(target)
    assert not runner.is_path_inside("output/notes.md", task_dir)


def test_dangling_symlink_to_outside(task_dir, tmp_path) -> None:
    (task_dir / "output" / "new.md").symlink_to(tmp_path / "does-not-exist.md")
    assert not runner.is_path_inside("output/new.md", task_dir)


def test_symlink_inside_task_dir_allowed(task_dir) -> None:
    (task_dir / "alias").symlink_to(task_dir / "output")
    assert runner.is_path_inside("alias/hello.md", task_dir)


def test_symlink_loop_denied(task_dir) -> None:
    (task_dir / "a").symlink_to(task_dir / "b")
    (task_dir / "b").symlink_to(task_dir / "a")
    assert not runner.is_path_inside("a/x", task_dir)


# --- check_tool_call ------------------------------------------------------


@pytest.mark.parametrize("tool", ["Read", "Write", "Edit"])
def test_file_tools(task_dir, tool) -> None:
    assert runner.check_tool_call(tool, {"file_path": str(task_dir / "output/a.md")}, task_dir) is None
    assert runner.check_tool_call(tool, {"file_path": "/etc/hosts"}, task_dir) is not None
    assert runner.check_tool_call(tool, {"file_path": "../x"}, task_dir) is not None
    assert runner.check_tool_call(tool, {}, task_dir) is not None  # missing path: fail closed


def test_glob_tool(task_dir) -> None:
    check = runner.check_tool_call
    assert check("Glob", {"pattern": "**/*.md"}, task_dir) is None
    assert check("Glob", {"pattern": "*.md", "path": str(task_dir / "output")}, task_dir) is None
    assert check("Glob", {"pattern": "*.md", "path": "/etc"}, task_dir) is not None
    assert check("Glob", {"pattern": "/etc/*"}, task_dir) is not None
    assert check("Glob", {"pattern": "../**/*.md"}, task_dir) is not None
    assert check("Glob", {"pattern": "output/../../*"}, task_dir) is not None
    assert check("Glob", {"pattern": "~/*"}, task_dir) is not None


def test_glob_through_symlink_denied(task_dir, tmp_path) -> None:
    (tmp_path / "outside").mkdir()
    (task_dir / "link").symlink_to(tmp_path / "outside")
    assert runner.check_tool_call("Glob", {"pattern": "link/**"}, task_dir) is not None


def test_grep_tool(task_dir) -> None:
    check = runner.check_tool_call
    # The regex itself is not a path, so ".." in it is fine.
    assert check("Grep", {"pattern": "a..b"}, task_dir) is None
    assert check("Grep", {"pattern": "x", "path": "output", "glob": "*.md"}, task_dir) is None
    assert check("Grep", {"pattern": "x", "path": "/"}, task_dir) is not None
    assert check("Grep", {"pattern": "x", "path": ".."}, task_dir) is not None
    assert check("Grep", {"pattern": "x", "glob": "../*.md"}, task_dir) is not None


@pytest.mark.parametrize("tool", ["Bash", "WebFetch", "NotebookEdit", "Task"])
def test_unknown_tools_denied(task_dir, tool) -> None:
    assert runner.check_tool_call(tool, {"command": "ls"}, task_dir) is not None


def test_path_guard_hook_output(task_dir, emitter) -> None:
    guard = runner.make_path_guard(task_dir, emitter)
    allow = asyncio.run(guard(
        {"tool_name": "Write", "tool_input": {"file_path": "output/a.md"}}, "id1", {"signal": None}
    ))
    assert allow == {}
    deny = asyncio.run(guard(
        {"tool_name": "Write", "tool_input": {"file_path": "/tmp/a.md"}}, "id2", {"signal": None}
    ))
    out = deny["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse" and out["permissionDecision"] == "deny"


def test_build_options_isolation(task_dir, emitter) -> None:
    options = runner.build_options(task_dir, emitter)
    assert options.tools == ["Read", "Write", "Edit", "Glob", "Grep"]
    assert options.setting_sources == []
    assert options.strict_mcp_config is True
    assert options.permission_mode == "dontAsk"
    assert options.cwd == task_dir
    assert options.hooks["PreToolUse"][0].on_failure == "block"
    assert set(options.hooks) == {"PreToolUse", "PostToolUse", "PostToolUseFailure"}


# --- tool hooks emit events (synthetic hook inputs) -------------------------


def hook_input(event: str, tool: str, tool_input: dict, **extra) -> dict:
    return {"hook_event_name": event, "session_id": "s", "transcript_path": "/t", "cwd": "/c",
            "tool_name": tool, "tool_input": tool_input, "tool_use_id": "tu1", **extra}


def test_guard_allow_emits_tool_start(task_dir, emitter) -> None:
    guard = runner.make_path_guard(task_dir, emitter)
    data = hook_input("PreToolUse", "Write", {"file_path": str(task_dir / "output/a.md"), "content": "SECRET"})
    assert asyncio.run(guard(data, "tu1", {"signal": None})) == {}
    [event] = logged(task_dir)
    assert event["type"] == "tool_start" and event["tool"] == "Write"
    assert event["path"] == "output/a.md"
    assert event["agent"] == "orchestrator" and event["agent_id"] is None
    assert "SECRET" not in json.dumps(event)  # never file contents


def test_guard_deny_emits_tool_denied(task_dir, emitter) -> None:
    guard = runner.make_path_guard(task_dir, emitter)
    data = hook_input("PreToolUse", "Read", {"file_path": "/etc/passwd"})
    out = asyncio.run(guard(data, "tu1", {"signal": None}))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    [event] = logged(task_dir)
    assert event["type"] == "tool_denied" and event["path"] is None
    assert "outside the task directory" in event["summary"]


def test_guard_bad_input_denies_without_raising(task_dir, emitter) -> None:
    guard = runner.make_path_guard(task_dir, emitter)
    out = asyncio.run(guard({"tool_name": "Write"}, "tu1", {"signal": None}))  # no tool_input
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert logged(task_dir)[0]["type"] == "tool_denied"


def test_guard_still_decides_when_emit_fails(task_dir, emitter, monkeypatch) -> None:
    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(emitter, "emit", broken)
    guard = runner.make_path_guard(task_dir, emitter)
    allow = hook_input("PreToolUse", "Write", {"file_path": "output/a.md"})
    deny = hook_input("PreToolUse", "Write", {"file_path": "/tmp/a.md"})
    assert asyncio.run(guard(allow, "tu1", {"signal": None})) == {}
    assert "hookSpecificOutput" in asyncio.run(guard(deny, "tu2", {"signal": None}))


def test_subagent_fields_from_hook_input(task_dir, emitter) -> None:
    guard = runner.make_path_guard(task_dir, emitter)
    data = hook_input("PreToolUse", "Read", {"file_path": "output/a.md"},
                      agent_id="agent-7", agent_type="writer")
    asyncio.run(guard(data, "tu1", {"signal": None}))
    [event] = logged(task_dir)
    assert event["agent"] == "writer" and event["agent_id"] == "agent-7"


def test_tool_end_hook(task_dir, emitter) -> None:
    hook = runner.make_tool_end_hook(task_dir, emitter)
    done = hook_input("PostToolUse", "Write", {"file_path": "output/a.md"}, tool_response={"x": "SECRET"})
    failed = hook_input("PostToolUseFailure", "Read", {"file_path": "output/b.md"}, error="SECRET")
    assert asyncio.run(hook(done, "tu1", {"signal": None})) == {}
    assert asyncio.run(hook(failed, "tu2", {"signal": None})) == {}
    first, second = logged(task_dir)
    assert first["type"] == second["type"] == "tool_end"
    assert first["summary"] == "Write done: output/a.md"
    assert second["summary"] == "Read failed: output/b.md"
    assert "SECRET" not in json.dumps([first, second])


def test_tool_end_hook_never_raises(task_dir, emitter) -> None:
    hook = runner.make_tool_end_hook(task_dir, emitter)
    assert asyncio.run(hook({}, None, {"signal": None})) == {}
    assert asyncio.run(hook(None, None, {"signal": None})) == {}


def test_glob_grep_summary(task_dir) -> None:
    assert runner.tool_target("Glob", {"pattern": "**/*.md"}, task_dir) == (None, "'**/*.md'")
    assert runner.tool_target("Grep", {"pattern": "x", "path": str(task_dir / "output")}, task_dir) == (
        "output", "'x' in output")


# --- run_task with a fake SDK ---------------------------------------------


def fake_result(**kwargs) -> ResultMessage:
    defaults = dict(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False,
                    num_turns=1, session_id="s", result="Wrote output/hello.md")
    return ResultMessage(**{**defaults, **kwargs})


def fake_query(*messages, raises: Exception | None = None):
    async def _query(prompt, options):
        for message in messages:
            yield message
        if raises:
            raise raises
    return _query


@pytest.fixture
def no_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_run_task_done_writes_summary(tasks_dir, monkeypatch, no_api_key) -> None:
    monkeypatch.setattr(runner, "query", fake_query(fake_result()))
    task_id = tasks.create_task("hello")["task_id"]
    asyncio.run(runner.run_task(task_id))
    manifest = tasks.read_manifest(task_id)
    assert manifest["status"] == "done"
    assert (tasks_dir / task_id / "summary.md").read_text() == "Wrote output/hello.md\n"
    assert [e["type"] for e in logged(tasks_dir / task_id)] == ["task_started", "task_done"]


def test_run_task_event_sequence(tasks_dir, monkeypatch, no_api_key) -> None:
    """A fake session that calls the registered hooks the way the CLI would."""

    async def _query(prompt, options):
        pre = options.hooks["PreToolUse"][0].hooks[0]
        post = options.hooks["PostToolUse"][0].hooks[0]
        write = {"file_path": "output/hello.md", "content": "hi"}
        yield AssistantMessage(content=[TextBlock(text="I will write\nthe file. " + "x" * 200)], model="m")
        await pre(hook_input("PreToolUse", "Write", write), "tu1", {"signal": None})
        await post(hook_input("PostToolUse", "Write", write, tool_response={}), "tu1", {"signal": None})
        await pre(hook_input("PreToolUse", "Write", {"file_path": "../x.md"}), "tu2", {"signal": None})
        yield fake_result()

    monkeypatch.setattr(runner, "query", _query)
    task_id = tasks.create_task("hello")["task_id"]
    asyncio.run(runner.run_task(task_id))
    file = tasks_dir / task_id / "events.jsonl"
    checked = events.validate_file(file)
    assert [e.type for e in checked] == [
        "task_started", "agent_message", "tool_start", "tool_end", "tool_denied", "task_done"]
    assert [e.seq for e in checked] == [1, 2, 3, 4, 5, 6]
    message = checked[1]
    assert message.summary.startswith("I will write the file.") and len(message.summary) == 120
    assert {e.task_id for e in checked} == {task_id}


def test_run_task_exception_marks_failed(tasks_dir, monkeypatch, no_api_key) -> None:
    monkeypatch.setattr(runner, "query", fake_query(raises=ConnectionError("cli died")))
    task_id = tasks.create_task("hello")["task_id"]
    asyncio.run(runner.run_task(task_id))
    manifest = tasks.read_manifest(task_id)
    assert manifest["status"] == "failed"
    assert "cli died" in manifest["error"]
    assert not (tasks_dir / task_id / "summary.md").exists()
    types = [e["type"] for e in logged(tasks_dir / task_id)]
    assert types == ["task_started", "task_failed"]


def test_run_task_error_result_marks_failed(tasks_dir, monkeypatch, no_api_key) -> None:
    result = fake_result(subtype="error_max_turns", is_error=True, result=None)
    monkeypatch.setattr(runner, "query", fake_query(result))
    task_id = tasks.create_task("hello")["task_id"]
    asyncio.run(runner.run_task(task_id))
    manifest = tasks.read_manifest(task_id)
    assert manifest["status"] == "failed" and "error_max_turns" in manifest["error"]


def test_run_task_refuses_with_api_key_set(tasks_dir, monkeypatch) -> None:
    called = []
    monkeypatch.setattr(runner, "query", lambda **kw: called.append(kw))
    monkeypatch.setitem(os.environ, "ANTHROPIC_API_KEY", "dummy-not-a-real-key")
    task_id = tasks.create_task("hello")["task_id"]
    asyncio.run(runner.run_task(task_id))
    assert tasks.read_manifest(task_id)["status"] == "failed"
    assert called == []
