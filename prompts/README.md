# prompts/

Paste these into Claude Code (run `claude` in the repo root on the M3 Air).

Every session:
1. `session-start.md` — orient, pull, check state. No coding.
2. One phase prompt (`00` → `07`, in order, one phase per session or two).
3. `session-end.md` — update PROGRESS.md, commit. Push yourself.

Rules of thumb
- Start a new Claude Code session for each phase; context from old phases is in the repo, not the chat.
- If a phase stops at a "STOP and report" gate, don't force it — bring the report back and decide.
- Phase 1 is the go/no-go gate. If the SDK won't run on the Pro login, the plan changes.
