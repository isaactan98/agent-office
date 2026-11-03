"""Phase 1 spike: run one tiny Agent SDK task on the Claude Code CLI login.

Run from backend/:  uv run python spikes/sdk_spike.py
"""

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    __version__,
    query,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import TASKS_DIR  # noqa: E402

PROMPT = "Create notes.md containing a 3-line haiku about Johor Bahru traffic."
TOOLS = ["Read", "Write"]


def summarize_block(block) -> str:
    if isinstance(block, TextBlock):
        return f"text: {block.text[:100]!r}"
    if isinstance(block, ThinkingBlock):
        return "thinking"
    if isinstance(block, ToolUseBlock):
        return f"tool_use: {block.name} {block.input.get('file_path', '')}"
    if isinstance(block, ToolResultBlock):
        return f"tool_result: is_error={block.is_error}"
    return type(block).__name__


def summarize(message) -> str:
    if isinstance(message, SystemMessage):
        if message.subtype == "init":
            d = message.data
            return (
                f"init apiKeySource={d.get('apiKeySource')!r} model={d.get('model')!r} "
                f"cwd={d.get('cwd')!r} permissionMode={d.get('permissionMode')!r} "
                f"tools={d.get('tools')} mcp_servers={d.get('mcp_servers')} "
                f"skills={d.get('skills')} plugins={d.get('plugins')} "
                f"claude_code_version={d.get('claude_code_version')!r}"
            )
        return f"subtype={message.subtype}"
    if isinstance(message, (AssistantMessage, UserMessage)):
        content = message.content
        if isinstance(content, str):
            return f"text: {content[:100]!r}"
        return "; ".join(summarize_block(b) for b in content)
    if isinstance(message, ResultMessage):
        return f"subtype={message.subtype} is_error={message.is_error}"
    return ""


async def main() -> None:
    # Check presence only; never read or print the value.
    if "ANTHROPIC_API_KEY" in os.environ:
        sys.exit("ANTHROPIC_API_KEY is set in the environment. Refusing to run.")

    spike_dir = TASKS_DIR / f"spike-{datetime.now():%Y%m%d-%H%M%S}"
    spike_dir.mkdir(parents=True)
    print(f"SDK {__version__}, spike dir {spike_dir}")

    options = ClaudeAgentOptions(
        cwd=spike_dir,
        tools=TOOLS,  # the only built-in tools that exist in the session
        allowed_tools=TOOLS,  # auto-approve them
        permission_mode="dontAsk",  # anything not pre-approved is denied
        setting_sources=[],  # do not load ~/.claude or project settings/CLAUDE.md/hooks
        strict_mcp_config=True,  # no MCP servers, including claude.ai connectors
        env={"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"},
        max_turns=5,
    )

    async for message in query(prompt=PROMPT, options=options):
        print(f"[{type(message).__name__}] {summarize(message)}")
        if isinstance(message, ResultMessage):
            print("--- result ---")
            print(f"result: {message.result!r}")
            print(f"num_turns: {message.num_turns} duration_ms: {message.duration_ms}")
            print(f"total_cost_usd: {message.total_cost_usd}")
            print(f"usage: {message.usage}")
            print(f"model_usage: {message.model_usage}")
            print(f"permission_denials: {message.permission_denials}")


if __name__ == "__main__":
    asyncio.run(main())
