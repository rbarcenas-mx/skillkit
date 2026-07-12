---
name: ci.prepare
description: Analyze the current project state and generate a CI integration plan with atomic commits, rollback commands, and save points. Delegates file classification and commit strategy to model via resolve_model(). Presents findings to the user and waits for confirmation before generating ci/{id}_tasks.md.
---

# ci.prepare — CI Integration Plan Generation

> **Language note**: All user-facing text below is in English. The orchestrator MUST present all interactions to the user in their language, translating as needed. Generated content (classifications, commit messages, task descriptions) must also be in the user's language.

## Purpose

Analyze the current project state and generate a CI integration plan with atomic commits following Conventional Commits, rollback commands, and save points. The orchestrator collects diagnostics, delegates heavy analysis to `run.py` (local model), presents results to the user, iterates until approval, and generates the task plan.

## Architecture

```
Orchestrator (this agent)
  ├─ 1. Resolve WORKDIR
  ├─ 2. Resolve model + show TOKEN_BUDGET
  ├─ 3. Show execution plan
  ├─ 4. Collect repository diagnostics (shell)
  ├─ 5. Write diagnostics to file
  ├─ 6. Copy run.py → execute analysis
  │     └─ run.py sends diagnostics to model → returns classification + commit strategy
  ├─ 7. Present results, capture user decisions
  ├─ 8. Generate ci/{id}_tasks.md
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
model_id = resolve_model('ci.prepare')
print('TOKEN_BUDGET:', os.environ.get('TOKEN_BUDGET', os.environ.get('OPENCODE_MODO', 'unknown')))
print('Model:', model_id)
print('Provider:', os.environ.get('OPENCODE_PROVEEDOR', '?'))
"
```

Display to user:

```
╔══════════════════════════════════════════════════╗
║           CI.PREPARE                             ║
╠══════════════════════════════════════════════════╣
║  TOKEN_BUDGET:    <mode>                          ║
║  Model:          <model>                         ║
║  Provider:       <provider>                      ║
║  Workdir:        <workdir>                       ║
║  Description:    Analyze repo and generate CI    ║
║                  integration plan                ║
╚══════════════════════════════════════════════════╝
```

## Step 3 — Execution plan

Present phases:

```
Execution Plan
═══════════════

Phase 1 - Diagnose:
  - Check git repo existence
  - Collect file listing (git status or find)
  - Read .gitignore

Phase 2 - Analyze:
  - Send diagnostics to local model
  - Classify files: include / exclude / decide
  - Propose atomic commit strategy

Phase 3 - Decide:
  - Present classification + commit strategy
  - Capture user decisions on 'decide' files
  - Iterate until approval

Phase 4 - Generate:
  - Write ci/{id}_tasks.md with rollback commands

Proceed? (y/n)
```

## Step 4 — Collect repository diagnostics

### 4.1 — Check git repo

```bash
git status 2>&1 | head -20
```

If output contains `fatal: not a git repository`, the repo does not exist.

### 4.2 — Collect file listing

**If repo exists:**
```bash
git status --short 2>&1
```

**If repo does NOT exist:**
```bash
find . -not -path './node_modules/*' -not -path './.git/*' -not -path './dist/*' -not -path './build/*' -not -path './coverage/*' -type f | sort
```

Then for key subdirectories:
```bash
for dir in src tests prisma specs docs .github .specify .opencode ci; do
  [ -d "$dir" ] && echo "=== $dir ===" && find "$dir" -type f | sort && echo ""
done
```

### 4.3 — Read .gitignore

```bash
cat .gitignore 2>/dev/null || echo "(does not exist)"
```

### 4.4 — Write diagnostics JSON

With the **Write** tool, save to `/tmp/opencode/ci_diagnostics.json`:

```json
{
  "repo_exists": true,
  "git_status": "<git status --short output>",
  "files_all": ["<file1>", "<file2>", "..."],
  "dir_contents": {
    "src": ["src/file1.ts", "..."],
    "tests": ["tests/test1.ts", "..."],
    "prisma": ["prisma/schema.prisma", "..."]
  },
  "gitignore_content": "<.gitignore content>",
  "project_root": "<WORKDIR>"
}
```

Only include directories that actually exist and are non-empty.

