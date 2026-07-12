---
name: qa.prepare
description: Analyze the current project state and generate QA validation plans for multiple types (infrastructure, unit, flow, stress, scale). Model resolved via TOKEN_BUDGET through resolve_model().
---

# qa.prepare — QA Plan Generation by Type

> **Language note**: All user-facing text below is in English. The orchestrator MUST present all interactions to the user in their language, translating as needed. Generated content (plans, reports) must also be in the user's language.

## Purpose

Analyze the current project state and generate QA validation plans per type. The model is resolved via `resolve_model("qa.prepare")` according to `TOKEN_BUDGET`. Supports 5 plan types and generates `suite_plan.md` when multiple are selected.

## Architecture

```
~/.claude/skills/qa.prepare/
├── SKILL.md
├── run.py                    # Plan generator
│                              #   - Reads QA_PLAN_TYPES from environment
│                              #   - Per type: loads template, calls model, validates, caches
│                              #   - If validation fails, regenerates with corrections
│                              #   - If multiple types, generates suite_plan.md
└── templates/
    ├── infra_prompt.md       # Infrastructure prompt
    ├── unit_prompt.md        # Unit test prompt
    ├── flow_prompt.md        # HTTP flow prompt
    ├── stress_prompt.md      # Stress test prompt
    └── scale_prompt.md       # Scale test prompt
```

## Plan Types

| Type | Purpose | Driver | Step format |
|---|---|---|---|
| `infra` | Docker, DB, Redis, migrations, healthchecks | shell | type: shell |
| `unit` | Unit tests, lint, typecheck | shell | type: shell |
| `flow` | Full HTTP flow (register→login→order→offer) | http | type: http + extract |
| `stress` | Load test with autocannon/hey/wrk | stress | type: stress |
| `scale` | Scaling with N workers + load | shell + stress | type: shell / type: stress |

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
model_id = resolve_model('qa.prepare')
print('TOKEN_BUDGET:', os.environ.get('TOKEN_BUDGET', os.environ.get('OPENCODE_MODO', 'unknown')))
print('Model:', model_id)
print('Provider:', os.environ.get('OPENCODE_PROVEEDOR', '?'))
"
```

Display to user:

```
╔══════════════════════════════════════════════════╗
║           QA.PREPARE                             ║
╠══════════════════════════════════════════════════╣
║  TOKEN_BUDGET:    <mode>                          ║
║  Model:          <model>                         ║
║  Provider:       <provider>                      ║
║  Workdir:        <workdir>                       ║
║  Description:    Generate QA validation plans    ║
║                  by type                         ║
╚══════════════════════════════════════════════════╝
```

## Step 3 — Execution plan

Present the phases:

```
Execution Plan
═══════════════

Phase 1 - Configure:
  - Select plan types (infra, unit, flow, stress, scale)
  - Configure flow params (users, orders, verification mode)
  - Configure stress level / scale workers

Phase 2 - Generate:
  - Per type: copy run.py + templates
  - For infra/unit/flow: deterministic template assembly (no AI)
  - For stress/scale: model generates plan from template + context
  - Validate each plan (YAML structure, required sections)
  - Auto-regenerate on validation failure

Phase 3 - Review:
  - Present generated plans with step counts
  - Generate suite_plan.md if multiple types

Proceed? (y/n)
```

## Step 4 — Ask user which plans to generate

**REQUIRED**: Before executing the script, ask the user using the `question` tool:

1. **Plan types to generate** (multi-select):
   - `infra` — Infrastructure (Docker + DB + Redis + migrations)
   - `unit` — Unit tests and code quality (lint, typecheck)
   - `flow` — Operational flow via HTTP
   - `stress` — Stress test
   - `scale` — Scaling test

2. **If `flow` selected**: ask configuration:
   - `Number of users` (pairs, e.g. 2, 4, 10) — creates N/2 requesters and N/2 runners
   - `Orders per requester` (1, 3, 5)
   - `Identity verification mode`:
     - `automatica` — Cloudinary mock credentials auto-approve (recommended)
     - `manual` — VERIFICACION_MANUAL=true, requires admin approval
   - `Admin in DB`:
     - `no` — register admin from plan
     - `si` — admin already exists (seed), generate JWT token directly
   - `Include complaints`: si | no
   - `Include admin endpoints`: si | no

3. **If `stress` selected**: ask level:
   - `ligero` (100 req, 10 concurrent)
   - `medio` (500 req, 50 concurrent)
   - `pesado` (2000 req, 100 concurrent)

4. **If `scale` selected**: ask workers (2, 4, 8)

Build variables:
```
QA_PLAN_TYPES=<types>
QA_FLOW_USERS=<N>
QA_FLOW_MANDADOS=<N>
QA_FLOW_VERIFICACION=<automatica|manual>
QA_FLOW_ADMIN_EXISTS=<si|no>
QA_FLOW_DENUNCIAS=<si|no>
QA_FLOW_ADMIN_ENDPOINTS=<si|no>
QA_STRESS_LEVEL=<level>
QA_SCALE_WORKERS=<workers>
```

## Step 5 — Collect project context

```bash
# Stack and scripts
cat package.json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps({'scripts':d.get('scripts',{}),'dependencies':list(d.get('dependencies',{}).keys()),'devDependencies':list(d.get('devDependencies',{}).keys())}, indent=2))"

# Test configuration
cat jest.config.js 2>/dev/null || cat vitest.config.ts 2>/dev/null || echo "NO_TEST_CONFIG"

