---
name: speckit.audit-resolve
description: Resolves audit findings post-speckit.audit. 100% local via Ollama. The remote orchestrator handles the full flow: diagnoses checkpoints, generates resolve.md, presents checklist to user, resolves findings with appropriate model per type, shows progress bar and checkpoint, finishes with solution timestamp > mtime of modified files.
---

# speckit.audit-resolve — Audit Finding Resolution

> **Language note**: All user-facing text (banners, prompts, summaries) below is in English. The orchestrator MUST present all interactions to the user in their language, translating as needed.

## Purpose

Resolve critical findings identified by `speckit.audit`, generating an `audit/{id}-audit-resolve.md` file with per-stage checklist, executing resolution with the appropriate model per finding type, and leaving a solution timestamp strictly greater than the mtimes of modified files, so `speckit.audit` does not re-audit what was already resolved.

## Architecture

```
Remote Orchestrator (this agent)
  ├─ 1. Diagnose: run.py MODE=diagnose
  │      → Reads checkpoints → generates audit/{id}-audit-resolve.md
  ├─ 2. Present findings + strategy options
  │      → Recommend: stage by stage (spec → plan → tasks → code)
  ├─ 3. For each stage (spec → plan → tasks → code):
  │     ├─ Show stage banner + model
  │     ├─ Generate proposals (action=suggest)
  │     ├─ Present each finding WITH proposed solution
  │     ├─ Ask user confirmation
  │     ├─ If confirmed → apply (action=solve)
  │     └─ Show stage summary report
  ├─ 4. Finalize: run.py MODE=finalize
  │      → verify_timestamps(): ts > mtime of referenced files
  │      → Write **Solucion**: in resolve.md, touch
  └─ 5. Consolidated report + token table
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
print('TOKEN_BUDGET:', os.environ.get('TOKEN_BUDGET', os.environ.get('SKILLKIT_MODE', 'unknown')))
print('Model:', model_id)
print('Provider:', os.environ.get('SKILLKIT_PROVIDER', '?'))
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
cp "$SKILLKIT_HOME/skills/speckit.audit-resolve/run.py" /tmp/skillkit/audit_resolve_run.py

AUDIT_WORKDIR="$WORKDIR" python3 /tmp/skillkit/audit_resolve_run.py
```

Default mode is `diagnose`. Output JSON with `status`, `resolve_path`, `total_findings`, `audit_id`, `stages`.

## Step 5 — Present findings and choose strategy

Read `resolve_path` file and present findings to user.

