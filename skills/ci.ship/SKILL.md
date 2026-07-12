---
name: ci.ship
description: Validate, push, and monitor CI for commits produced by ci.execute. Supports solo mode (direct push to main) and team mode (branch + PR via gh). Delegates pre-flight checks, push, and CI wait to run.py (local).
---

# ci.ship — Publish Commits to GitHub

> **Language note**: All user-facing text below is in English. The orchestrator MUST present all interactions to the user in their language, translating as needed. Generated content (reports, summaries) must also be in the user's language.

## Purpose

Take local commits produced by `ci.execute`, validate them (lint, build, tests), review them with `pr-review-expert`, push to GitHub, and monitor CI. The orchestrator (remote model according to TOKEN_BUDGET) coordinates atomic steps, presents information to the user, and delegates heavy work to `run.py` (local).

## Pipeline

```
ci.prepare  ──>  ci.execute  ──>  ci.ship
(plan)           (commit)         (push + CI)
```

`ci.ship` is the final step — it pushes commits from `ci.execute` to the remote and optionally waits for CI. There is no next skill; the pipeline ends here.

## Architecture

```
Orchestrator (this agent)
  ├─ 1. Resolve WORKDIR
  ├─ 2. Resolve model + show TOKEN_BUDGET
  ├─ 3. Show execution plan
  ├─ 4. Check repo state + remote connection + operation mode
  ├─ 5. Detect checkpoint → resume if applicable
  ├─ 6. Pre-flight: lint, build, tests (run.py)
  ├─ 7. Calculate diff against origin/main
  ├─ 8. Optional review with pr-review-expert (batch by batch)
  ├─ 9. Push to origin/main (run.py)
  ├─ 10. Wait for CI (run.py, optional)
  ├─ 11. Close task plan
  ├─ 12. Execution report
  └─ 13. Token report
```

---

## Step 1 — Resolve working directory

```bash
pwd
```

Use output as `WORKDIR`.

## Step 2 — Resolve model and show TOKEN_BUDGET

```bash
python3 -c "
import sys, os, json
sys.path.insert(0, os.environ['SKILLKIT_HOME'])
from lib import resolve_model
model_id = resolve_model('ci.ship')
print('TOKEN_BUDGET:', os.environ.get('TOKEN_BUDGET', os.environ.get('SKILLKIT_MODE', 'unknown')))
print('Model:', model_id)
print('Provider:', os.environ.get('SKILLKIT_PROVIDER', '?'))
"
```

Display to user:

```
╔══════════════════════════════════════════════════╗
║           CI.SHIP                                ║
╠══════════════════════════════════════════════════╣
║  TOKEN_BUDGET:    <mode>                          ║
║  Model:          <model>                         ║
║  Provider:       <provider>                      ║
║  Workdir:        <workdir>                       ║
║  Description:    Validate, review, push commits  ║
║                  to GitHub and monitor CI        ║
╚══════════════════════════════════════════════════╝
```

## Step 3 — Execution plan

```
Execution Plan
═══════════════

Phase 1 - Check:
  - Git status, remote connection, operation mode
  - Detect checkpoint → resume if applicable

Phase 2 - Pre-flight:
  - lint + build + tests (run.py)
  - Present results, decide on failure

Phase 3 - Review:
  - Optional: pr-review-expert batch by batch
  - Consolidate findings, user decision

Phase 4 - Deploy:
  - Push to origin/main (run.py)
  - Monitor CI (optional, run.py)
  - Close task plan on success

Proceed? (y/n)
```

## Step 4 — Check repo state and remote

### 4.1 — Git status

```bash
git status --short 2>&1
```

If there are uncommitted changes, present to user with `question`:
- "Run ci.prepare first"
- "Ignore and continue"
- "Abort"

### 4.2 — Verify remote

```bash
git remote -v 2>&1
```

If no remote configured, abort with setup instructions.

### 4.3 — Test connection

```bash
git fetch origin main 2>&1
```

If fails, show error and abort.

### 4.4 — Operation mode

