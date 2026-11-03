"""Path guard and run_task tests. The real SDK is never called."""

import asyncio
import json
import os

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

from app import agents, events, runner, tasks


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
    assert options.tools == ["Read", "Write", "Edit", "Glob", "Grep", "Agent"]
    assert options.allowed_tools == options.tools
    assert options.setting_sources == []
    assert options.strict_mcp_config is True
    assert options.permission_mode == "dontAsk"
    assert options.cwd == task_dir
    assert options.hooks["PreToolUse"][0].on_failure == "block"
    assert set(options.hooks) == {
        "PreToolUse", "PostToolUse", "PostToolUseFailure", "SubagentStart", "SubagentStop"}
    assert options.system_prompt == agents.ORCHESTRATOR_PROMPT
    assert set(options.agents) == {"writer", "reviewer"}
    # Subagents get file tools only: no Bash, no web, no Agent.
    assert options.agents["writer"].tools == ["Read", "Write", "Edit"]
    assert options.agents["reviewer"].tools == ["Read", "Glob", "Grep", "Write"]


def test_orchestrator_prompt_is_short() -> None:
    assert len(agents.ORCHESTRATOR_PROMPT.splitlines()) < 40


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


# --- subagents: path guard, reviewer rule, delegation rules -----------------


def run_guard(guard, tool: str, tool_input: dict, **extra) -> dict:
    return asyncio.run(guard(hook_input("PreToolUse", tool, tool_input, **extra), "tu", {"signal": None}))


def denied(out: dict) -> bool:
    return out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


WRITER = {"agent_id": "a-writer-1", "agent_type": "writer"}
REVIEWER = {"agent_id": "a-reviewer-1", "agent_type": "reviewer"}


@pytest.mark.parametrize("who", [WRITER, REVIEWER])
@pytest.mark.parametrize("tool,tool_input", [
    ("Read", {"file_path": "/etc/passwd"}),
    ("Write", {"file_path": "../escape.md", "content": "x"}),
    ("Edit", {"file_path": "/tmp/x.md", "old_string": "a", "new_string": "b"}),
    ("Glob", {"pattern": "../**/*"}),
    ("Grep", {"pattern": "x", "path": "/"}),
    ("Bash", {"command": "cat /etc/passwd"}),
])
def test_subagent_calls_outside_task_dir_denied(task_dir, emitter, who, tool, tool_input) -> None:
    guard = runner.make_path_guard(task_dir, emitter)
    assert denied(run_guard(guard, tool, tool_input, **who))
    [event] = logged(task_dir)
    assert event["type"] == "tool_denied"
    assert event["agent"] == who["agent_type"] and event["agent_id"] == who["agent_id"]


def test_subagent_symlink_escape_denied(task_dir, emitter, tmp_path) -> None:
    (tmp_path / "outside").mkdir()
    (task_dir / "output" / "link").symlink_to(tmp_path / "outside")
    guard = runner.make_path_guard(task_dir, emitter)
    assert denied(run_guard(guard, "Write", {"file_path": "output/link/x.md"}, **WRITER))


def test_writer_allowed_inside(task_dir, emitter) -> None:
    guard = runner.make_path_guard(task_dir, emitter)
    assert run_guard(guard, "Write", {"file_path": str(task_dir / "output/route.md")}, **WRITER) == {}
    assert run_guard(guard, "Edit", {"file_path": "output/route.md"}, **WRITER) == {}