Inform the user (present in the user's language):

```
Found N findings across M stages.

Resolution proceeds from specification to code, in this fixed order:
  spec → plan → tasks → code

Strategy options:
  • Stage by stage (RECOMMENDED):
    For each stage you will see the findings, review the proposed
    solution for each one, confirm before applying, see the result,
    and then move to the next stage.

  • Auto-resolve all:
    Resolve everything in one pass without intermediate review.
    Faster but no opportunity to reject individual changes.
```

Ask with `question` tool (present options in the user's language):

Options:
- **A: Resolve all automatically** — no stage-by-stage review, no intermediate confirmation. Batched execution.
- **B: Resolve stage by stage with confirmation (RECOMMENDED)** — see findings + proposed solutions, confirm each stage before applying.
- **C: Other action** — cancel or save for later.

If B (or default): proceed to Step 6 (stage-by-stage resolution).
If A: proceed to "Auto-resolve all stages" (Step 6a).
If C: handle as needed.

## Step 6 — Resolve by stages (default, RECOMMENDED)

Loop through stages in fixed order: **spec → plan → tasks → code** (always from specification forward, never start from code).

### Per-stage flow

For each stage that has findings, follow this EXACT flow:

```
  ╔══════════════════════════════════════════════════════╗
  ║  1. Show stage banner + model                        ║
  ║  2. Generate proposals (action=suggest)               ║
  ║  3. Present findings + proposed solutions             ║
  ║  4. Ask confirmation                                  ║
  ║  5. If confirmed → apply (action=solve)               ║
  ║  6. Present stage summary report                      ║
  ║  7. Proceed to next stage                             ║
  ╚══════════════════════════════════════════════════════╝
```

### Step 6.1 — Stage banner

Resolve the model for this stage type:

```bash
# For spec, plan, tasks:
python3 -c "
import sys, os
sys.path.insert(0, os.environ['SKILLKIT_HOME'])
from lib import resolve_model
model_id = resolve_model('audit.resolve_spec')
print('Mode:', os.environ.get('TOKEN_BUDGET', os.environ.get('SKILLKIT_MODE', 'unknown')))
print('Model:', os.environ.get('SKILLKIT_MODEL', '?'))
print('Provider:', os.environ.get('SKILLKIT_PROVIDER', '?'))
print('Description:', os.environ.get('SKILLKIT_MODEL_DESC', '?'))
"

# For code:
python3 -c "
import sys, os
sys.path.insert(0, os.environ['SKILLKIT_HOME'])
from lib import resolve_model
model_id = resolve_model('audit.resolve_codigo')
print('Mode:', os.environ.get('TOKEN_BUDGET', os.environ.get('SKILLKIT_MODE', 'unknown')))
print('Model:', os.environ.get('SKILLKIT_MODEL', '?'))
print('Provider:', os.environ.get('SKILLKIT_PROVIDER', '?'))
print('Description:', os.environ.get('SKILLKIT_MODEL_DESC', '?'))
"
```

Display per-stage banner:

```  
╔══════════════════════════════════════════════════════════════╗
║  Stage:          <spec|plan|tasks|code>                     ║
║  Findings:       <N>                                        ║
║                                                             ║
║  TOKEN_BUDGET:   <low|medium|high>                          ║
║  Model:          <model_id>                                 ║
║  Provider:       <provider>                                ║
║                                                             ║
║  Why this model:                                            ║
║  <Reason why it is the best model in its mode>              ║
╚══════════════════════════════════════════════════════════════╝
```

Rationale per stage type:

| Stage | Budget | Model | Why best |
|-------|--------|-------|----------|
| spec/plan/tasks | low | `gemma4:26b` | Local multilingual, ideal for Spanish specs at zero cost. |
| spec/plan/tasks | medium | `deepseek-v4-flash` | Fast, good cost-quality balance, strong reasoning for documents. |
| spec/plan/tasks | high | `deepseek-v4-pro` | Premium deep reasoning for complex specifications. |
| code | low | `deepseek-coder-v2:16b` | Local specialized in code generation and review. |
| code | medium/high | `kimi-k2.7-code` | Remote code-specialized, maximum quality for code resolution. |

### Step 6.2 — Generate proposals (suggest mode)

Run the model in **suggest** mode to generate proposed solutions WITHOUT applying them:

```bash
AUDIT_WORKDIR="$WORKDIR" \
AUDIT_RESOLVE_MODE=resolve_stage \
AUDIT_RESOLVE_STAGE="<stage>" \
AUDIT_RESOLVE_ACTION=suggest \
python3 /tmp/skillkit/audit_resolve_run.py
```

This generates and stores suggestions in `/tmp/skillkit/audit_resolve_suggestion_<stage>_*.md` but does NOT modify any source files.

### Step 6.3 — Present findings with proposed solutions

Read the suggestions from `/tmp/skillkit/audit_resolve_suggestion_*` or parse the output JSON.

For EACH finding in the stage, present (in the user's language):

```
Hallazgo <finding_id>: <descripción>
  Archivo: <archivo>
  Acción requerida: <accion>
  ─────────────────────────────────────
  Solución propuesta:
  <suggestion_preview>

  [Ver detalle completo: /tmp/skillkit/audit_resolve_suggestion_<stage>_<idx>.md]
```

**Present ALL findings of the stage together**, each with its proposal, before asking for confirmation. The user must be able to see the full picture of the stage before deciding.

### Step 6.4 — Ask confirmation (per stage, not per finding)

After presenting all findings with their proposals, ask a SINGLE confirmation for the entire stage:

Using `question` tool, ask (in the user's language):

```
Stage <stage> — <N> findings with proposed solutions.

Options:
  • Yes: Apply all <N> solutions now (RECOMMENDED)
  • I have questions about specific findings
  • No: Skip this stage
```

If **Yes**: proceed to Step 6.5 to apply all solutions for the stage at once.

If **I have questions**: the user may ask about specific findings. The orchestrator provides clarification using the stored suggestion and/or additional context. After resolving questions, ask again: "Apply all <N> solutions now? (y/n)". If yes → apply. If no → skip stage.

If **No**: skip stage. Findings remain as `[ ]` (unchecked) in resolve.md.

### Step 6.5 — Apply all solutions for the stage (if confirmed)

If user confirmed **Yes**, execute in **solve** mode to apply ALL solutions for the stage in one batch:

```bash
AUDIT_WORKDIR="$WORKDIR" \
AUDIT_RESOLVE_MODE=resolve_stage \
AUDIT_RESOLVE_STAGE="<stage>" \
AUDIT_RESOLVE_ACTION=solve \
python3 /tmp/skillkit/audit_resolve_run.py
```

This calls the model again for each finding AND applies all changes to source files in a single pass.

If user had questions and resolved them → same command above.

If user chose No → skip stage. Findings remain as `[ ]` (unchecked) in resolve.md.

### Step 6.6 — Stage summary report

After execution, present (in the user's language):

```
╔══════════════════════════════════════════════════╗
║  Summary for <stage>                             ║
╠══════════════════════════════════════════════════╣
║  Findings resolved:   <X>/<N>                    ║
║  Changes applied:     <Y>                        ║
║  Errors:              <E>                        ║
╚══════════════════════════════════════════════════╝
```

### Step 6.7 — Proceed to next stage

Continue to next stage in order: spec → plan → tasks → code.

After the last stage, proceed to Step 7 (Finalize).

## Step 6a — Auto-resolve all stages

If the user chose Option A (auto-resolve):

Resolution proceeds in fixed order: **spec → plan → tasks → code** (from spec forward, never from code).

```bash
AUDIT_WORKDIR="$WORKDIR" \
AUDIT_RESOLVE_MODE=resolve \
AUDIT_RESOLVE_ACTION=solve \
python3 /tmp/skillkit/audit_resolve_run.py
```

No intermediate confirmation per stage. After completion, proceed directly to Step 7.

## Step 7 — Finalize (with timestamp verification)

```bash
AUDIT_WORKDIR="$WORKDIR" \
AUDIT_RESOLVE_MODE=finalize \
python3 /tmp/skillkit/audit_resolve_run.py
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

Check `SKILLKIT_PROVIDER` to determine if each phase ran local (Ollama → 🆓) or remote (💰). Build the table dynamically:

```
| Source                   | Calls | Input (tok) | Output (tok) | Total (tok) | Cost |
|---|---|---|---|---|---|---|
| **Remote**               |       |             |              |             |      |
| SKILL.md + orchestration | 1     | 2,000       | —            | 2,000       | 💰   |
{phase rows — place each phase under Remote or Local based on provider}
| **Total {group}**       |       |             |              | **N**      | {💰/🆓} |
|---|---|---|---|---|---|---|---|
{repeat for second group if phases and orchestration are in different groups}
```

For each phase: if `SKILLKIT_PROVIDER=ollama` label as `**Local**` with 🆓, otherwise label as `**Remote**` with 💰. Use actual token counts from run.py output.

---
## Checkpoint & resume

- **Progress**: `/tmp/skillkit/audit_resolve_progress.json` tracks `stage_name`, `finding_index`, `completed_stages`, `completed_findings`
- **Resume**: On restart, completed findings are skipped from progress file

## Notes

- **Models**: spec/plan/tasks → `audit.resolve_spec`; code → `audit.resolve_codigo`, both via TOKEN_BUDGET
- **Language**: All generated content must be in the user's language without accents or special characters
- **Generated file**: `audit/{id}-audit-resolve.md` (same ID as the audit it resolves)
- **No model in diagnose/finalize**: file operations and regex only
- **Timestamp verified**: finalize guarantees `**Solucion**: <ts>` with ts > mtime of all referenced files
- **If diff doesn't apply**: orchestrator applies change manually with `edit` tool
