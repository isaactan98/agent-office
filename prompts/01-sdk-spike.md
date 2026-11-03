## Session Strategy
New session. Read `CLAUDE.md` first.

## Objective
Prove the Claude Agent SDK (Python) runs from this backend on my Claude Pro
subscription login, sandboxed to a scratch directory. This is a go/no-go gate for
the whole project.

## Context
Phase 0 is done (backend skeleton with uv). Claude Code CLI is logged in with my
Pro account. I have NO API key and will not create one.

## Target State
- `backend/spikes/sdk_spike.py`: runs ONE tiny task — "Create notes.md containing a
  3-line haiku about Johor Bahru traffic" — with:
  - working directory = a fresh `TASKS_DIR/spike-<timestamp>/`
  - allowed tools limited to file read/write only (no Bash, no web)
  - settings isolation so nothing from `~/.claude` (my personal settings, hooks,
    CLAUDE.md) is loaded
  - prints each SDK message type and a one-line summary as it streams
  - prints the final result message, including any usage/cost fields the SDK returns
- `backend/spikes/README.md`: what you verified, SDK version, and anything surprising.

## Scope
- Work only in: `backend/spikes/`, `backend/pyproject.toml` (to add the dependency).
- Do NOT touch: `backend/app/`, `frontend/`, `docs/`, `~/.claude`, my shell profile.

## Constraints
- Add exactly one dependency: `claude-agent-sdk`.
- **NEVER set, export, or read `ANTHROPIC_API_KEY`.** Before running, confirm it is
  not set in the environment (`env | grep -i anthropic`, print only variable names).
- Before writing code, open the installed package's type definitions and the
  official Agent SDK docs. Use only option, class and hook names that exist in the
  installed version. List the names you verified in `spikes/README.md`.
- Only make changes directly requested.

## Acceptance Criteria
- [ ] Spike runs end-to-end and `notes.md` exists inside the spike directory only
- [ ] No file was created or modified outside that spike directory
      (show `git status` and a listing of the spike dir)
- [ ] Output shows the run used my subscription login, not an API key
- [ ] `spikes/README.md` lists the verified SDK names and the version

## Action Boundaries
- Run the spike at most 2 times total. Each run spends my usage.
- **STOP immediately and report** if the SDK errors about authentication, asks for
  an API key, or tries to use one. Do not attempt workarounds. That means the
  project plan needs to change and I decide how.
- Stop and ask before any other dependency or any change outside scope.

## Progress Evidence
End with: the raw streamed output of the successful run (trimmed to 40 lines), the
verified-names list, and your go/no-go recommendation in one sentence.
