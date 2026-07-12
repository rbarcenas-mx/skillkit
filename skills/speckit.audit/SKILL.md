---
name: speckit.audit
description: Progressive audit of spec-kit artifacts. 100% local via Ollama. The remote orchestrator handles the full flow: detects stages, validates timestamps vs resolve.md, marks resolved/pending, calls run.py ONE stage or ONE batch at a time, reports to user, shows progress bar, and consolidates results.
---

# speckit.audit — Progressive Audit of Spec-Kit Artifacts

> **Language note**: All user-facing text (banners, prompts, summaries) below is in English. The orchestrator MUST present all interactions to the user in their language, translating as needed.

## Purpose

Audit spec-kit artifacts progressively. **100% local**: `run.py` is invoked once per stage/batch, returns JSON, and the remote orchestrator (this agent) handles the full flow.

## Architecture

```
Remote Orchestrator (this agent)
  ├─ 1. Detect available stages + latest audit-resolve
  ├─ 2. Validate timestamps: compare resolve.md **Solucion** vs file mtimes
  │      → Mark each stage as ✅ Resolved or ⚠️ Pending
  ├─ 3. Present to user: stage list with status
  │      → Ask: which stage(s) to audit? (shows pending by default)
  ├─ 4. For each requested stage:
  │     ├─ spec/plan/tasks: 1 run.py call each
  │     ├─ code: ONE CALL PER BATCH (never group in for loop)
  │     ├─ EACH call: runs ONE batch, presents result IMMEDIATELY
  │     ├─ Show UPDATED progress bar after each batch
  │     └─ Ask user to continue (required for code)
  ├─ 5. Consolidate results: summary table + findings
  ├─ 6. Token report (local vs remote)
  └─ 7. audit.md updated with global status

GOLDEN RULE: The orchestrator must NEVER group multiple code batches
   in a single bash command (for loop). Each batch is an independent atomic call.
   The user must see progress and decide whether to continue after EACH batch.
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
model_id = resolve_model('audit.spec_plan_tasks')
print('TOKEN_BUDGET:', os.environ.get('TOKEN_BUDGET', os.environ.get('SKILLKIT_MODE', 'unknown')))
print('Model:', model_id)
print('Provider:', os.environ.get('SKILLKIT_PROVIDER', '?'))
"
```

Display to user:

```
╔══════════════════════════════════════════════════╗
║           SPECKIT.AUDIT                          ║
╠══════════════════════════════════════════════════╣
║  TOKEN_BUDGET:    <mode>                          ║
║  Model:          <model>                         ║
║  Provider:       <provider>                      ║
║  Workdir:        <workdir>                       ║
║  Description:    Audit spec-kit artifacts        ║
║                  (spec/plan/tasks/code/lint)     ║
╚══════════════════════════════════════════════════╝
```

## Step 3 — Execution plan

```
Execution Plan
═══════════════

Phase 1 - Detect:
  - Find available stages and feature directory
  - Validate timestamps against resolve.md
  - Mark each stage as resolved or pending

Phase 2 - Audit (per stage/batch):
  - spec/plan/tasks: 1 run.py call each
  - code: census → N batches → run.py per batch
  - lint: 1 run.py call
  - Progress bar updated after each

Phase 3 - Consolidate:
  - Generate audit/{id}-audit.md with auto-incremented ID
  - Summary table with verdicts and counts

Proceed? (y/n)
```

## Step 4 — Copy run.py

```bash
cp "$SKILLKIT_HOME/skills/speckit.audit/run.py" /tmp/skillkit/speckit_audit_run.py
```

## Step 5 — Detect stages and resolve status

Use `detect-stage.sh` for available stages:

```bash
bash "$SKILLKIT_HOME/skills/speckit.audit/scripts/detect-stage.sh" "$WORKDIR"
```

Output JSON with `stage`, `features`, `has_spec`, `has_plan`, `has_tasks`, `has_code`, `code_census`, `batches_suggested`.

### Validate timestamps against resolve.md (REQUIRED)

Determine which stages are resolved and which are pending:

1. **Find latest resolve.md**: `audit/*-audit-resolve.md` (most recent)
2. **If exists**:
   - Extract `**Solucion**: {timestamp}` from resolve.md
   - Extract all referenced files (paths in backticks, src/...)
   - Get max mtime of those files
   - If `timestamp_solucion > max mtime` → everything covered is resolved
3. **Determine stage status**:
   - For spec/plan/tasks: compare source file mtime vs timestamp_solucion
   - For code: compare files in each batch vs timestamp_solucion
   - All files older than timestamp → ✅ Resolved
   - Any file newer → ⚠️ Pending

## Step 6 — Present stages to user

