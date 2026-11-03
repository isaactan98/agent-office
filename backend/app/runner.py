"""Run one task as a single Agent SDK session, sandboxed to its task directory.

SDK option names were verified in Phase 1 (backend/spikes/README.md).
"""

import os
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, HookMatcher, ResultMessage, query

from app import tasks

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


def make_path_guard(task_dir: Path):
    """PreToolUse hook that denies tool calls touching paths outside task_dir."""

    async def path_guard(input_data, tool_use_id, context):
        reason = check_tool_call(input_data["tool_name"], input_data["tool_input"], task_dir)
        if reason is None:
            return {}
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }

    return path_guard


def build_options(task_dir: Path) -> ClaudeAgentOptions:
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
                HookMatcher(matcher=None, hooks=[make_path_guard(task_dir)], on_failure="block")
            ]
        },
    )


async def run_task(task_id: str) -> None:
    """Run the task. Ends with status 'done' (summary.md written) or 'failed'."""
    task_dir = tasks.task_dir(task_id)
    manifest = tasks.set_status(task_id, "running")
    try:
        # Check presence only; never read or print the value.
        if "ANTHROPIC_API_KEY" in os.environ:
            raise RuntimeError("ANTHROPIC_API_KEY is set in the environment. Refusing to run.")

        result: ResultMessage | None = None
        prompt = PROMPT_TEMPLATE.format(text=manifest["text"])
        async for message in query(prompt=prompt, options=build_options(task_dir)):
            if isinstance(message, ResultMessage):
                result = message

        if result is None:
            raise RuntimeError("SDK session ended without a result")
        if result.is_error or result.subtype != "success":
            raise RuntimeError(f"SDK result {result.subtype!r}: {result.errors or result.result}")

        (task_dir / "summary.md").write_text((result.result or "") + "\n")
        tasks.set_status(task_id, "done")
    except Exception as exc:
        tasks.set_status(task_id, "failed", error=f"{type(exc).__name__}: {exc}")
