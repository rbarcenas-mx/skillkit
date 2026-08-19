# CI Task Plan — skillkit

- **run_id**: 001
- **desc**: CI integration plan for model-call refactor (centralize model logic in lib.call_model + reselect per-skill models)
- **date**: 2026-08-19
- **total_tasks**: 5

## Include / Exclude Analysis

### Included (versioned)

| Category | Files |
|---|---|
| Root config | pyproject.toml, .gitignore |
| Central library | lib/__init__.py, lib/models.json |
| Skills (code) | skills/*/run.py + qa.execute drivers/lib |
| Skills (docs) | skills/*/SKILL.md |
| QA templates | skills/qa.prepare/templates/** |
| Aux scripts | skills/speckit.audit/scripts/** |
| Modelfile | skills/speckit.audit/gemma4-audit.Modelfile |
| Project docs | README.md, CONTRIBUTING.md, CREDITS.md, LICENSE, TODO.md, skillkit-model-refactor-plan.md |
| Commands | commands/*.md |
| Install | configure.py, install.sh |
| CI/CD | .github/workflows/ci.yml |
| Tests | tests/__init__.py, tests/test_lib.py |
| Assets | assets/banner.svg |

### Excluded (NOT versioned)

| File | Reason |
|---|---|
| __pycache__/ | Python bytecode cache (generated) |
| *.egg-info/ | Python packaging metadata (pip/setuptools) |
| .pytest_cache/ | pytest cache (generated) |

### Secrets

None detected.

## Tasks

### EX-001: fix(lib): update models and central library logic

- **desc**: Add lib.call_model() helper and reselect per-skill models in lib/models.json
- **command**:
  ```
  git add lib/__init__.py lib/models.json
  git commit -m "fix(lib): update models and central library logic"
  ```
- **rollback**: `git reset --soft HEAD~1`
- **dangerous**: false
- **deps**: []
- **checkpoint**: false

### EX-002: fix(skills): update CI, QA and Speckit skill implementations

- **desc**: Migrate 6 skill run.py files to lib.call_model()
- **command**:
  ```
  git add skills/ci.prepare/run.py skills/qa.prepare/run.py skills/speckit.audit-resolve/run.py skills/speckit.audit/run.py skills/speckit.diagrams/run.py skills/speckit.prespec/run.py
  git commit -m "fix(skills): update CI, QA and Speckit skill implementations"
  ```
- **rollback**: `git reset --soft HEAD~1`
- **dangerous**: false
- **deps**: ["EX-001"]
- **checkpoint**: false

### EX-003: fix(skills/pr-review-expert): update PR review skill implementation

- **desc**: Migrate pr-review-expert run.py to lib.call_model()
- **command**:
  ```
  git add skills/pr-review-expert/run.py
  git commit -m "fix(skills/pr-review-expert): update PR review skill implementation"
  ```
- **rollback**: `git reset --soft HEAD~1`
- **dangerous**: false
- **deps**: ["EX-001"]
- **checkpoint**: false

### EX-004: test(lib): update central library tests

- **desc**: Add call_model tests to tests/test_lib.py
- **command**:
  ```
  git add tests/test_lib.py
  git commit -m "test(lib): update central library tests"
  ```
- **rollback**: `git reset --soft HEAD~1`
- **dangerous**: false
- **deps**: ["EX-001"]
- **checkpoint**: false

### EX-005: docs: add model refactor plan and pending tasks

- **desc**: Add TODO.md and skillkit-model-refactor-plan.md documentation
- **command**:
  ```
  git add TODO.md skillkit-model-refactor-plan.md
  git commit -m "docs: add model refactor plan and pending tasks"
  ```
- **rollback**: `git reset --soft HEAD~1`
- **dangerous**: false
- **deps**: []
- **checkpoint**: false

## Execution Log

(Sin registros)
EX-001 2026-08-19T16:25:12Z ✅ `5caca53` Add lib.call_model() helper and reselect per-skill models in lib/models.json
EX-002 2026-08-19T16:25:12Z ✅ `6d5411f` Migrate 6 skill run.py files to lib.call_model()
EX-003 2026-08-19T16:25:12Z ✅ `20d2cbf` Migrate pr-review-expert run.py to lib.call_model()
EX-004 2026-08-19T16:25:12Z ✅ `9c34e70` Add call_model tests to tests/test_lib.py
EX-005 2026-08-19T16:25:12Z ✅ `bf7502f` Add TODO.md and skillkit-model-refactor-plan.md documentation

### Final summary

**Status:** ✅ Completed — 5/5 tasks succeeded
**Branch:** `main`
**Commits:** 5caca53 → 6d5411f → 20d2cbf → 9c34e70 → bf7502f
**Tracked files:** 77


## Ship Log

- **Pushed**: 6 commits to origin/main (73c9656..a0a85ff) on 2026-08-19
- **Branch**: main
- **Mode**: solo
- **Pre-flight**: pytest 42 passed; syntax OK; ruff FAILED (preexistent 456 E501)
- **Review**: pr-review-expert (12 batches, programmatic consolidation)
