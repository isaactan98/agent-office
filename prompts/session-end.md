## Objective
Close the session cleanly so I can continue on my other machine (JB ↔ SG).

## Steps
1. Run the backend tests (and frontend checks if the frontend exists). Report results.
2. Update `docs/PROGRESS.md`:
   - "Current state" block: phase, machine, blockers.
   - New log entry on top: date, location (ask me: JB or SG), what was done,
     how it was verified (actual commands/results), next step, open questions.
   - Record facts only. If something is unverified, write "unverified".
3. Fill in any `TBD` commands in `CLAUDE.md` that now exist.
4. Show me `git status` and a proposed commit message (Conventional Commits style).
5. Commit only after I say yes. Do NOT push — I push myself.

## Constraints
- Never commit `.env`, `tasks/`, virtualenvs, `node_modules`, or `.nuxt`/`.output`.
- If tests fail, say so in PROGRESS.md under Blockers. Do not hide it.