Read `ci.config.json` if exists, or ask user:
- "Solo (direct push to main)"
- "Team (branch + PR via gh)"

For team mode, ask branch name. Save to `ci.config.json`.

## Step 5 — Detect checkpoint

```bash
cat /tmp/skillkit/ci_ship_progress.json 2>/dev/null || echo '{"found": false}'
```

Show user which phases are complete and which are pending.

## Step 6 — Pre-flight: lint, build, tests

```bash
cp "$SKILLKIT_HOME/skills/ci.ship/run.py" /tmp/skillkit/ci_ship_run.py
```

```bash
CI_MODE=preflight WORKDIR="$WORKDIR" python3 /tmp/skillkit/ci_ship_run.py
```

`timeout=300000` (5 min). Presents results and asks user on failure.

## Step 7 — Calculate diff against origin/main

```bash
COMMITS_AHEAD=$(git rev-list --count origin/main..HEAD 2>/dev/null || echo "0")
echo "Commits ahead of origin/main: $COMMITS_AHEAD"
```

If 0, nothing to push. Inform and finish.

## Step 8 — Optional review with pr-review-expert

Ask user with `question`:
- "Review code before pushing (pr-review-expert)" — recommended
- "Push without review"

If accepted: obtain diff, run batch-by-batch review via `pr-review-expert/run.py`, consolidate, present findings, let user decide.

## Step 9 — Push to origin/main

Confirm with user, then:

```bash
CI_MODE=push WORKDIR="$WORKDIR" python3 /tmp/skillkit/ci_ship_run.py
```

`timeout=120000` (2 min). Present result.

## Step 10 — Wait for CI (optional)

Ask user, then optionally:

```bash
CI_MODE=ci-wait WORKDIR="$WORKDIR" python3 /tmp/skillkit/ci_ship_run.py
```

`timeout=300000` (5 min). Present CI result.

## Step 11 — Close task plan (if exists)

If CI was successful and a `ci/*_tasks.md` file without `_completed` exists:
1. Append Ship Log to plan's Execution Log
2. Rename to `_completed`

## Step 12 — Execution report

```
╔══════════════════════════════════════════════════╗
║           EXECUTION COMPLETED                    ║
╠══════════════════════════════════════════════════╣
║  Pre-flight:     ✅ PASSED                       ║
║  Review:         ✅ / ⏭️ Skipped                 ║
║  Push:           ✅ N commits to origin/main     ║
║  CI:             ✅ success / ⏭️ Skipped         ║
║  Mode:           solo / team                     ║
╚══════════════════════════════════════════════════╝
```

## Step 13 — Token report

Check `SKILLKIT_PROVIDER` to determine if each phase ran local (Ollama → 🆓) or remote (💰). Build the table dynamically:

```
| Source                   | Calls | Input (tok) | Output (tok) | Total (tok) | Cost |
|---|---|---|---|---|---|---|
| **Remote**               |       |             |              |             |      |
| SKILL.md + orchestration | 1     | 2,500       | —            | 2,500       | 💰   |
{phase rows — place each phase under Remote or Local based on provider}
| **Total {group}**       |       |             |              | **N**      | {💰/🆓} |
|---|---|---|---|---|---|---|---|
{repeat for second group if phases and orchestration are in different groups}
```

For each phase: if `SKILLKIT_PROVIDER=ollama` label as `**Local**` with 🆓, otherwise label as `**Remote**` with 💰. Use actual token counts from run.py output.

---
## Checkpoint & resume

- **Progress**: `/tmp/skillkit/ci_ship_progress.json` tracks `preflight`, `review`, `push`, `ci_wait` phases
- **Resume**: on restart, check progress and resume from last incomplete phase

## Notes

- **Orchestrator model**: resolved via `resolve_model("ci.ship")` according to TOKEN_BUDGET
- **Timeouts**: 300s for pre-flight, 120s for push, 300s for CI wait
- **Never push without explicit user confirmation**
- **Language**: All generated content must be in the user's language without accents or special characters
- **Team mode**: uses `git push -u origin <branch>` instead of main, then `gh pr create`
