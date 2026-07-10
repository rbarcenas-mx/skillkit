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

## Purpose

Review GitHub/GitLab PRs in a structured way, delegating ALL analysis to the model resolved via `resolve_model("pr-review")` according to TOKEN_BUDGET. `run.py` receives the diff, splits it into batches if large, sends it to the model for blast radius, security, breaking changes, performance, testing, and code quality analysis, and consolidates findings.

## Architecture

```
Orchestrator (this agent)
  ├─ 1. Resolve WORKDIR
  ├─ 2. Resolve model + show TOKEN_BUDGET
  ├─ 3. Show execution plan
  ├─ 4. Obtain PR diff and metadata (gh/glab CLI)
  ├─ 5. Copy run.py → execute analysis
  │     ├─ run.py splits diff into batches if needed
  │     ├─ Each batch sent to model for review
  │     ├─ Multi-batch: hierarchical consolidation
  │     └─ Returns JSON with structured review
  ├─ 6. Present review to user
  ├─ 7. Execution report
  └─ 8. Token report
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

Phase 2 - Analyze:
  - Split diff into batches (if >4000 chars)
  - Send each batch to model for structured review
  - Multi-batch: hierarchical consolidation

Phase 3 - Report:
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

## Step 5 — Execute run.py (100% local analysis)

Copy and execute:

```bash
cp "$HOME/.claude/skills/pr-review-expert/run.py" /tmp/opencode/pr_review_run.py
```

```bash
PR_DIFF_FILE="/tmp/pr-<NUMBER>.diff" \
PR_METADATA="$(cat /tmp/pr-<NUMBER>-meta.json)" \
python3 /tmp/opencode/pr_review_run.py
```

`timeout=900000` (15 min). run.py:

1. Reads diff from `PR_DIFF_FILE` (or `PR_DIFF` env var)
2. If diff is large (>4000 chars), splits into batches by file
3. Sends each batch to the model (resolved via `resolve_model("pr-review")`) with review system prompt
4. For multi-batch: hierarchical consolidation
5. Returns JSON with structured review

### Environment variables

| Variable | Description |
|---|---|
| `PR_DIFF_FILE` | Path to .diff file |
| `PR_DIFF` | Diff content directly |
| `PR_METADATA` | JSON with PR title, body, labels |
| `PR_MODEL` | Model override (default: resolved via resolve_model("pr-review")) |

## Step 6 — Present review

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

## Step 7 — Execution report

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

## Step 8 — Token report

```
| Source                   | Calls | Input (tok) | Output (tok) | Total (tok) | Cost |
|---|---|---|---|---|---|---|
| **Remote**               |       |             |              |             |      |
| SKILL.md + orchestration | 1     | X,XXX       | —            | X,XXX       | 💰   |
| **Total remote**         |       |             |              | **X,XXX**   |      |
|                          |       |             |              |             |      |
| **Local**                |       |             |              |             |      |
| Batch 1                  | 1     | X,XXX       | X,XXX        | X,XXX       | 🆓   |
| Batch 2                  | 1     | X,XXX       | X,XXX        | X,XXX       | 🆓   |
| Consolidation            | 1     | X,XXX       | X,XXX        | X,XXX       | 🆓   |
| **Total local**          | **N** | **XX,XXX**  | **XX,XXX**   | **XX,XXX**  | 🆓   |
|---|---|---|---|---|---|---|
| Remote share             |       |             |              | X,XXX (~X%)  | 💰   |
| Local share              |       |             |              | XX,XXX (~X%) | 🆓   |
```

Adjust based on actual number of batches and token counts.

---

## Checkpoint & resume

- **Progress file**: `/tmp/opencode/pr_review_progress.json` tracks `{"phase": "batches|consolidate|done", "total_batches": N, "completed_batches": N, "timestamp": "ISO8601"}`.
- **Batch partials**: `/tmp/opencode/review_partial_<N>.json` — saved after each batch.
- **Resume**: If interrupted during batching, re-run skips already-completed batches by checking partial files.

## Notes

- **Model**: resolved via `resolve_model("pr-review")` according to TOKEN_BUDGET. Override with `PR_MODEL`.
- **Timeout**: `900000` (15 min) for large diffs with multiple batches.
- **Batching**: Diff split by files (~4000 chars per batch). Multi-batch triggers hierarchical consolidation.
- **No here-documents**: Always Write + Bash separately.
- **Payload via file**: run.py writes payload to `/tmp/opencode/pr_review_payload.json`.
- **Credentials**: If using Jira/Linear, pass credentials via stdin (`curl -K -`), never in argv.
- **Language**: All generated content (PR reports, model prompts, findings) in Spanish without accents or special characters.