```
Detected stages:
  spec       → ✅ Resolved (timestamp > file mtime)
  plan       → ✅ Resolved
  tasks      → ✅ Resolved
  code       → ⚠️ Pending (files modified after resolve)
    ├─ models (1)      → ✅
    ├─ services (2)    → ⚠️ Pending
    └─ ...
  lint       → ✅ Resolved
```

Ask user: "What do you want to audit? (shows pending by default)"

Options:
- A: Audit only pending stages
- B: Audit everything (force re-audit)
- C: Select specific stages
- D: Cancel

## Step 7 — Audit spec/plan/tasks (1 call each)

```bash
AUDIT_WORKDIR="$WORKDIR" \
AUDIT_FEATURE="<feature>" \
AUDIT_STAGE="<spec|plan|tasks>" \
python3 /tmp/skillkit/speckit_audit_run.py
```

Returns JSON with `status`, `stage`, `result.veredicto`, `result.report`, `checkpoint`.

## Step 8 — Audit code (ONE batch per call, NEVER group)

First, census the code:

```bash
bash "$SKILLKIT_HOME/skills/speckit.audit/scripts/census-code.sh" "$WORKDIR"
```

CRITICAL: Execute ONE batch at a time. Each batch is an independent call to `run.py`.

```bash
AUDIT_WORKDIR="$WORKDIR" \
AUDIT_FEATURE="<feature>" \
AUDIT_STAGE="codigo" \
AUDIT_BATCH="0" \
python3 /tmp/skillkit/speckit_audit_run.py
# ← PRESENT RESULTS, ASK TO CONTINUE

# Batch 1 — only if user said "yes"
AUDIT_BATCH="1" \
python3 /tmp/skillkit/speckit_audit_run.py
```

## Step 9 — Audit lint (1 call)

```bash
AUDIT_WORKDIR="$WORKDIR" \
AUDIT_FEATURE="<feature>" \
AUDIT_STAGE="lint" \
python3 /tmp/skillkit/speckit_audit_run.py
```

## Step 10 — Between each batch/stage, report to user (REQUIRED)

EVERY time run.py finishes, IMMEDIATELY present:

1. **Overall progress bar** with ALL stages/batches
2. **Immediate result** of the just-finished batch/stage
3. **New critical findings** (if any) — 1 line each
4. **Ask user**: "Continue with next stage/batch?"

NEVER present results from multiple batches at once.

## Step 11 — Consolidate and present final summary

When all stages/batches are complete:

1. **Consolidate with run.py** to generate session file:

```bash
AUDIT_WORKDIR="$WORKDIR" \
AUDIT_FEATURE="<feature>" \
AUDIT_CONSOLIDATE='[{"stage":"spec","veredicto":"...",...}]' \
python3 /tmp/skillkit/speckit_audit_run.py
```

Generates `audit/{next_id}-{YYYYMMDD}-{HHMM}-audit.md`.

2. **Final progress bar** at 100%
3. **Summary table**: stage, verdict, criticals, warnings, observations
4. **Consolidated critical findings** from all stages
5. **Session file** generated

## Step 12 — Execution report

```
╔══════════════════════════════════════════════════╗
║           EXECUTION COMPLETED                    ║
╠══════════════════════════════════════════════════╣
║  Stages audited:  spec, plan, code (M batches)   ║
║  Audit file:      audit/<id>-audit.md            ║
║  Critical:        N                              ║
║  Warnings:        W                              ║
║  Observations:    O                              ║
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

## Step 14 — Link to speckit.audit-resolve

After the token report, ask the user (present in the user's language):

```
╔══════════════════════════════════════════════════╗
║   Critical findings need resolution.            ║
║                                                 ║
║   speckit.audit-resolve is the skill in charge  ║
║   of resolving the findings found.              ║
║                                                 ║
║   Do you want to resolve findings now?          ║
╚══════════════════════════════════════════════════╝
```

If yes → the orchestrator should pass control to `speckit.audit-resolve` or instruct the user:

```bash
opencode --skill speckit.audit-resolve
```

If no → audit is complete. Findings remain in `audit/{id}-audit.md` for later resolution.

---

## Checkpoint & resume

- **Checkpoints**: `audit/checkpoints/` — one file per stage/batch
- **Session file**: `audit/{id}-audit.md` — auto-generated with next available ID
- **Resume**: checkpoints are read on restart. Completed stages/batches are skipped.

## Notes

- **Models**: resolved via `resolve_model()` according to TOKEN_BUDGET (`audit.spec_plan_tasks` for spec/plan/tasks, `audit.codigo` for code, `audit.lint` for lint)
- **Language**: All generated content must be in the user's language without accents or special characters
- **Timeouts**: 300s per code batch, 120s for spec/plan/tasks, 120s for lint
