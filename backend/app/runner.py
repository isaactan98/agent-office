"""Run one task as a single Agent SDK session, sandboxed to its task directory.

SDK option names were verified in Phase 1 (backend/spikes/README.md).
"""

import logging
import os
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    HookMatcher,
    ResultMessage,
    TextBlock,
    query,
)

from app import events, tasks

log = logging.getLogger(__name__)

# File read/write/edit/search only. No Bash, no web tools.
TOOLS = ["Read", "Write", "Edit", "Glob", "Grep"]
MAX_TURNS = 20

PROMPT_TEMPLATE = """\
Your working directory is the task directory. Write every deliverable file under
the output/ directory. Do not read or write anything outside the task directory.

Task:
{text}
"""

GLOB_CHARS = set("*?[{")


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


def check_tool_call(tool_name: str, tool_input: dict[str, Any], task_dir: Path) -> str | None:
    """Return a reason to deny the call, or None if every path stays inside task_dir."""
    root = str(task_dir.resolve())
    if tool_name in ("Read", "Write", "Edit"):
        path = tool_input.get("file_path")
        if not is_path_inside(path, task_dir):
            return f"{tool_name}: path {path!r} is outside the task directory"
        return None
    if tool_name in ("Glob", "Grep"):
        base = tool_input.get("path") or root
        if not is_path_inside(base, task_dir):
            return f"{tool_name}: path {base!r} is outside the task directory"
        pattern = tool_input.get("pattern" if tool_name == "Glob" else "glob")
        if pattern is not None and not is_glob_inside(pattern, base, task_dir):
            return f"{tool_name}: pattern {pattern!r} reaches outside the task directory"
        return None
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

    Emits tool_start for allowed calls and tool_denied for denied ones.
    """

    async def path_guard(input_data, tool_use_id, context):
        try:
            reason = check_tool_call(input_data["tool_name"], input_data["tool_input"], task_dir)
        except Exception:
            log.exception("path guard failed; denying the call")
            reason = "path guard error"
        if reason is None:
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


def build_options(task_dir: Path, emitter: events.EventEmitter) -> ClaudeAgentOptions:
    tool_end = make_tool_end_hook(task_dir, emitter)
    return ClaudeAgentOptions(
        cwd=task_dir,
        tools=TOOLS,  # the only built-in tools that exist in the session
        allowed_tools=TOOLS,  # auto-approve them
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
        },
    )


async def run_task(task_id: str) -> None:
    """Run the task. Ends with status 'done' (summary.md written) or 'failed'.

    Events go to events.jsonl: task_started first, task_done or task_failed last.
    """
    task_dir = tasks.task_dir(task_id)
    emitter = events.EventEmitter(task_id, task_dir)
    manifest = tasks.set_status(task_id, "running")
    emit_safely(emitter, "task_started", "Task started")
    try:
        # Check presence only; never read or print the value.
        if "ANTHROPIC_API_KEY" in os.environ:
            raise RuntimeError("ANTHROPIC_API_KEY is set in the environment. Refusing to run.")

        result: ResultMessage | None = None
        prompt = PROMPT_TEMPLATE.format(text=manifest["text"])
        async for message in query(prompt=prompt, options=build_options(task_dir, emitter)):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock) and block.text.strip():
                        emit_safely(emitter, "agent_message", block.text)
            elif isinstance(message, ResultMessage):
                result = message

        if result is None:
            raise RuntimeError("SDK session ended without a result")
        if result.is_error or result.subtype != "success":
            raise RuntimeError(f"SDK result {result.subtype!r}: {result.errors or result.result}")

        (task_dir / "summary.md").write_text((result.result or "") + "\n")
        tasks.set_status(task_id, "done")
        emit_safely(emitter, "task_done", f"Task done in {result.num_turns} turns")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        tasks.set_status(task_id, "failed", error=error)
        emit_safely(emitter, "task_failed", f"Task failed: {error}")
