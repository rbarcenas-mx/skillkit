---
name: speckit.audit-resolve
description: Resolves audit findings post-speckit.audit. 100% local via Ollama. The remote orchestrator handles the full flow: diagnoses checkpoints, generates resolve.md, presents checklist to user, resolves findings with appropriate model per type, shows progress bar and checkpoint, finishes with solution timestamp > mtime of modified files.
---

# speckit.audit-resolve — Audit Finding Resolution

## Purpose

Resolve critical findings identified by `speckit.audit`, generating an `audit/{id}-audit-resolve.md` file with per-stage checklist, executing resolution with the appropriate model per finding type, and leaving a solution timestamp strictly greater than the mtimes of modified files, so `speckit.audit` does not re-audit what was already resolved.

## Architecture

```
Remote Orchestrator (this agent)
  ├─ 1. Diagnose: run.py MODE=diagnose
  │      → Reads checkpoints → generates audit/{id}-audit-resolve.md
  ├─ 2. Present full findings list to user
  │      → Ask: a) Resolve all  b) Resolve by stage  c) Other action
  ├─ 3. Option A: run.py MODE=resolve (all stages)
  │      Option B: ask which stage → run.py MODE=resolve_stage
  │      → Show banner with mode, model, provider, reason
  │      → Live progress bar, checkpoint for resume
  ├─ 4. If by stage: present solution report for stage
  ├─ 5. Finalize: run.py MODE=finalize
  │      → verify_timestamps(): ts > mtime of referenced files
  │      → Write **Solucion**: in resolve.md, touch
  └─ 6. Consolidated report + token table
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
model_id = resolve_model('audit.resolve_spec')
print('TOKEN_BUDGET:', os.environ.get('TOKEN_BUDGET', os.environ.get('OPENCODE_MODO', 'unknown')))
print('Model:', model_id)
print('Provider:', os.environ.get('OPENCODE_PROVEEDOR', '?'))
"
```

Display to user:

```
╔══════════════════════════════════════════════════╗
║           SPECKIT.AUDIT-RESOLVE                  ║
╠══════════════════════════════════════════════════╣
║  TOKEN_BUDGET:    <mode>                          ║
║  Model:          <model>                         ║
║  Provider:       <provider>                      ║
║  Workdir:        <workdir>                       ║
║  Description:    Resolve audit findings with     ║
║                  model per finding type          ║
╚══════════════════════════════════════════════════╝
```

## Step 3 — Execution plan

```
Execution Plan
═══════════════

Phase 1 - Diagnose:
  - Scan checkpoints → extract findings
  - Generate audit/{id}-audit-resolve.md with checklist

Phase 2 - Resolve:
  - Per stage: resolve findings with appropriate model
  - spec/plan/tasks → audit.resolve_spec model
  - code → audit.resolve_codigo model
  - Apply suggestions, track progress

Phase 3 - Finalize:
  - Verify timestamps (ts > mtime of all referenced files)
  - Write **Solucion**: timestamp to resolve.md
  - Touch file to sync mtime

Proceed? (y/n)
```

## Step 4 — Diagnose (run.py MODE=diagnose)

```bash
cp "$HOME/.claude/skills/speckit.audit-resolve/run.py" /tmp/opencode/audit_resolve_run.py

AUDIT_WORKDIR="$WORKDIR" python3 /tmp/opencode/audit_resolve_run.py
```

Default mode is `diagnose`. Output JSON with `status`, `resolve_path`, `total_findings`, `audit_id`, `stages`.

## Step 5 — Present findings and ask user

Read `resolve_path` file and present to user.

Ask with `question` tool: "Found N findings in M stages. What do you want to do?"

Options:
- A: Resolve all findings (all stages)
- B: Resolve a specific stage
- C: Other action

## Step 6 — Resolve

### Option A — Resolve all stages

```bash
AUDIT_WORKDIR="$WORKDIR" \
AUDIT_RESOLVE_MODE=resolve \
AUDIT_RESOLVE_ACTION=solve \
python3 /tmp/opencode/audit_resolve_run.py
```

### Option B — Resolve one stage

```bash
AUDIT_WORKDIR="$WORKDIR" \
AUDIT_RESOLVE_MODE=resolve_stage \
AUDIT_RESOLVE_STAGE="<exact stage name>" \
AUDIT_RESOLVE_ACTION=solve \
python3 /tmp/opencode/audit_resolve_run.py
```

The script iterates each finding, resolves model per type, builds prompt with finding context, sends to model, receives diff, applies via `apply_suggestion()`, updates progress.

## Step 7 — Finalize (with timestamp verification)

```bash
AUDIT_WORKDIR="$WORKDIR" \
AUDIT_RESOLVE_MODE=finalize \
python3 /tmp/opencode/audit_resolve_run.py
```

Verifies `**Solucion**: <ts>` with ts strictly > mtime of all referenced files. Returns JSON with status and verified timestamp.

## Step 8 — Execution report

```
╔══════════════════════════════════════════════════╗
║           EXECUTION COMPLETED                    ║
╠══════════════════════════════════════════════════╣
║  Resolve file:   audit/<id>-audit-resolve.md     ║
║  Findings:       N total, M resolved             ║
║  Changes applied: C                              ║
║  Solution ts:    <ISO8601>                       ║
╚══════════════════════════════════════════════════╝
```

## Step 9 — Token report

```
| Source                   | Calls | Input (tok) | Output (tok) | Total (tok) | Cost |
|---|---|---|---|---|---|---|
| **Remote**               |       |             |              |             |      |
| SKILL.md + orchestration | 1     | 2,000       | —            | 2,000       | 💰   |
| **Total remote**         |       |             |              | **2,000**   |      |
|                          |       |             |              |             |      |
| **Local**                |       |             |              |             |      |
| Diagnose (no model)      | 1     | —           | —            | —           | 🆓   |
| Resolve spec/plan/tasks  | N     | X,XXX       | X,XXX        | X,XXX       | 🆓   |
| Resolve code             | N     | X,XXX       | X,XXX        | X,XXX       | 🆓   |
| Finalize (no model)      | 1     | —           | —            | —           | 🆓   |
| **Total local**          | **N** | **XX,XXX**  | **XX,XXX**   | **XX,XXX**  | 🆓   |
|---|---|---|---|---|---|---|
| Remote share             |       |             |              | X,XXX (~X%)  | 💰   |
| Local share              |       |             |              | XX,XXX (~X%) | 🆓   |
```

---

## Checkpoint & resume

- **Progress**: `/tmp/opencode/audit_resolve_progress.json` tracks `stage_name`, `finding_index`, `completed_stages`, `completed_findings`
- **Resume**: On restart, completed findings are skipped from progress file

## Notes

- **Models**: spec/plan/tasks → `audit.resolve_spec`; code → `audit.resolve_codigo`, both via TOKEN_BUDGET
- **Language**: All content in Spanish without accents or special characters
- **Generated file**: `audit/{id}-audit-resolve.md` (same ID as the audit it resolves)
- **No model in diagnose/finalize**: file operations and regex only
- **Timestamp verified**: finalize guarantees `**Solucion**: <ts>` with ts > mtime of all referenced files
- **If diff doesn't apply**: orchestrator applies change manually with `edit` tool
