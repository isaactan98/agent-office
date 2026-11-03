"""Path guard and run_task tests. The real SDK is never called."""

import asyncio
import os

import pytest
from claude_agent_sdk import ResultMessage

from app import runner, tasks


@pytest.fixture
def task_dir(tmp_path):
    directory = tmp_path / "task"
    (directory / "output").mkdir(parents=True)
    return directory.resolve()


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


def test_path_guard_hook_output(task_dir) -> None:
    guard = runner.make_path_guard(task_dir)
    allow = asyncio.run(guard(
        {"tool_name": "Write", "tool_input": {"file_path": "output/a.md"}}, "id1", {"signal": None}
    ))
    assert allow == {}
    deny = asyncio.run(guard(
        {"tool_name": "Write", "tool_input": {"file_path": "/tmp/a.md"}}, "id2", {"signal": None}
    ))
    out = deny["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse" and out["permissionDecision"] == "deny"


def test_build_options_isolation(task_dir) -> None:
    options = runner.build_options(task_dir)
    assert options.tools == ["Read", "Write", "Edit", "Glob", "Grep"]
    assert options.setting_sources == []
    assert options.strict_mcp_config is True
    assert options.permission_mode == "dontAsk"
    assert options.cwd == task_dir
    assert options.hooks["PreToolUse"][0].on_failure == "block"


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


def test_run_task_exception_marks_failed(tasks_dir, monkeypatch, no_api_key) -> None:
    monkeypatch.setattr(runner, "query", fake_query(raises=ConnectionError("cli died")))
    task_id = tasks.create_task("hello")["task_id"]
    asyncio.run(runner.run_task(task_id))
    manifest = tasks.read_manifest(task_id)
    assert manifest["status"] == "failed"
    assert "cli died" in manifest["error"]
    assert not (tasks_dir / task_id / "summary.md").exists()


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
