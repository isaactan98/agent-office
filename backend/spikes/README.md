# Phase 1 spike: Agent SDK on the Pro login

`sdk_spike.py` runs one tiny task ("Create notes.md containing a 3-line haiku about
Johor Bahru traffic") in a fresh `TASKS_DIR/spike-<timestamp>/` and prints every
streamed message plus the final result.

```
cd backend && uv run python spikes/sdk_spike.py
```

## Versions
- `claude-agent-sdk` 0.2.177 (bundles Claude Code CLI 2.1.317, `_bundled/claude`;
  `cli_path` not set, so the bundled binary is used)
- Python 3.12.11

## What was verified (run on 2026-11-03, SG, 1 run)
- **Auth:** the `system`/`init` message reported `apiKeySource='none'`, which the
  SDK documents as "no API key in use, e.g. a claude.ai login". `ANTHROPIC_API_KEY`
  was not set; the script also refuses to start if the variable exists (checks the
  name only, never reads the value).
- **Sandbox:** init reported `cwd=<spike dir>`, `tools=['Read', 'Write']`,
  `permissionMode='dontAsk'`, `mcp_servers=[]`. The agent made one `Write` call, to
  `<spike dir>/notes.md`. `permission_denials: []`.
- **Settings isolation:** none of my `~/.claude/skills` (brandkit, chatcut-*, ...)
  appeared in the init `skills` list; no MCP servers loaded.
- **Files:** inside the repo, the only new file outside gitignored bytecode
  (`__pycache__/*.pyc`) was `tasks/spike-20261103-184208/notes.md`.
- **Result:** `subtype=success`, 2 turns, ~8.6 s.

## Verified SDK names (installed `types.py` + official docs)
- Functions/classes: `query`, `ClaudeAgentOptions`, `__version__`
- Messages: `SystemMessage` (`subtype`, `data`; `init` data has `apiKeySource`,
  `cwd`, `tools`, `mcp_servers`, `model`, `permissionMode`, `skills`, `plugins`,
  `claude_code_version`), `AssistantMessage`, `UserMessage`, `ResultMessage`
  (`subtype`, `is_error`, `result`, `num_turns`, `duration_ms`, `total_cost_usd`,
  `usage`, `model_usage`, `permission_denials`)
- Blocks: `TextBlock`, `ThinkingBlock`, `ToolUseBlock`, `ToolResultBlock`
- Options used: `cwd`, `tools`, `allowed_tools`, `permission_mode` (`"dontAsk"`),
  `setting_sources` (`[]`), `strict_mcp_config`, `env`, `max_turns`
- Env var: `CLAUDE_CODE_DISABLE_AUTO_MEMORY`

## Surprises / things to know
- **`allowed_tools` does not restrict tools**, it only auto-approves them. The
  restriction comes from `tools=[...]` (which built-in tools exist) plus
  `permission_mode="dontAsk"` (deny anything not pre-approved).
- **`setting_sources=None` (the default) loads `~/.claude`** user settings, hooks,
  CLAUDE.md, skills. `[]` is the isolation mode (docs: in SDK <= 0.1.59, `[]` was
  treated like `None`; fine in 0.2.177).
- Read **regardless** of `setting_sources` (docs, "What settingSources does not
  control"): managed policy, `~/.claude.json`, auto memory (disabled here via env),
  claude.ai MCP connectors (disabled here via `strict_mcp_config=True`).
- The CLI process itself still writes to `~/.claude`: a session transcript under
  `~/.claude/projects/<spike-path>/`, a `~/.claude/backups/.claude.json.backup.*`,
  and a built-in plugin store file. These are CLI bookkeeping, not agent tool calls.
  `CLAUDE_CONFIG_DIR` could relocate them, but that may also move the login; untested.
- Init still lists CLI-**bundled** skills (design, verify, debug, ...) and built-in
  plugins (telemetry, privacy, ...). They are not from `~/.claude`, and the `Skill`
  tool is not in `tools`, so they cannot be invoked. `skills=[]` would hide them.
- Default model was `claude-opus-5-5` (plus a tiny `claude-haiku-5-5` side call).
  `total_cost_usd` (~$0.021) is a list-price estimate (`costBasis: 'list'`), not a
  bill; on the Pro login it counts against subscription usage. A `RateLimitEvent`
  message also streams.
- No PreToolUse path hook yet (not in this phase's scope). With `Write` pre-approved,
  nothing but the model's choice kept the write inside `cwd`. The hook is still needed.
- The spike was run with a stripped environment (`env -i` keeping only HOME, USER,
  PATH, ...) because the shell it was launched from (Claude desktop app) exports
  `ANTHROPIC_BASE_URL` and `CLAUDE_CODE_*` variables. The SDK merges the parent
  environment into the CLI subprocess, so the backend should be started from a
  plain terminal, not from inside another Claude Code session.
- The Agent SDK quickstart says: unless previously approved, Anthropic does not
  allow third-party developers to offer claude.ai login or rate limits in their
  products. This project is personal and single-user, not a product offered to
  others; noted here so the decision is explicit.
