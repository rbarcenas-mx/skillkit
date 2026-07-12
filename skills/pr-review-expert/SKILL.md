---
name: pr-review-expert
description: Use when the user asks to review pull requests, analyze code changes, check for security issues in PRs, or assess code quality of diffs. Delegates all analysis to model via resolve_model(). Supports batching for large diffs.
---

<!--
  Derived from a community PR review skill. Original author unknown.
  Modified: integrated TOKEN_BUDGET model resolution, added batch-by-batch
  orchestration, spinner, checkpoint system, and English pattern refactor.
  If you recognize this as your work, please open an issue for attribution.
  See CREDITS.md for details.
-->

# PR Review Expert — Pull Request Review

> **Language note**: All user-facing text below is in English. The orchestrator MUST present all interactions to the user in their language, translating as needed. Generated content (reviews, findings) must also be in the user's language.

## Purpose

Review GitHub/GitLab PRs in a structured way, delegating ALL analysis to the model resolved via `resolve_model("pr-review")` according to TOKEN_BUDGET. `run.py` receives the diff, splits it into batches if large, sends it to the model for blast radius, security, breaking changes, performance, testing, and code quality analysis, and consolidates findings.

## Architecture

```
Orchestrator (this agent)
  ├─ 1. Resolve WORKDIR
  ├─ 2. Resolve model + show TOKEN_BUDGET
  ├─ 3. Show execution plan
  ├─ 4. Obtain PR diff and metadata (gh/glab CLI)
  ├─ 5. Census: get batch list (PR_BATCH_ONLY=info) — 1 fast call
  ├─ 6. For EACH batch — ONE atomic call, NEVER grouped:
  │     ├─ PR_BATCH_ONLY=N → run.py → JSON review
  │     ├─ Present result immediately
  │     ├─ Save partial to /tmp/opencode/review_partial_N.json
  │     └─ Ask user to continue (required for multi-batch)
  ├─ 7. Consolidate: PR_CONSOLIDATE_DIR → run.py → merged review
  ├─ 8. Present consolidated review to user
  ├─ 9. Execution report
  └─ 10. Token report
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
model_id = resolve_model('pr-review')
print('TOKEN_BUDGET:', os.environ.get('TOKEN_BUDGET', os.environ.get('OPENCODE_MODO', 'unknown')))
print('Model:', model_id)
print('Provider:', os.environ.get('OPENCODE_PROVEEDOR', '?'))
"
```

Display to user:

```
╔══════════════════════════════════════════════════╗
║           PR-REVIEW-EXPERT                       ║
╠══════════════════════════════════════════════════╣
║  TOKEN_BUDGET:    <mode>                          ║
║  Model:          <model>                         ║
║  Provider:       <provider>                      ║
║  PR/MR:          #<number>                       ║
║  Description:    Review PR diff with local model ║
╚══════════════════════════════════════════════════╝
```

## Step 3 — Execution plan

Present the phases:

```
Execution Plan
═══════════════

Phase 1 - Fetch:
  - Obtain PR diff via gh/glab CLI
  - Fetch PR metadata (title, body, labels)
  - Optional: read repo context (constitution.md)

Phase 2 - Census:
  - Run PR_BATCH_ONLY=info → get batch count and list
  - Show user how many batches will be processed

Phase 3 - Analyze (ONE call per batch):
  - For each batch: PR_BATCH_ONLY=N → run.py → JSON
  - Present result AFTER each batch
  - User decides to continue or stop
  - NEVER group multiple batches in a single run.py call

Phase 4 - Consolidate:
  - PR_CONSOLIDATE_DIR → run.py hierarchically merges all partials
  - Returns the final structured review

Phase 5 - Report:
  - Present findings: must_fix, should_fix, suggestions, looks_good
  - Verdict: APPROVE / COMMENT / REQUEST_CHANGES

Proceed? (y/n)
```

## Step 4 — Obtain PR diff and metadata

The PR number is `$ARGUMENTS`. If empty, ask the user.

### GitHub (gh CLI)

```bash
PR=<number>
gh pr diff $PR > /tmp/pr-$PR.diff
gh pr view $PR --json title,body,labels,assignees,milestone > /tmp/pr-$PR-meta.json
```

### GitLab (glab CLI)

```bash
MR=<iid>
glab mr diff $MR > /tmp/mr-$MR.diff
glab mr view $MR --output json > /tmp/mr-$MR-meta.json
```

### Optional: repository context

If `.specify/memory/constitution.md` exists in the repo, read it to include as additional context.

## Step 5 — Census: detect batch count

Copy run.py once, then use it for all phases:

```bash
cp "$HOME/.claude/skills/pr-review-expert/run.py" /tmp/opencode/pr_review_run.py
```

Get the batch list without processing:

```bash
PR_DIFF_FILE="/tmp/pr-<NUMBER>.diff" \
PR_BATCH_ONLY="info" \
python3 /tmp/opencode/pr_review_run.py
```

Shows total batches and each batch label. Use `timeout=30000` (30s — no model call, just parsing).

## Step 6 — Execute ONE batch per call (CRITICAL)

CRITICAL: Each batch is an independent atomic call. **NEVER group multiple batches in a single bash command or loop.** Batches are always executed one at a time as separate bash calls, even when the user chooses to run all.

Before starting, ask the user:

- **A: Run all batches with confirmation** — Orchestrator pauses after each batch and asks "Continue?"
- **B: Run all batches automatically** — Orchestrator executes all batches sequentially without pausing, but each batch is STILL a separate atomic call

In both modes, every batch uses its own `bash` call with `PR_BATCH_ONLY=N`. The only difference is whether the orchestrator waits for user input between batches.

### 6.1 — For each batch index N (1..total):