def test_reviewer_may_only_write_review_file(task_dir, emitter) -> None:
    guard = runner.make_path_guard(task_dir, emitter)
    assert run_guard(guard, "Read", {"file_path": "output/route.md"}, **REVIEWER) == {}
    assert run_guard(guard, "Glob", {"pattern": "output/**"}, **REVIEWER) == {}
    assert run_guard(guard, "Write", {"file_path": "output/review.md"}, **REVIEWER) == {}
    assert run_guard(guard, "Write", {"file_path": str(task_dir / "output/review.md")}, **REVIEWER) == {}
    for path in ["output/route.md", "summary.md", "output/sub/review.md", "review.md"]:
        assert denied(run_guard(guard, "Write", {"file_path": path}, **REVIEWER)), path
    assert denied(run_guard(guard, "Edit", {"file_path": "output/route.md"}, **REVIEWER))
    # The orchestrator and writer are not limited to review.md.
    assert run_guard(guard, "Write", {"file_path": "summary.md"}) == {}


def test_reviewer_symlink_to_deliverable_denied(task_dir, emitter) -> None:
    (task_dir / "output" / "route.md").write_text("x")
    (task_dir / "output" / "review.md").symlink_to(task_dir / "output" / "route.md")
    guard = runner.make_path_guard(task_dir, emitter)
    assert denied(run_guard(guard, "Write", {"file_path": "output/review.md"}, **REVIEWER))


def delegation(name="writer", **extra) -> dict:
    return {"subagent_type": name, "description": "Write route", "prompt": "Write output/route.md",
            "run_in_background": False, **extra}


def test_delegation_allowed(task_dir, emitter) -> None:
    guard = runner.make_path_guard(task_dir, emitter)
    assert run_guard(guard, "Agent", delegation("writer")) == {}
    assert run_guard(guard, "Agent", delegation("reviewer")) == {}
    first, second = logged(task_dir)
    assert first["type"] == "tool_start" and first["tool"] == "Agent"
    assert first["agent"] == "orchestrator" and first["summary"] == "Agent writer: Write route"


@pytest.mark.parametrize("tool_input,reason", [
    (delegation("general-purpose"), "unknown subagent"),
    ({k: v for k, v in delegation().items() if k != "subagent_type"}, "unknown subagent"),
    ({k: v for k, v in delegation().items() if k != "run_in_background"}, "run_in_background"),
    (delegation(run_in_background=True), "run_in_background"),
    (delegation(isolation="worktree"), "not allowed"),
    (delegation(cwd="/tmp"), "not allowed"),
    (delegation(model="opus"), "not allowed"),
])
def test_delegation_denied(task_dir, emitter, tool_input, reason) -> None:
    guard = runner.make_path_guard(task_dir, emitter)
    assert denied(run_guard(guard, "Agent", tool_input))
    assert reason in logged(task_dir)[0]["summary"]


def test_subagent_cannot_delegate(task_dir, emitter) -> None:
    guard = runner.make_path_guard(task_dir, emitter)
    assert denied(run_guard(guard, "Agent", delegation("reviewer"), **WRITER))


def test_delegation_capped_at_four(task_dir, emitter) -> None:
    guard = runner.make_path_guard(task_dir, emitter)
    assert denied(run_guard(guard, "Agent", delegation("nobody")))  # denied calls do not count
    for _ in range(agents.MAX_SUBAGENT_CALLS):
        assert run_guard(guard, "Agent", delegation()) == {}
    assert denied(run_guard(guard, "Agent", delegation()))
    assert "limit of 4" in logged(task_dir)[-1]["summary"]


def test_subagent_hook_emits_and_counts(tasks_dir) -> None:
    task_id = tasks.create_task("hello")["task_id"]
    emitter = events.EventEmitter(task_id, tasks_dir / task_id)
    hook = runner.make_subagent_hook(emitter)
    base = {"session_id": "s", "transcript_path": "/t", "cwd": "/c", "agent_id": "a1", "agent_type": "writer"}
    start = {**base, "hook_event_name": "SubagentStart"}
    stop = {**base, "hook_event_name": "SubagentStop", "stop_hook_active": False,
            "agent_transcript_path": "/t2", "last_assistant_message": "Wrote output/route.md"}
    assert asyncio.run(hook(start, None, {"signal": None})) == {}
    assert asyncio.run(hook(stop, None, {"signal": None})) == {}
    first, second = logged(tasks_dir / task_id)
    assert (first["type"], first["agent"], first["agent_id"]) == ("subagent_start", "writer", "a1")
    assert (second["type"], second["agent"], second["agent_id"]) == ("subagent_stop", "writer", "a1")
    assert second["summary"] == "writer finished: Wrote output/route.md"
    assert tasks.read_manifest(task_id)["agents"] == {"writer": 1}


