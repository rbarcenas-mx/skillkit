---
name: speckit.prespec
description: Analyzes a raw development idea to find ambiguities, contradictions, missing scope, and define MVP questions. Two-phase: initial analysis → user decisions → refined doc. 100% local execution via run.py delegating to model resolved through resolve_model().
---

# speckit.prespec — Raw Idea Analysis

> **Language note**: All user-facing text below is in English. The orchestrator MUST present all interactions to the user in their language, translating as needed. Generated content (idea.md, prompts) must also be in the user's language.

## Purpose

Analyze a raw development idea in two phases. Phase 1: run.py sends the idea to the locally-resolved model, generates `idea.md` (sections 1–6) with ambiguities, contradictions, missing pieces, and MVP-critical questions. The orchestrator presents those questions and captures user decisions. Phase 2: run.py refines the document incorporating those decisions, adding user flow and data model (sections 1–8).

## Architecture

```
Orchestrator (this agent)
  ├─ 1. Resolve WORKDIR
  ├─ 2. Resolve model + show TOKEN_BUDGET
  ├─ 3. Detect idea source (file or text)
  ├─ 4. PHASE 1 — Copy run.py → execute initial analysis
  │     ├─ run.py sends idea to model → writes idea.md
  │     └─ Returns JSON with questions, counts
  ├─ 5. Present questions to user → capture decisions
  ├─ 6. PHASE 2 — Execute refinement with user decisions
  │     └─ run.py refines idea.md (sections 1–8)
  └─ 7. Execution report + token report
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
model_id = resolve_model('prespec')
print('TOKEN_BUDGET:', os.environ.get('TOKEN_BUDGET', os.environ.get('SKILLKIT_MODE', 'unknown')))
print('Model:', model_id)
print('Provider:', os.environ.get('SKILLKIT_PROVIDER', '?'))
"
```

Display to user:

```
╔══════════════════════════════════════════════════╗
║           SPECKIT.PRESPEC                        ║
╠══════════════════════════════════════════════════╣
║  TOKEN_BUDGET:    <mode>                          ║
║  Model:          <model>                         ║
║  Provider:       <provider>                      ║
║  Description:    Raw idea analysis (2 phases)    ║
╚══════════════════════════════════════════════════╝
```

## Step 3 — Show execution plan

Present the plan to the user:

```
Execution Plan:
  Phase 1 — Initial analysis (run.py → local model)
    • Resolve model via resolve_model("prespec")
    • Load idea from source
    • Send to model → generate idea.md (sections 1–6)
    • Extract questions, ambiguities, missing pieces
  Phase 2 — Refinement with decisions
    • Present MVP-critical questions to user
    • Capture user decisions via question tool
    • Resend to model → refined idea.md (sections 1–8)
```

## Step 4 — Detect idea source

Check sources in this order:
1. `$ARGUMENTS` — explicit file path from command
2. `./idea.txt` — in the current WORKDIR
3. User-provided text in the message

If none found, ask the user to provide the idea.

## Step 5 — Phase 1: Initial analysis

### 5.1 — Copy run.py

```bash
cp "$SKILLKIT_HOME/skills/speckit.prespec/run.py" /tmp/skillkit/prespec_run.py
```

Say: `▶ Copying runner... done`

### 5.2 — Execute (file source)

Say (in the user's language): `▶ Phase 1 — Initial analysis (sending to model, wait up to 11 min)...`

Then execute:

```bash
WORKDIR="$WORKDIR" \
IDEA_FILE="<path to idea file>" \
python3 /tmp/skillkit/prespec_run.py
```

Or with direct text:

```bash
WORKDIR="$WORKDIR" \
IDEA_TEXT="<idea text>" \
python3 /tmp/skillkit/prespec_run.py
```

Use `timeout=660000` (11 min).

After execution completes, say: `✓ Phase 1 complete — processing response...`

`run.py`:
1. Loads the idea from `IDEA_FILE`, `IDEA_TEXT`, or local `idea.txt`
2. Sends it to the model (resolved via `resolve_model("prespec")`) with the analysis system prompt
3. Shows a spinner with elapsed time on stderr while waiting for the model
4. Writes `idea.md` to WORKDIR
5. Saves checkpoint to `/tmp/skillkit/prespec_progress.json`
6. Returns JSON to stdout: `status`, `output_file`, `ambiguities`, `missing_pieces`, `questions_count`, `questions[]`

### 5.3 — Parse and present results

Read the JSON output. Display:

```
Phase 1 complete — idea.md saved
  Ambiguities:    N
  Missing pieces: N
  Questions:      N
```

## Step 6 — Present questions and capture decisions

Show each hyper-critical question from the JSON output with full context.

Use the `question` tool to capture the user's decisions on each question. If the user answers in plain text, parse their decisions.

## Step 7 — Phase 2: Refinement with user decisions

If the user provided decisions, re-run in refinement mode:

Say (in the user's language): `▶ Phase 2 — Refinement (incorporating decisions, wait up to 11 min)...`

First write the existing idea.md to a temp file to avoid env var size limits:

Write the content to `/tmp/skillkit/prespec_existing_doc.md`, then:

```bash
WORKDIR="$WORKDIR" \
PRESPEC_REFINE="true" \
EXISTING_DOC_FILE="/tmp/skillkit/prespec_existing_doc.md" \
USER_DECISIONS="<user decisions>" \
python3 /tmp/skillkit/prespec_run.py
```

Use `timeout=660000` (11 min).

After completion, say: `✓ Phase 2 complete — idea.md updated with user decisions.`

`run.py` incorporates the decisions and generates the full document (sections 1–8: User Flow and Data Model included). Overwrites `idea.md`.

If the user did not provide decisions, skip this step.

Checkpoint: if the process is interrupted, re-running phase 1 regenerates `idea.md` from scratch. Phase 2 restart simply re-runs the refine command with the existing doc and decisions — safe to redo.

## Step 8 — Execution report

```
╔══════════════════════════════════════════════════╗
║           EXECUTION COMPLETED                    ║
╠══════════════════════════════════════════════════╣
║  Output:        idea.md                          ║
║  Phases run:    1 / 2                            ║
║  Questions:     N answered                       ║
║  Sections:      1–8 (fully refined)              ║
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

For each phase: if `SKILLKIT_PROVIDER=ollama` label as `**Local**` with 🆓, otherwise label as `**Remote**` with 💰. Use actual token counts from run.py output. If only phase 1 ran (no user decisions), omit phase 2 row.

---

## Checkpoint & resume

- **Progress file**: `/tmp/skillkit/prespec_progress.json` tracks `{"phase": 1|2, "status": "starting|running|done|failed", "timestamp": "ISO8601"}`.
- **Phase 1**: single-shot — if interrupted, re-run; `idea.md` is overwritten. The progress file indicates whether phase 1 completed.
- **Phase 2**: single-shot — if interrupted, re-run with same `EXISTING_DOC_FILE` and `USER_DECISIONS`; safe to redo. Check the progress file to know if phase 2 already ran.
- **Resume**: before executing phase 1, check if `/tmp/skillkit/prespec_progress.json` shows `"phase": 1, "status": "done"` — skip to phase 2 (questions display). Before phase 2, check for `"phase": 2, "status": "done"` — skip to end.

## Notes

- **Model**: resolved via `resolve_model("prespec")` according to TOKEN_BUDGET
- **Timeout**: `660000` (11 min) per run.py call
- **Output**: `idea.md` in WORKDIR, overwritten on each run
- **Language**: All generated content (`idea.md`, prompts) must be in the user's language without accents or special characters
