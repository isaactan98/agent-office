## Session Strategy
New session.

## Objective
Get oriented before any work. I sync between JB and SG through GitHub, so the
other machine may have moved the project forward.

## Steps
1. `git status`, `git pull --ff-only`, `git log --oneline -10`. If the pull is not a
   fast-forward or the tree is dirty, stop and tell me — do not merge or stash.
2. Read `CLAUDE.md`, `docs/PLAN.md`, `docs/PROGRESS.md`.
3. If the backend exists, run the backend tests and report pass/fail.

## Output format
Reply in at most 10 lines:
- Current phase and what the last session finished (cite the PROGRESS entry)
- Test result (or "no tests yet")
- Anything that looks inconsistent between PROGRESS.md and the actual code
- The next concrete step

Do NOT write or change any code in this session step. Wait for me to paste a phase prompt.
