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

## Step 5 — Present findings and choose strategy

Read `resolve_path` file and present findings to user.

Inform the user (present in the user's language):

```
Found N findings across M stages.

By default, resolution proceeds stage by stage (spec → plan → tasks → code)
requiring your review and confirmation before applying each one.
You can also resolve everything automatically without intermediate review.
```

Ask with `question` tool (present options in the user's language):

Options:
- A: Resolve all automatically (no stage-by-stage review)
- B: Resolve stage by stage with confirmation (default, recommended)
- C: Other action

If B (or default): proceed to Step 6 (stage-by-stage resolution).
If A: proceed to "Auto-resolve all stages" below.
If C: handle as needed.

## Step 6 — Resolve by stages (default)

Loop through stages in fixed order: **spec → plan → tasks → code** (back to front, from specification to code).

For each stage that has findings:

### Stage banner

Resolve the model for this stage type:

```bash
# For spec, plan, tasks:
python3 -c "
import sys, os
sys.path.insert(0, os.environ['SKILLKIT_HOME'])
from lib import resolve_model
model_id = resolve_model('audit.resolve_spec')
print('Mode:', os.environ.get('TOKEN_BUDGET', os.environ.get('OPENCODE_MODO', 'unknown')))
print('Model:', os.environ.get('OPENCODE_MODEL', '?'))
print('Provider:', os.environ.get('OPENCODE_PROVEEDOR', '?'))
print('Description:', os.environ.get('OPENCODE_MODEL_DESC', '?'))
"

# For code:
python3 -c "
import sys, os
sys.path.insert(0, os.environ['SKILLKIT_HOME'])
from lib import resolve_model
model_id = resolve_model('audit.resolve_codigo')
print('Mode:', os.environ.get('TOKEN_BUDGET', os.environ.get('OPENCODE_MODO', 'unknown')))
print('Model:', os.environ.get('OPENCODE_MODEL', '?'))
print('Provider:', os.environ.get('OPENCODE_PROVEEDOR', '?'))
print('Description:', os.environ.get('OPENCODE_MODEL_DESC', '?'))
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
║  Provider:       <proveedor>                                ║
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

### Present findings and proposed solution

Show each finding for the current stage with its proposed solution (present in the user's language):

```
Findings in <stage>:
  • <finding 1> → Proposed solution: <solution 1>
  • <finding 2> → Proposed solution: <solution 2>
```

Ask (in the user's language): "Apply these solutions for <stage>? (y/n)" using `question` tool.

If yes → execute:

```bash
AUDIT_WORKDIR="$WORKDIR" \
AUDIT_RESOLVE_MODE=resolve_stage \
AUDIT_RESOLVE_STAGE="<stage>" \
AUDIT_RESOLVE_ACTION=solve \
python3 /tmp/opencode/audit_resolve_run.py
```

If no → skip stage (findings remain unresolved for this stage).

### Stage summary

After execution, show (present in the user's language):

```
Summary for <stage>:
  Findings resolved:   X/Y
  Changes applied:     N
  Errors:              E
```

Continue to next stage. After the last stage, proceed to Step 7 (Finalize).

## Step 6a — Auto-resolve all stages

If the user chose Option A (auto-resolve):

```bash
AUDIT_WORKDIR="$WORKDIR" \
AUDIT_RESOLVE_MODE=resolve \
AUDIT_RESOLVE_ACTION=solve \
python3 /tmp/opencode/audit_resolve_run.py
```

After completion, proceed directly to Step 7.

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

Check `OPENCODE_PROVEEDOR` to determine if each phase ran local (Ollama → 🆓) or remote (💰). Build the table dynamically:

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

For each phase: if `OPENCODE_PROVEEDOR=ollama` label as `**Local**` with 🆓, otherwise label as `**Remote**` with 💰. Use actual token counts from run.py output.

---
## Checkpoint & resume

- **Progress**: `/tmp/opencode/audit_resolve_progress.json` tracks `stage_name`, `finding_index`, `completed_stages`, `completed_findings`
- **Resume**: On restart, completed findings are skipped from progress file

## Notes

- **Models**: spec/plan/tasks → `audit.resolve_spec`; code → `audit.resolve_codigo`, both via TOKEN_BUDGET
- **Language**: All generated content must be in the user's language without accents or special characters
- **Generated file**: `audit/{id}-audit-resolve.md` (same ID as the audit it resolves)
- **No model in diagnose/finalize**: file operations and regex only
- **Timestamp verified**: finalize guarantees `**Solucion**: <ts>` with ts > mtime of all referenced files
- **If diff doesn't apply**: orchestrator applies change manually with `edit` tool
