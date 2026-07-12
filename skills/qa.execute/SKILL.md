---
name: qa.execute
description: Execute a QA validation plan locally — runs Docker, migrations, tests, HTTP flows, stress tests with progress bar, checkpoints, and error recovery. Orchestrated by model resolved via resolve_model().
---

# qa.execute — QA Validation Plan Execution

> **Language note**: All user-facing text below is in English. The orchestrator MUST present all interactions to the user in their language, translating as needed. Generated content (plan logs, reports) must also be in the user's language.

## Purpose

Execute individual QA plans (infra, unit, flow, stress, scale) or plan suites sequentially. Supports `shell`, `http`, and `stress` step types delegating to specialized drivers. Progress bar, checkpoints, Docker recovery, and model-based decision (resolved via `resolve_model("qa.execute")`) on failures.

## Architecture

```
$SKILLKIT_HOME/skills/qa.execute/
├── SKILL.md
├── run.py                    # Main orchestrator
│                              #   - Parses plan (YAML between --- STEP)
│                              #   - Delegates to drivers by type
│                              #   - Normal mode: execute individual plan
│                              #   - Suite mode: execute sequence with dependencies
├── drivers/
│   ├── shell.py              # type: shell → subprocess.run
│   ├── http.py               # type: http → urllib + context variables
│   └── stress.py             # type: stress → autocannon/hey/wrk
└── lib/
    ├── progress.py           # Progress bar
    ├── checkpoint.py         # Per-step checkpoint (log in plan)
    ├── decision.py           # Model query (RETRY/SKIP/ABORT) via resolve_model("qa.execute")
    └── recovery.py           # Docker auto-recovery
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
model_id = resolve_model('qa.execute')
print('TOKEN_BUDGET:', os.environ.get('TOKEN_BUDGET', os.environ.get('SKILLKIT_MODE', 'unknown')))
print('Model:', model_id)
print('Provider:', os.environ.get('SKILLKIT_PROVIDER', '?'))
"
```

Display to user:

```
╔══════════════════════════════════════════════════╗
║           QA.EXECUTE                             ║
╠══════════════════════════════════════════════════╣
║  TOKEN_BUDGET:    <mode>                          ║
║  Model:          <model>                         ║
║  Provider:       <provider>                      ║
║  Workdir:        <workdir>                       ║
║  Description:    Execute QA validation plans     ║
╚══════════════════════════════════════════════════╝
```

## Step 3 — Execution plan

```
Execution Plan
═══════════════

Phase 1 - Select:
  - List available QA plans in qa/
  - User selects plan or suite to execute

Phase 2 - Execute:
  - Parse plan steps (YAML between --- STEP)
  - Run each step via shell/http/stress drivers
  - Progress bar, checkpoints after each step
  - On failure: model decides RETRY/SKIP/ABORT
  - Suite mode: sequential plans with dependencies, teardown at end

Phase 3 - Close:
  - If successful: rename plan to *_completed.md
  - Add execution summary to plan

Proceed? (y/n)
```

## Step 4 — Select QA plan file

```bash
ls qa/*_plan.md 2>/dev/null | grep -v '_completed'
```

If multiple, ask user which to use. If only one, use it directly. Plans with `_completed` suffix are ignored.

## Step 5 — Copy and execute script

```bash
rm -rf /tmp/skillkit/qa_execute && cp -r $SKILLKIT_HOME/skills/qa.execute /tmp/skillkit/qa_execute
```

```bash
QA_PLAN_FILE=/absolute/path/to/qa/{id}_plan.md \
WORKDIR=<WORKDIR> \
python3 /tmp/skillkit/qa_execute/run.py
```

`timeout=900000` (15 min).

The script: auto-detects individual plan vs suite, parses YAML steps, delegates to driver, progress bar per step, checkpoint after each step, model-based decision on failure, suite mode respects dependencies and runs teardown.

## Step 6 — Present results

Read the plan file (Execution Log section updated). Show consolidated summary:
- Plans OK vs with failures (suite mode)
- Steps completed, failed, skipped
- Scenario checklist vs results

## Step 7 — Close plan on completion

If execution was successful (0 failures), close the plan:

### Add QA Log to plan
Append execution summary to the plan: date, total steps, successful, failed, total duration.

### Rename to `_completed`

```bash
ORIGINAL="<path/to/executed/plan>"
if [ -f "$ORIGINAL" ]; then
  BASENAME=$(basename "$ORIGINAL" .md)
  mv "$ORIGINAL" "$(dirname $ORIGINAL)/${BASENAME}_completed.md"
  echo "Plan closed: ${BASENAME}_completed.md"
fi
```

For suite plans, rename all associated individual plans as well.

## Step 8 — Execution report

```
╔══════════════════════════════════════════════════╗
║           EXECUTION COMPLETED                    ║
╠══════════════════════════════════════════════════╣
║  Plan type:     infra / unit / flow / suite      ║
║  Steps total:   N                                ║
║  Completed:     C  ✅                            ║
║  Failed:        F  ❌                            ║
║  Skipped:       S  ⏭️                            ║
║  Duration:      Xm Ys                            ║
╚══════════════════════════════════════════════════╝
```

## Step 9 — Token report

Check `SKILLKIT_PROVIDER` to determine if each phase ran local (Ollama → 🆓) or remote (💰). Build the table dynamically:

```
| Source                   | Calls | Input (tok) | Output (tok) | Total (tok) | Cost |
|---|---|---|---|---|---|---|
| **Remote**               |       |             |              |             |      |
| SKILL.md + orchestration | 1     | X,XXX       | —            | X,XXX       | 💰   |
{phase rows — place each phase under Remote or Local based on provider}
| **Total {group}**       |       |             |              | **N**      | {💰/🆓} |
|---|---|---|---|---|---|---|---|
{repeat for second group if phases and orchestration are in different groups}
```

For each phase: if `SKILLKIT_PROVIDER=ollama` label as `**Local**` with 🆓, otherwise label as `**Remote**` with 💰. Use actual token counts from run.py output.

---
## Checkpoint & resume

- **Per-step checkpoint**: each completed step is logged immediately in the plan's Execution Log
- **Resume**: re-executing a plan skips steps marked with ✅, re-evaluates ❌ steps with model decision

## Notes

- **Language**: All generated content must be in the user's language without accents or special characters
- **Orchestrator model**: resolved via `resolve_model("qa.execute")` according to TOKEN_BUDGET
- **Drivers**: loaded on demand by `run.py` based on step `type`
- **Timeout**: `900000` (15 min) for main script execution
- **Failure → local decision**: `lib/decision.py` sends error context to model
- **Docker recovery**: `lib/recovery.py` auto-detects and starts Docker on Linux/WSL
- **Low risk**: only operates Docker, npm, Prisma, Jest, and local HTTP. No git, no real credentials, no push.