## Step 5 — Execute run.py (analysis with local model)

```bash
cp "$HOME/.claude/skills/ci.prepare/run.py" /tmp/opencode/ci_prepare_run.py
```

```bash
CI_DIAGNOSTICS_FILE="/tmp/opencode/ci_diagnostics.json" \
python3 /tmp/opencode/ci_prepare_run.py
```

`timeout=660000` (11 min). run.py sends diagnostics to the local model (resolved via `resolve_model("ci.prepare")`) and generates:

- **classification**: files classified into include / exclude / decide, with justifications
- **commit_strategy**: list of atomic commits with Conventional Commit type, files, message, and command
- **gitignore_missing**: missing patterns in .gitignore
- **secrets_detected**: files with potentially exposed secrets

## Step 6 — Present results to user

Read the JSON output from run.py and present.

### 6.1 — Repository status

```
Repository status: (does not exist / exists with X commits)
.gitignore: (complete / missing patterns: X, Y)
Secrets detected: (none / file X)
```

### 6.2 — Files to INCLUDE (grouped by category)

```
Root config: package.json, tsconfig.json, ...
Source code (src/): 30 files
...
```

### 6.3 — EXCLUDED files

Show `classification.exclude` with reasons.

### 6.4 — Files requiring DECISION

Use the `question` tool for the user to decide on files in `classification.decide`.

### 6.5 — Commit strategy

Show table with `commit_strategy`:

```
| # | Type | Files | Message |
|---|------|-------|---------|
| 1 | chore | package.json, tsconfig.json, ... | chore: initial project setup |
| 2 | feat | prisma/schema.prisma | feat: add Prisma schema |
```

Use `question` tool:
- **Accept and generate plan**
- **Modify** (user dictates changes)
- **Cancel**

If the user chooses modify, iterate until confirmed.

## Step 7 — Generate tasks file

### 7.1 — Determine unique ID

```bash
ls ci/*_tasks.md 2>/dev/null | grep -oP '^\d+' | sort -n | tail -1
```

If no files exist, ID = `001`.

### 7.2 — Write `ci/{id}_tasks.md`

Use the **Write** tool. The file must include:

1. **Header**: `run_id`, `desc`, `date`, `total_tasks`
2. **Include/Exclude analysis**: table documenting what is included, excluded, and why
3. **Tasks**: each with `id`, `desc`, `command`, `rollback`, `dangerous`, `deps`, `checkpoint`
4. **Execution Log** (empty)

Example task:
```markdown
## EX-001: chore: initial project setup

- **desc**: chore: initial project setup
- **command**:
  ```
  git init
  git add package.json package-lock.json tsconfig.json .eslintrc.json .gitignore .env.example
  git commit -m "chore: initial project setup"
  ```
- **rollback**: `rm -rf .git`
- **dangerous**: true
- **deps**: []
- **checkpoint**: true
```

### 7.3 — Confirm

```
Plan generated: ci/001_tasks.md
N tasks ready to execute with /ci.execute
```

## Step 8 — Execution report

```
╔══════════════════════════════════════════════════╗
║           EXECUTION COMPLETED                    ║
╠══════════════════════════════════════════════════╣
║  Plan file:     ci/<id>_tasks.md                 ║
║  Tasks:         N                                ║
║  Commits:       N                                ║
║  Dangerous:     N (marked with checkpoint)       ║
║  Next:          /ci.execute to run the plan      ║
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

- **Progress file**: `/tmp/opencode/ci_prepare_progress.json` tracks `{"phase": "analysis|done", "status": "running|done|failed", "timestamp": "ISO8601"}`.
- **Single-shot**: ci.prepare is a single analysis → one output. No multi-step resume needed. If interrupted, restart from diagnostics.

## Notes

- **Model**: resolved via `resolve_model("ci.prepare")` according to TOKEN_BUDGET. Override with `CI_PREPARE_MODEL`.
- **Timeout**: `660000` (11 min) for run.py with local model.
- **No git commands executed**: This skill only plans. Never runs git add/commit.
- **Mandatory confirmation**: Use `question` tool before generating the tasks file.
- **Language**: All generated content (classifications, commit messages, task descriptions) must be in the user's language without accents or special characters.
