---
description: Create a new SkillKit skill following the patterns documented in CONTRIBUTING.md. Guides you through naming, models.json, run.py, and SKILL.md. Usage: /new-skill <skill-name> "<one-line-description>"
---

Read `$SKILLKIT_HOME/CONTRIBUTING.md` which documents every step of the SkillKit pattern. Then walk through:

1. **Register** the skill in `$SKILLKIT_HOME/lib/models.json` → `skill_mapping`
2. **Create executor** `$SKILLKIT_HOME/skills/<name>/run.py` with `resolve_model()`, spinner, file-based payloads, JSON output, `-K` for auth headers, checkpoint save
3. **Create orchestrator** `$SKILLKIT_HOME/skills/<name>/SKILL.md` with standard header, execution plan, atomic bash calls per step, execution report, token report
4. **Create command** `$SKILLKIT_HOME/commands/<name>.md`
5. **Verify**: `python3 -m py_compile` on run.py
6. **Stage**: `git add -A && git commit`

**Arguments**: `$ARGUMENTS` — skill name (required) and optional description. Example: `/new-skill my-linter "Lint all Python files using a local model"`