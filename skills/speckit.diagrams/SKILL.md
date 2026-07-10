---
name: speckit.diagrams
description: Generate Mermaid.js architecture diagrams from spec-kit artifacts. 100% local via Ollama. The remote orchestrator handles the full flow: detects project type, prepares manifest, shows diagram plan to user, then generates ONE diagram at a time with progress bar and checkpoints.
---

# speckit.diagrams — Architecture Diagram Generation

## Purpose

Generate Mermaid.js architecture diagrams from spec-kit artifacts in `specs/<feature>/`. Progressive orchestration: the remote orchestrator splits the work into phases, delegating each model call to `run.py` (100% local via Ollama).

## Architecture

```
Orchestrator (this agent)
  ├─ 1. Resolve feature directory & read artifacts
  ├─ 2. Resolve model + show TOKEN_BUDGET
  ├─ 3. Show execution plan
  ├─ 4. Copy run.py → write context file
  ├─ 5. PHASE 1 — Prepare: detect project type, build manifest
  │     └─ run.py sends artifacts to model → returns diagram manifest
  ├─ 6. Present manifest to user, confirm selection
  ├─ 7. PHASE 2 — Generate: one diagram at a time
  │     ├─ run.py generates diagram → returns content
  │     ├─ Orchestrator writes file to specs/<feature>/diagrams/
  │     └─ Progress bar updated per diagram, checkpoint saved
  ├─ 8. Final consolidation (summary + file list)
  ├─ 9. Execution report
  └─ 10. Token report
```

---

## Step 1 — Resolve feature directory and read artifacts

Ask the user for the feature name if `$ARGUMENTS` is empty.

Base path: `specs/<feature>/` (from repo root).

Verify `specs/<feature>/plan.md` exists. If not, abort with an error.

Read artifacts with the **Read** tool:
- `specs/<feature>/plan.md` (required)
- `specs/<feature>/spec.md` (optional)
- `specs/<feature>/data-model.md` (optional)
- `specs/<feature>/contracts/api.md` (optional)

## Step 2 — Resolve model and show TOKEN_BUDGET

```bash
python3 -c "
import sys, os, json
sys.path.insert(0, os.environ['SKILLKIT_HOME'])
from lib import resolve_model
model_id = resolve_model('diagrams')
print('TOKEN_BUDGET:', os.environ.get('TOKEN_BUDGET', os.environ.get('OPENCODE_MODO', 'unknown')))
print('Model:', model_id)
print('Provider:', os.environ.get('OPENCODE_PROVEEDOR', '?'))
"
```

Display to user:

```
╔══════════════════════════════════════════════════╗
║           SPECKIT.DIAGRAMS                       ║
╠══════════════════════════════════════════════════╣
║  TOKEN_BUDGET:    <mode>                          ║
║  Model:          <model>                         ║
║  Provider:       <provider>                      ║
║  Feature:        <feature-name>                  ║
║  Description:    Generate Mermaid diagrams from  ║
║                  spec-kit artifacts              ║
╚══════════════════════════════════════════════════╝
```

## Step 3 — Execution plan

Present the phases to the user:

```
Execution Plan
═══════════════

Phase 1 - Prepare:
  - Detect project type from plan.md
  - Build diagram manifest (categories + instances)
  - 1 model call

Phase 2 - Generate:
  - Generate each diagram one at a time
  - Write to specs/<feature>/diagrams/
  - N model calls (one per diagram)

Proceed? (y/n)
```

## Step 4 — Copy run.py and write context file

```bash
cp "$HOME/.claude/skills/speckit.diagrams/run.py" /tmp/opencode/diagrams_run.py
```

Write the artifacts to `/tmp/opencode/diagrams_context.json`:

```json
{
  "feature": "<feature-name>",
  "artifacts": {
    "spec.md": "<full content>",
    "plan.md": "<full content>",
    "data-model.md": "<full content>",
    "contracts/api.md": "<full content>"
  }
}
```

Include only artifacts that exist. Skip empty/missing ones.

## Step 5 — Phase 1: Prepare (detect project type, build manifest)

```bash
DIAGRAMS_MODE="prepare" \
DIAGRAMS_CONTEXT_FILE="/tmp/opencode/diagrams_context.json" \
python3 /tmp/opencode/diagrams_run.py
```

`timeout=120000` (2 minutes). run.py shows a spinner on stderr during the model call.

Output is JSON on stdout with `project_type`, `summary`, and `diagrams[]`. The manifest is also saved to `/tmp/opencode/diagrams_manifest.json`.

## Step 6 — Present manifest and confirm

Show the detected project type and diagram list:

```
Project type: Mobile App
Summary: Mandadero app in Queretaro

Diagrams to generate (N total):

  screen-flow (1):
    - screen-flow.md

  sequence (5):
    - sequence-auth.md
    - sequence-mandado.md
    ...

  data-flow (3):
    - core-data-flow.md
    ...

  er-diagram (1):
    - er-diagram.md
```

Ask the user to confirm or select specific diagrams. Capture the selection as a filtered list of diagrams to generate.

## Step 7 — Phase 2: Generate diagrams one by one

Create output directory:

```bash
mkdir -p specs/<feature>/diagrams
```

For each diagram in the selected manifest:

### 7.1 — Run generate