```bash
PR_DIFF_FILE="/tmp/pr-<NUMBER>.diff" \
PR_BATCH_ONLY="<N>" \
python3 /tmp/opencode/pr_review_run.py
```

Use `timeout=300000` (5 min per batch — each batch has its own timeout).

### 6.2 — After each batch:

1. **Read the JSON output** immediately
2. **Save partial** — run.py saves to `/tmp/opencode/review_partial_N.json` automatically
3. **Present result** to user: batch label, verdict, any critical findings
4. **Show progress**: `Batch N/M completed`
5. If mode A: **Ask user** "Continue with next batch?"
   If mode B: **Continue** to next batch immediately

### 6.3 — Consolidate all partials

After all batches are complete, run hierarchical consolidation:

```bash
PR_DIFF_FILE="/tmp/pr-<NUMBER>.diff" \
PR_CONSOLIDATE_DIR="/tmp/opencode" \
python3 /tmp/opencode/pr_review_run.py
```

Use `timeout=300000` (5 min for consolidation with model calls).

> **GOLDEN RULE**: The orchestrator must NEVER call run.py with all batches at once (no `PR_BATCH_ONLY` + no `PR_CONSOLIDATE_DIR` = full mode that loops internally). Multi-batch diffs must ALWAYS use `PR_BATCH_ONLY=N` one at a time, then `PR_CONSOLIDATE_DIR`. Single-batch diffs (total=1) can use the direct mode (no env vars) since there is only one call.

### Environment variables

| Variable | Description |
|---|---|
| `PR_DIFF_FILE` | Path to .diff file |
| `PR_DIFF` | Diff content directly |
| `PR_METADATA` | JSON with PR title, body, labels |
| `PR_BATCH_ONLY` | `"info"` to list batches, `"<N>"` to run batch N only |
| `PR_CONSOLIDATE_DIR` | Path with `review_partial_*.json` files to consolidate |
| `PR_MODEL` | Model override (default: resolved via resolve_model("pr-review")) |

## Step 7 — Present review

The JSON output contains:

```json
{
  "blast_radius": {"level": "HIGH", "summary": "..."},
  "security": {"findings": [...]},
  "breaking_changes": {"found": false, "items": []},
  "performance": {"issues": [...]},
  "code_quality": {"issues": [...]},
  "tests": {"coverage_assessment": "...", "issues": [...]},
  "checklist_completed": {"scope": 5, "blast_radius": 5, ...},
  "verdict": "APPROVE | COMMENT | REQUEST_CHANGES",
  "summary": "...",
  "must_fix": [...],
  "should_fix": [...],
  "suggestions": [...],
  "looks_good": [...]
}
```

Present to user in readable format:

```
## PR Review: [title] (#NUMBER)

Blast Radius: HIGH — changes in lib/auth used by 5 services
Security: 1 finding (medium severity)
Tests: Delta coverage +2%
Breaking Changes: None detected
Verdict: REQUEST_CHANGES

--- MUST FIX (Blocking) ---
1. [C1] SQL Injection in src/db/users.ts:42
   ...

--- SHOULD FIX (Non-blocking) ---
2. [W1] Missing auth check in POST /api/admin/reset
   ...

--- SUGGESTIONS ---
3. [S1] N+1 in src/services/reports.ts:88
   ...

--- LOOKS GOOD ---
- Test coverage for new auth flow
```

## Step 8 — Execution report

```
╔══════════════════════════════════════════════════╗
║           EXECUTION COMPLETED                    ║
╠══════════════════════════════════════════════════╣
║  PR/MR:         #<number>                        ║
║  Batches:       N (single/multi)                 ║
║  Verdict:       APPROVE|COMMENT|REQUEST_CHANGES  ║
║  Must fix:      M                                ║
║  Should fix:    S                                ║
║  Suggestions:   G                                ║
╚══════════════════════════════════════════════════╝
```

## Step 9 — Token report

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

- **Progress file**: `/tmp/opencode/pr_review_progress.json` tracks `{"phase": "census|batches|consolidate|done", "total_batches": N, "completed_batches": N, "timestamp": "ISO8601"}`.
- **Batch partials**: `/tmp/opencode/review_partial_<N>.json` — saved by run.py after each atomic batch call.
- **Resume**: If interrupted, check `/tmp/opencode/review_partial_*.json` count. Already-completed batches are skipped by starting `PR_BATCH_ONLY` from the next uncompleted index. On restart, re-run census first, then resume from the first missing partial.

## Notes

- **Model**: resolved via `resolve_model("pr-review")` according to TOKEN_BUDGET. Override with `PR_MODEL`.
- **Batching**: Diff split by files (~4000 chars per batch). Multi-batch uses `PR_BATCH_ONLY=N` one batch per call.
- **Per-batch timeout**: `300000` (5 min) per batch. Each call has its own independent timeout — never use a single high timeout for all batches.
- **Consolidation timeout**: `300000` (5 min) for `PR_CONSOLIDATE_DIR` mode.
- **GOLDEN RULE — NEVER group batches**: The orchestrator must process each batch via `PR_BATCH_ONLY=N` in separate bash calls. A single `run.py` call without `PR_BATCH_ONLY` (full mode) is ONLY acceptable when the diff produces exactly 1 batch. For multi-batch diffs, the full mode is forbidden because a timeout would lose all partial progress.
- **Resume**: If interrupted, check `/tmp/opencode/review_partial_*.json` to skip already-completed batches via `PR_BATCH_ONLY`.
- **No here-documents**: Always Write + Bash separately.
- **Payload via file**: run.py writes payload to `/tmp/opencode/pr_review_payload.json`.
- **Credentials**: If using Jira/Linear, pass credentials via stdin (`curl -K -`), never in argv.
- **Language**: All generated content (PR reports, model prompts, findings) must be in the user's language without accents or special characters.