# TypeScript
cat tsconfig.json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print('outDir:', d.get('compilerOptions',{}).get('outDir',''))" 2>/dev/null || echo "NO_TSCONFIG"

# Expected env vars
cat .env.example 2>/dev/null || cat .env.template 2>/dev/null || echo "NO_ENV_EXAMPLE"

# Database (Prisma)
cat prisma/schema.prisma 2>/dev/null | head -30 || echo "NO_PRISMA"

# Existing Docker
cat docker-compose.yml 2>/dev/null || echo "NO_DOCKER_COMPOSE"

# Test files
find tests/ -name '*.test.*' -o -name '*.spec.*' 2>/dev/null | sort || echo "NO_TESTS_DIR"

# .gitignore
cat .gitignore 2>/dev/null || echo "NO_GITIGNORE"
```

Save output as `/tmp/opencode/qa_prepare_payload.json`.

## Step 6 — Execute run.py

```bash
cp -r ~/.claude/skills/qa.prepare /tmp/opencode/qa_prepare && \
QA_PROJECT_CONTEXT="$(cat /tmp/opencode/qa_prepare_payload.json)" \
WORKDIR="<WORKDIR>" \
QA_EXISTING_PLANS="$(ls qa/*_plan.md 2>/dev/null || echo '')" \
QA_PLAN_TYPES="<selected types>" \
QA_STRESS_LEVEL="<level>" \
QA_SCALE_WORKERS="<workers>" \
QA_FLOW_USERS="<N>" \
QA_FLOW_MANDADOS="<N>" \
QA_FLOW_VERIFICACION="<automatica|manual>" \
QA_FLOW_ADMIN_EXISTS="<si|no>" \
QA_FLOW_DENUNCIAS="<si|no>" \
QA_FLOW_ADMIN_ENDPOINTS="<si|no>" \
python3 /tmp/opencode/qa_prepare/run.py
```

`timeout=660000` (11 min per plan generated — each plan takes ~2min).

**IMPORTANT**: The script first checks for pending plans (without `_completed`). If found:
- Prints `PENDING_FILES_DETECTED` and exits with code 2
- The orchestrator must ask the user:
  1. Delete them (remove `qa/*_plan.md` without `_completed`) and re-execute
  2. Resume them with `qa.execute` directly (do not re-execute `qa.prepare`)

The script:
- Iterates each selected plan type
- Loads the corresponding template from `templates/`
- Resolves model with `resolve_model("qa.prepare")` and calls model with project context
- Validates each plan (YAML, required sections, --- STEP format)
- Cache by type (no cross-type cache reuse)
- Saves each plan as `qa/{id}_{timestamp}_{type}_plan.md`
- If multiple types, generates `qa/{id}_{timestamp}_suite_plan.md`

## Step 7 — Verify results

Read each generated plan. Verify:
- Starts with correct header per type
- Contains README and Scenario Checklist
- Has steps in `--- STEP` YAML format
- Each step has `type`, `id`, `desc`
- Execution Log is empty

If any plan is missing or has errors, inform the user and offer to regenerate that specific type.

## Step 8 — Present to user

Show a summary per plan:

```
✅ QA plans generated:
  - infra: qa/002_20260622_1800_infra_plan.md (6 steps)
  - unit:  qa/002_20260622_1802_unit_plan.md (5 steps)
  - flow:  qa/002_20260622_1804_flow_plan.md (7 steps)
  - suite: qa/002_20260622_1804_suite_plan.md (3 plans)

Stack detected: Node.js + TypeScript, Jest, Prisma, PostgreSQL+PostGIS
Infrastructure: Docker (postgis/postgis:16-3.4, redis:alpine)
External services: Twilio (mock), Cloudinary (mock)
```

Ask if the user wants to review any plan, modify it, or proceed to execute with `qa.execute`.

## Step 9 — Execution report

```
╔══════════════════════════════════════════════════╗
║           EXECUTION COMPLETED                    ║
╠══════════════════════════════════════════════════╣
║  Plans generated: N                              ║
║  Types:          infra, unit, flow, ...          ║
║  Suite:          yes / no                        ║
║  Output dir:     qa/                             ║
║  Next:           /qa.execute to run the plans    ║
╚══════════════════════════════════════════════════╝
```

## Step 10 — Token report

Check `OPENCODE_PROVEEDOR` to determine if each phase ran local (Ollama → 🆓) or remote (💰). Build the table dynamically:

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

For each phase: if `OPENCODE_PROVEEDOR=ollama` label as `**Local**` with 🆓, otherwise label as `**Remote**` with 💰. Use actual token counts from run.py output.

---

## Checkpoint & resume

- **Progress file**: `/tmp/opencode/qa_prepare_progress.json` tracks per-type status `{"infra": "done", "flow": "running", ...}`.
- **Cache per type**: `/tmp/opencode/qa_prepare_{type}_cached.md` — saves generated plan text to avoid re-generation.
- **Resume**: On restart, progress file is checked. Types marked "done" load from cache. Types marked "running" are re-generated.

## Notes

- **Language**: All generated content must be in the user's language without accents or special characters
- **Model**: resolved via `resolve_model("qa.prepare")` according to TOKEN_BUDGET
- **Timeout**: `660000` (11 min) per execution
- **Cache per type**: `/tmp/opencode/qa_prepare_progress.json` with per-type keys
- **Validation**: YAML parser + structural checks. On failure, auto-regenerate with correction prompt
- **Step format**: `--- STEP` YAML, compatible with `qa.execute`
- **Suite**: auto-generated if 2+ plan types selected
- **The script builds the prompt and calls the model** — data via environment variables