```bash
DIAGRAMS_MODE="generate" \
DIAGRAMS_CATEGORY="<category>" \
DIAGRAMS_INSTANCE="<instance>" \
DIAGRAMS_MANIFEST_FILE="/tmp/opencode/diagrams_manifest.json" \
DIAGRAMS_CONTEXT_FILE="/tmp/opencode/diagrams_context.json" \
python3 /tmp/opencode/diagrams_run.py
```

`timeout=300000` (5 minutes per diagram).

### 7.2 — Write diagram file

Parse the JSON output, extract `content`, and write with **Write**:

```
specs/<feature>/diagrams/<filename>
```

### 7.3 — Update progress bar

After each diagram, show a progress bar (via run.py stderr relay + orchestrator display):

```
[██████░░░░░░░░░░░░░░]  35%  (4/11)

  screen-flow       [█] 1/1  ✅
  component-arch    [█] 1/1  ✅
  sequence          [███░░░░] 3/5  ▶️  In progress
  data-flow         [░░░] 0/3  🕐  Pending
  er-diagram        [░░] 0/1  🕐  Pending

Just completed: sequence-auth.md ✅
```

### 7.4 — Checkpoint

Each `run.py generate` call saves a checkpoint to `/tmp/opencode/diagrams_checkpoints/{category}_{instance}.json`. The orchestrator checks before calling run.py:

- If checkpoint exists for `{category}_{instance}` and the user wants to skip → read from cache, show `⚡ Cache hit`
- Progress is also tracked in `/tmp/opencode/diagrams_progress.json` with `phase`, `total`, `completed`, `current`, and timestamp

## Step 8 — Final consolidation

When ALL diagrams are generated, show:

### Progress bar (100%)

```
[████████████████████]  100%  (11/11)

  screen-flow       [█] 1/1  ✅
  component-arch    [█] 1/1  ✅
  sequence          [█████] 5/5  ✅
  data-flow         [███] 3/3  ✅
  er-diagram        [█] 1/1  ✅
```

### Summary table

```
| Category           | Files | Status |
|--------------------|-------|--------|
| screen-flow        | 1     | ✅     |
| sequence           | 5     | ✅     |
| data-flow          | 3     | ✅     |
| er-diagram         | 1     | ✅     |
| **Total**          | **10**| ✅     |
```

### File list

```
specs/<feature>/diagrams/screen-flow.md
specs/<feature>/diagrams/sequence-auth.md
...
```

## Step 9 — Execution report

```
╔══════════════════════════════════════════════════╗
║           EXECUTION COMPLETED                    ║
╠══════════════════════════════════════════════════╣
║  Project type:   <type>                          ║
║  Diagrams gen:   N / M                           ║
║  Failed:         F                               ║
║  Skipped:        S (cache hits)                  ║
║  Output dir:     specs/<feature>/diagrams/       ║
╚══════════════════════════════════════════════════╝
```

## Step 10 — Token report

```
| Source                   | Calls | Input (tok) | Output (tok) | Total (tok) | Cost |
|---|---|---|---|---|---|---|
| **Remote**               |       |             |              |             |      |
| SKILL.md + orchestration | 1     | X,XXX       | —            | X,XXX       | 💰   |
| **Total remote**         |       |             |              | **X,XXX**   |      |
|                          |       |             |              |             |      |
| **Local**                |       |             |              |             |      |
| Phase 1 — prepare        | 1     | X,XXX       | X,XXX        | X,XXX       | 🆓   |
| Phase 2 — diagram 1      | 1     | X,XXX       | X,XXX        | X,XXX       | 🆓   |
| ...                      | ...   | ...         | ...          | ...         | 🆓   |
| **Total local**          | **N** | **XX,XXX**  | **XX,XXX**   | **XX,XXX**  | 🆓   |
|---|---|---|---|---|---|---|
| Remote share             |       |             |              | X,XXX (~X%)  | 💰   |
| Local share              |       |             |              | XX,XXX (~X%) | 🆓   |
```

Adjust based on actual token counts from each run.py call (`_tokens` in JSON response).

---

## Checkpoint & resume

- **Progress file**: `/tmp/opencode/diagrams_progress.json` tracks `{"phase": "prepare|generate|done", "total": N, "completed": M, "current": "category_instance", "timestamp": "ISO8601"}`.
- **Diagram checkpoints**: `/tmp/opencode/diagrams_checkpoints/{category}_{instance}.json` — one per generated diagram.
- **Resume**: Before phase 1, check progress. If `"phase": "done"` → skip to consolidation. If `"phase": "generate"` → resume from last completed diagram.
- **Cache hit**: If checkpoint file exists and user confirms skip → read from cache instead of regenerating.

## Notes

- **Model**: resolved via `resolve_model("diagrams")` according to TOKEN_BUDGET. Override with `DIAGRAMS_MODEL` env var.
- **Timeouts**: Prepare = 120s, Generate = 300s per diagram.
- **Payload via file**: run.py sends payloads via `/tmp/opencode/diagrams_payload.json` (avoids ARG_MAX).
- **Output directory**: `specs/<feature>/diagrams/`. Created if missing.
- **Language**: All generated content (diagrams, prompts) in Spanish without accents or special characters.
- **No placeholders**: Diagrams must use real entities from the artifacts.