def test_subagent_hook_never_raises(task_dir, emitter) -> None:
    hook = runner.make_subagent_hook(emitter)
    assert asyncio.run(hook({}, None, {"signal": None})) == {}
    assert asyncio.run(hook(None, None, {"signal": None})) == {}


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


def test_run_task_orchestrator_and_subagents(tasks_dir, monkeypatch, no_api_key) -> None:
    """A fake session that delegates to writer and reviewer the way the CLI would."""

    async def _query(prompt, options):
        hooks = {name: matchers[0].hooks[0] for name, matchers in options.hooks.items()}
        ctx = {"signal": None}

        async def subagent(name: str, agent_id: str, tool: str, path: str):
            call = delegation(name)
            await hooks["PreToolUse"](hook_input("PreToolUse", "Agent", call), "tu-a", ctx)
            sub = {"session_id": "s", "transcript_path": "/t", "cwd": "/c",
                   "agent_id": agent_id, "agent_type": name}
            await hooks["SubagentStart"]({**sub, "hook_event_name": "SubagentStart"}, None, ctx)
            ids = {"agent_id": agent_id, "agent_type": name}
            await hooks["PreToolUse"](hook_input("PreToolUse", tool, {"file_path": path}, **ids), "tu-s", ctx)
            await hooks["PostToolUse"](hook_input("PostToolUse", tool, {"file_path": path}, **ids), "tu-s", ctx)
            await hooks["SubagentStop"]({**sub, "hook_event_name": "SubagentStop", "stop_hook_active": False,
                                         "agent_transcript_path": "/t2"}, None, ctx)
            await hooks["PostToolUse"](hook_input("PostToolUse", "Agent", call), "tu-a", ctx)

        yield AssistantMessage(content=[TextBlock(text="Plan: write, review.")], model="m")
        await subagent("writer", "a1", "Write", "output/route.md")
        # A subagent's own message (parent_tool_use_id set) is not an orchestrator message.
        yield AssistantMessage(content=[TextBlock(text="subagent text")], model="m", parent_tool_use_id="tu-a")
        await subagent("reviewer", "a2", "Write", "output/review.md")
        await hooks["PreToolUse"](hook_input("PreToolUse", "Write", {"file_path": "summary.md"}), "tu-o", ctx)
        (tasks_dir / task_id / "summary.md").write_text("orchestrator summary\n")
        yield fake_result(result="final text")

    monkeypatch.setattr(runner, "query", _query)
    task_id = tasks.create_task("route")["task_id"]
    asyncio.run(runner.run_task(task_id))
    checked = events.validate_file(tasks_dir / task_id / "events.jsonl")
    by_agent = {}
    for event in checked:
        by_agent.setdefault(event.agent, []).append(event.type)
    assert by_agent["writer"] == ["subagent_start", "tool_start", "tool_end", "subagent_stop"]
    assert by_agent["reviewer"] == ["subagent_start", "tool_start", "tool_end", "subagent_stop"]
    assert "subagent text" not in [e.summary for e in checked]
    assert {e.agent_id for e in checked if e.agent == "writer"} == {"a1"}
    assert [e.type for e in checked].count("subagent_start") == 2
    manifest = tasks.read_manifest(task_id)
    assert manifest["status"] == "done"
    assert manifest["agents"] == {"orchestrator": 1, "writer": 1, "reviewer": 1}
    # The orchestrator's summary.md is kept, not replaced by the result text.
    assert (tasks_dir / task_id / "summary.md").read_text() == "orchestrator summary\n"


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
