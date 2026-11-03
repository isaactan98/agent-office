"""Run one task as an Agent SDK session (orchestrator + subagents from app/agents.py),
sandboxed to its task directory.

SDK option names were verified in Phase 1 (backend/spikes/README.md). Subagent
events come from the SDK's SubagentStart/SubagentStop hooks; tool hooks carry
agent_id/agent_type when they fire inside a subagent.

The session uses ClaudeSDKClient, not query(): only the client has interrupt(),
which is how a running task is cancelled.
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    ResultMessage,
    TextBlock,
)

from app import agents, events, tasks, usage

log = logging.getLogger(__name__)

# File read/write/edit/search only. No Bash, no web tools.
TOOLS = ["Read", "Write", "Edit", "Glob", "Grep"]
# The orchestrator also gets the delegation tool, to start writer/reviewer.
SESSION_TOOLS = TOOLS + [agents.DELEGATION_TOOL]
MAX_TURNS = 20

PROMPT_TEMPLATE = """\
Your working directory is the task directory. Write every deliverable file under
the output/ directory. Do not read or write anything outside the task directory.

Task:
{text}
"""

GLOB_CHARS = set("*?[{")

# Tasks asked to stop, and the SDK client of each running session.
_cancel_requested: set[str] = set()
_clients: dict[str, ClaudeSDKClient] = {}


class Cancelled(Exception):
    """The task was cancelled while running."""


def is_path_inside(path: str, task_dir: Path) -> bool:
    """True if `path` (relative to task_dir, or absolute) resolves inside task_dir.

    Resolves `..` and follows symlinks, so a symlink pointing outside is caught.
    """
    if not isinstance(path, str) or not path or path.startswith("~"):
        return False
    root = task_dir.resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve()
    except (OSError, RuntimeError, ValueError):  # symlink loop, null byte, ...
        return False
    return resolved == root or resolved.is_relative_to(root)


def is_glob_inside(pattern: str, base: str, task_dir: Path) -> bool:
    """True if a glob pattern, searched from `base`, cannot reach outside task_dir."""
    if not isinstance(pattern, str) or pattern.startswith(("/", "~")):
        return False
    parts = Path(pattern).parts
    if ".." in parts:
        return False
    # The literal part before the first wildcard must itself resolve inside.
    literal = []
    for part in parts:
        if GLOB_CHARS & set(part):
            break
        literal.append(part)
    return is_path_inside(str(Path(base).joinpath(*literal)), task_dir)


def check_delegation(tool_input: dict[str, Any], agent_type: str | None, agent_calls: int) -> str | None:
    """Return a reason to deny an Agent tool call, or None if it may start a subagent."""
    if agent_type is not None:
        return f"Agent: subagent {agent_type!r} may not start other agents"
    extra = sorted(set(tool_input) - agents.DELEGATION_KEYS)
    if extra:
        return f"Agent: fields {extra} are not allowed"
    name = tool_input.get("subagent_type")
    if name not in agents.SUBAGENTS:
        return f"Agent: unknown subagent {name!r}"
    if tool_input.get("run_in_background") is not False:
        return "Agent: run_in_background must be false"
    if agent_calls >= agents.MAX_SUBAGENT_CALLS:
        return f"Agent: limit of {agents.MAX_SUBAGENT_CALLS} subagent calls reached"
    return None


def check_tool_call(
    tool_name: str,
    tool_input: dict[str, Any],
    task_dir: Path,
    agent_type: str | None = None,
    agent_calls: int = 0,
) -> str | None:
    """Return a reason to deny the call, or None if it is allowed.

    Every path must stay inside task_dir. `agent_type` is the subagent making the
    call (None for the orchestrator); `agent_calls` is how many subagent calls were
    already allowed in this task.
    """
    root = str(task_dir.resolve())
    if tool_name in ("Read", "Write", "Edit"):
        path = tool_input.get("file_path")
        if not is_path_inside(path, task_dir):
            return f"{tool_name}: path {path!r} is outside the task directory"
        # Not resolved: if review.md is a symlink, the resolved path differs and is denied.
        review_file = task_dir.resolve() / agents.REVIEW_FILE
        if agent_type == agents.REVIEWER and tool_name != "Read" and (task_dir / path).resolve() != review_file:
            return f"{tool_name}: the reviewer may only write {agents.REVIEW_FILE}"
        return None
    if tool_name in ("Glob", "Grep"):
        base = tool_input.get("path") or root
        if not is_path_inside(base, task_dir):
            return f"{tool_name}: path {base!r} is outside the task directory"
        pattern = tool_input.get("pattern" if tool_name == "Glob" else "glob")
        if pattern is not None and not is_glob_inside(pattern, base, task_dir):
            return f"{tool_name}: pattern {pattern!r} reaches outside the task directory"
        return None
    if tool_name == agents.DELEGATION_TOOL:
        return check_delegation(tool_input, agent_type, agent_calls)
    # Fail closed: a tool we do not know how to check is denied.
    return f"tool {tool_name!r} is not allowed"


def tool_target(tool_name: str, tool_input: dict[str, Any], task_dir: Path) -> tuple[str | None, str]:
    """(path relative to task_dir or None, short label for the summary) of a tool call."""
    if tool_name in ("Read", "Write", "Edit"):
        raw = tool_input.get("file_path")
        path = events.relative_path(raw, task_dir)
        return path, path or str(raw)
    if tool_name in ("Glob", "Grep"):
        path = events.relative_path(tool_input.get("path"), task_dir)
        pattern = repr(tool_input.get("pattern"))  # Glob: file pattern, Grep: regex
        return path, f"{pattern} in {path}" if path else pattern
    if tool_name == agents.DELEGATION_TOOL:
        return None, f"{tool_input.get('subagent_type')}: {tool_input.get('description')}"
    return None, ""


def agent_fields(input_data: dict[str, Any]) -> dict[str, Any]:
    """agent/agent_id from a tool hook input. The installed SDK sets agent_id and
    agent_type on tool hooks only when they fire inside a subagent."""
    return {
        "agent": input_data.get("agent_type") or events.DEFAULT_AGENT,
        "agent_id": input_data.get("agent_id"),
    }


def emit_safely(emitter: events.EventEmitter, type: str, summary: str, **fields: Any) -> None:
    """Emit, but never raise: a broken event log must not break the task or a hook."""
    try:
        emitter.emit(type, summary, **fields)
    except Exception:
        log.exception("could not emit %s event", type)


def emit_tool_event(
    emitter: events.EventEmitter,
    task_dir: Path,
    type: str,
    input_data: dict[str, Any],
    reason: str | None = None,
) -> None:
    """Emit tool_start / tool_end / tool_denied from hook input. Never raises."""
    try:
        tool = input_data.get("tool_name")
        path, label = tool_target(tool, input_data.get("tool_input") or {}, task_dir)
        if type == "tool_denied":
            summary = f"Denied {reason}"
        elif type == "tool_end":
            failed = input_data.get("hook_event_name") == "PostToolUseFailure"
            summary = f"{tool} {'failed' if failed else 'done'}: {label}"
        else:
            summary = f"{tool} {label}"
        emitter.emit(type, summary, tool=tool, path=path, **agent_fields(input_data))
    except Exception:
        log.exception("could not emit %s event", type)


def make_path_guard(task_dir: Path, emitter: events.EventEmitter):
    """PreToolUse hook that denies tool calls touching paths outside task_dir.

    Also enforces the per-agent rules in check_tool_call and counts allowed subagent
    calls. Emits tool_start for allowed calls and tool_denied for denied ones.
    """
    agent_calls = 0

    async def path_guard(input_data, tool_use_id, context):
        nonlocal agent_calls
        try:
            reason = check_tool_call(
                input_data["tool_name"],
                input_data["tool_input"],
                task_dir,
                agent_type=input_data.get("agent_type"),
                agent_calls=agent_calls,
            )
        except Exception:
            log.exception("path guard failed; denying the call")
            reason = "path guard error"
        if reason is None:
            if input_data["tool_name"] == agents.DELEGATION_TOOL:
                agent_calls += 1
            emit_tool_event(emitter, task_dir, "tool_start", input_data)
            return {}
        emit_tool_event(emitter, task_dir, "tool_denied", input_data, reason)
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }

    return path_guard


def make_tool_end_hook(task_dir: Path, emitter: events.EventEmitter):
    """PostToolUse / PostToolUseFailure hook that emits tool_end. Never decides anything."""

    async def tool_end(input_data, tool_use_id, context):
        emit_tool_event(emitter, task_dir, "tool_end", input_data)
        return {}

    return tool_end


def make_subagent_hook(emitter: events.EventEmitter):
    """SubagentStart / SubagentStop hook: emits subagent_start / subagent_stop and
    counts each start in the manifest. Never decides anything, never raises."""

    async def subagent_hook(input_data, tool_use_id, context):
        try:
            name = input_data.get("agent_type") or "unknown"
            fields = {"agent": name, "agent_id": input_data.get("agent_id")}
            if input_data.get("hook_event_name") == "SubagentStart":
                emit_safely(emitter, "subagent_start", f"{name} started", **fields)
                tasks.record_agent_run(emitter.task_id, name)
            else:
                last = input_data.get("last_assistant_message")
                summary = f"{name} finished: {last}" if last else f"{name} finished"
                emit_safely(emitter, "subagent_stop", summary, **fields)
        except Exception:
            log.exception("subagent hook failed")
        return {}

    return subagent_hook


def build_options(task_dir: Path, emitter: events.EventEmitter) -> ClaudeAgentOptions:
    tool_end = make_tool_end_hook(task_dir, emitter)
    subagent_hook = make_subagent_hook(emitter)
    return ClaudeAgentOptions(
        cwd=task_dir,
        system_prompt=agents.ORCHESTRATOR_PROMPT,
        agents=agents.SUBAGENTS,
        tools=SESSION_TOOLS,  # the only built-in tools that exist in the session
        allowed_tools=SESSION_TOOLS,  # auto-approve them
        permission_mode="dontAsk",  # anything not pre-approved is denied
        setting_sources=[],  # do not load ~/.claude or project settings/CLAUDE.md/hooks
        strict_mcp_config=True,  # no MCP servers, including claude.ai connectors
        env={"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"},
        max_turns=MAX_TURNS,
        hooks={
            # matcher=None: every tool call. on_failure="block": a crashing hook denies.
            "PreToolUse": [
                HookMatcher(
                    matcher=None, hooks=[make_path_guard(task_dir, emitter)], on_failure="block"
                )
            ],
            "PostToolUse": [HookMatcher(matcher=None, hooks=[tool_end])],
            "PostToolUseFailure": [HookMatcher(matcher=None, hooks=[tool_end])],
            "SubagentStart": [HookMatcher(matcher=None, hooks=[subagent_hook])],
            "SubagentStop": [HookMatcher(matcher=None, hooks=[subagent_hook])],
        },
    )


def cancel_queued(task_id: str) -> dict[str, Any]:
    """Mark a task that never started as cancelled. Emits task_failed so a watching
    feed knows it ended (the event schema has no task_cancelled type)."""
    _cancel_requested.discard(task_id)
    manifest = tasks.set_status(task_id, "cancelled")
    emitter = events.EventEmitter(task_id, tasks.task_dir(task_id))
    emit_safely(emitter, "task_failed", "Task cancelled before it started")
    return manifest


async def request_cancel(task_id: str) -> None:
    """Ask the running session of task_id to stop; run_task then ends as 'cancelled'.

    Sends the SDK's interrupt if the session is connected. If it is still
    connecting, run_task sees the request and does not send the prompt.
    Raises if the interrupt cannot be sent.
    """
    _cancel_requested.add(task_id)
    client = _clients.get(task_id)
    if client is not None:
        await client.interrupt()


def _end_cancelled(task_id: str, emitter: events.EventEmitter) -> None:
    try:
        tasks.set_status(task_id, "cancelled")
    except Exception:
        log.exception("could not mark %s cancelled", task_id)
    emit_safely(emitter, "task_failed", "Task cancelled")


async def run_task(task_id: str) -> None:
    """Run the task. Ends with status 'done' (summary.md written), 'failed' or
    'cancelled'. If the SDK returned a result, one line goes to usage.jsonl.

    Events go to events.jsonl: task_started first, task_done or task_failed last
    (a cancelled task ends with task_failed "Task cancelled").
    """
    if task_id in _cancel_requested:  # cancelled before it started
        cancel_queued(task_id)
        return
    task_dir = tasks.task_dir(task_id)
    emitter = events.EventEmitter(task_id, task_dir)
    manifest = tasks.set_status(task_id, "running")
    emit_safely(emitter, "task_started", "Task started")
    result: ResultMessage | None = None
    try:
        # Check presence only; never read or print the value.
        if "ANTHROPIC_API_KEY" in os.environ:
            raise RuntimeError("ANTHROPIC_API_KEY is set in the environment. Refusing to run.")
        tasks.record_agent_run(task_id, agents.ORCHESTRATOR)

        prompt = PROMPT_TEMPLATE.format(text=manifest["text"])
        async with ClaudeSDKClient(options=build_options(task_dir, emitter)) as client:
            _clients[task_id] = client
            try:
                if task_id not in _cancel_requested:  # not cancelled while connecting
                    await client.query(prompt)
                    async for message in client.receive_response():
                        # Subagent text is not forwarded (forward_subagent_text is off);
                        # messages with a parent_tool_use_id carry only a subagent's
                        # tool blocks.
                        if isinstance(message, AssistantMessage) and message.parent_tool_use_id is None:
                            for block in message.content:
                                if isinstance(block, TextBlock) and block.text.strip():
                                    emit_safely(emitter, "agent_message", block.text)
                        elif isinstance(message, ResultMessage):
                            result = message
            finally:
                del _clients[task_id]

        if task_id in _cancel_requested:
            raise Cancelled()
        if result is None:
            raise RuntimeError("SDK session ended without a result")
        if result.is_error or result.subtype != "success":
            raise RuntimeError(f"SDK result {result.subtype!r}: {result.errors or result.result}")

        summary = task_dir / "summary.md"
        if not summary.exists():  # the orchestrator should have written it
            summary.write_text((result.result or "") + "\n")
        tasks.set_status(task_id, "done")
        emit_safely(emitter, "task_done", f"Task done in {result.num_turns} turns")
    except (Cancelled, asyncio.CancelledError) as exc:
        _end_cancelled(task_id, emitter)
        if isinstance(exc, asyncio.CancelledError):
            raise  # the asyncio task itself was cancelled: let it end
    except Exception as exc:
        if task_id in _cancel_requested:  # the interrupt made the session fail
            _end_cancelled(task_id, emitter)
        else:
            error = f"{type(exc).__name__}: {exc}"
            tasks.set_status(task_id, "failed", error=error)
            emit_safely(emitter, "task_failed", f"Task failed: {error}")
    finally:
        _cancel_requested.discard(task_id)
        if result is not None:
            usage.record(task_id, result)
