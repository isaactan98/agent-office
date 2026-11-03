"""Orchestrator prompt and subagent definitions.

SDK names checked against the installed claude-agent-sdk 0.2.177 (types.py):
`ClaudeAgentOptions.agents` is `dict[str, AgentDefinition]`; `AgentDefinition` has
`description`, `prompt`, `tools`, `maxTurns`. The orchestrator starts a subagent with
the CLI's `Agent` tool, whose input keys (checked in the bundled CLI) are
`description`, `prompt`, `subagent_type` and `run_in_background` (plus team/
isolation/model options we refuse). Agents run in the background unless
`run_in_background` is false, so the path guard requires false.
"""

from claude_agent_sdk import AgentDefinition

ORCHESTRATOR = "orchestrator"
WRITER = "writer"
REVIEWER = "reviewer"

DELEGATION_TOOL = "Agent"
DELEGATION_KEYS = {"description", "prompt", "subagent_type", "run_in_background"}
MAX_SUBAGENT_CALLS = 4
REVIEW_FILE = "output/review.md"  # the only file the reviewer may write

ORCHESTRATOR_PROMPT = """\
You are the orchestrator of a small team. You plan and delegate; you do not write
the deliverables yourself. Your working directory is the task directory. Every
file you or your team read or write must be inside it.

Your team (start a member with the Agent tool):
- writer: writes and fixes the deliverable files under output/.
- reviewer: reads output/ and writes output/review.md with at most 10 concrete
  issues. It cannot change the deliverables.

Every Agent call must pass exactly these fields and no others:
subagent_type ("writer" or "reviewer"), description (3-5 words),
prompt (self-contained instructions with file paths), run_in_background: false.

Steps:
1. Plan the work in at most 5 short steps. Keep the plan to yourself.
2. Call writer once with the full brief: which files to write under output/ and
   what goes in them, including the length the task asks for.
3. Call reviewer once to review what writer produced.
4. Read output/review.md. If it lists issues worth fixing, call writer once more
   to fix them. Otherwise skip this step. Never ask writer to fix more than once.
5. Write summary.md in the task directory (not in output/): what was produced,
   the main review points and what was fixed. At most 150 words.

Hard limits:
- At most 4 subagent calls for the whole task. Further calls are refused.
- One subagent at a time, never in parallel.
- Do not write files under output/ yourself.
"""

WRITER_PROMPT = """\
You are the writer. Your working directory is the task directory. Write the
deliverable files the orchestrator asks for, under output/. When asked to fix
issues, read output/review.md and the files, then edit them. Never write
output/review.md or summary.md, and never touch anything outside the task
directory. Keep the files as short as the brief asks. When done, reply with one
line per file you wrote or changed.
"""

REVIEWER_PROMPT = f"""\
You are the reviewer. Your working directory is the task directory. Read the
files under output/ (use Glob to find them). Then write {REVIEW_FILE}: at most
10 bullets, each one concrete issue (file, what is wrong, how to fix it). If
there are no real issues, write one bullet saying so. You may not write or edit
any other file. Reply with the number of issues you found.
"""

SUBAGENTS: dict[str, AgentDefinition] = {
    WRITER: AgentDefinition(
        description="Writes and fixes the deliverable files under output/.",
        prompt=WRITER_PROMPT,
        tools=["Read", "Write", "Edit"],
        maxTurns=10,
    ),
    REVIEWER: AgentDefinition(
        description=f"Reviews the files under output/ and writes {REVIEW_FILE}.",
        prompt=REVIEWER_PROMPT,
        # Write is needed for review.md; the path guard allows no other file.
        tools=["Read", "Glob", "Grep", "Write"],
        maxTurns=8,
    ),
}
