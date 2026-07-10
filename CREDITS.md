# Credits

SkillKit builds upon and adapts work from the open-source AI skills ecosystem.

## Derived Skills

### pr-review-expert

- **Derived from**: community PR review skill
- **Original author**: unknown
- **Modifications**: integrated `TOKEN_BUDGET` model resolution via `resolve_model()`, batch-by-batch orchestration with progress bar, spinner, checkpoint-based resume, English pattern refactor for orchestrator model instructions
- **Attribution**: if you are or know the original author, please [open an issue](https://github.com/<user>/skillkit/issues)

### speckit.audit / speckit.audit-resolve / speckit.diagrams / speckit.prespec

- **Derived from**: spec-kit audit and diagram generation patterns from the spec-kit ecosystem
- **Modifications**: progressive orchestration (one stage/batch per call), TOKEN_BUDGET integration, checkpoint system, English orchestrator pattern

## Original Skills

The following skills were built from scratch for SkillKit:

- **ci.prepare** — CI integration plan generation with file classification
- **ci.execute** — CI plan execution with save points and rollback
- **ci.ship** — pre-flight validation, push, and CI monitoring
- **qa.prepare** — QA validation plan generation by type
- **qa.execute** — QA plan execution with specialized drivers (shell, http, stress)

## Token Budget Engine

- **`lib/__init__.py`** — original implementation
- **`lib/models.json`** — original model catalog and skill mapping

---

Attribution matters. If you see your work reflected here without credit, let us know and we'll fix it immediately.
