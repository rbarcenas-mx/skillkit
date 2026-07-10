# SkillKit

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Skills + Token Budget Engine** — Anthropic-format skills with built-in model routing that respects your token spend budget.

## Architecture: Orchestrator + Executor

Every skill in SkillKit follows the **Orchestrator + Executor** pattern — the strategy that Anthropic and other AI labs now recommend as the optimal way to manage token costs without sacrificing quality.

```
Remote Agent (Orchestrator)                    Local System (Executor)
   ┌──────────────────────┐                   ┌──────────────────────────┐
   │  Advisor model       │                   │  Worker model            │
   │  (Claude, GPT, etc.)  │                   │  (via TOKEN_BUDGET)      │
   │                      │                   │                          │
   │  • Decompose task     │  ── atomic ──→   │  • run.py call #1        │
   │  • Show progress bar  │     calls        │  • run.py call #2        │
   │  • Save checkpoints   │  ←── JSON ────   │  • run.py call #N        │
   │  • Present results    │                  │                          │
   │  • Token accounting   │                  │  Returns structured       │
   └──────────────────────┘                   │  result on stdout,       │
                                              │  progress on stderr      │
                                              └──────────────────────────┘
```

The **orchestrator** (the remote agent — Claude Code, opencode, Copilot, etc.) is the "advisor" model. It reads `SKILL.md`, breaks the work into atomic one-shot calls to `run.py`, shows live progress to the user after each step, manages fault-tolerant checkpoints for resume, presents an initial execution plan and a final consolidated report, and tracks token consumption per phase.

The **executor** (`run.py`) is the "worker" — resolved via `TOKEN_BUDGET` to the cheapest adequate model (local Ollama at $0, or a remote model at low/medium/high cost). It does one thing, returns one JSON on stdout, and exits. No orchestration logic in the executor.

This separation means:

- **You control the cost**: expensive reasoning stays in the orchestrator; the executor runs on the model you choose via `TOKEN_BUDGET`
- **Fault tolerance**: if an executor call fails, the orchestrator can retry, skip, or abort without losing progress — checkpoints guarantee resume
- **Live feedback**: the orchestrator shows a progress bar and findings after every single executor call
- **Audit trail**: initial plan → each executor call result → final token report

## What is this?

SkillKit provides 10 ready-to-use development skills (CI, QA, audit, reviews, diagrams) built on this pattern, plus a **token budget engine** (`lib/`) that automatically selects the right model for the executor based on how much you want to spend. Every model referenced in `lib/models.json` must be available and configured by you — SkillKit provides the mapping, you provide the access.

| `TOKEN_BUDGET` | Executor model range | Token cost | Use case |
|---|---|---|---|
| `low` | Ollama local (gemma4, deepseek-coder, deepseek-r1) | $0 | Daily development |
| `medium` | Remote balanced (deepseek-v4-flash, kimi-k2.7) | $$ | Pre-push QA |
| `high` | Remote premium (glm-5.2, qwen3.7-max) | $$$ | Critical reviews |

## Model availability & graceful degradation

If the model mapped to your `TOKEN_BUDGET` level is **not available** (Ollama model not pulled, remote provider not configured, API key missing), SkillKit **never crashes**. Instead:

1. **Warns** you on stderr about the missing model
2. **Falls back** to the next available tier (e.g. `low` → `medium` → `high`)
3. If nothing works: **keeps your current model** and warns that TOKEN_BUDGET was bypassed
4. The skill continues execution regardless — broken budget doesn't break your workflow

Example:

```
WARNING: TOKEN_BUDGET=low → 'gemma4:26b' not found in Ollama
  Falling back to medium: opencode-go/deepseek-v4-flash
  Skill: ci.prepare — proceeding with fallback model
```

## Prerequisites

The models referenced in `lib/models.json` for each `TOKEN_BUDGET` level must be made available by you. SkillKit selects the model — you provide the access.

- **Local models** (`TOKEN_BUDGET=low`): pull with `ollama pull <model>` for each model listed in your chosen level
- **Remote models** (`TOKEN_BUDGET=medium/high`): the API key for each provider must be accessible to the curl calls made by run.py (typically via environment variables or an auth config file — your agent's standard mechanism for providing secrets)
- If a model is not available, SkillKit **does not crash** — it warns and falls back gracefully to the next available tier, or keeps your current model

## Quick start

```bash
git clone https://github.com/<user>/skillkit.git ~/skillkit
cd ~/skillkit
./install.sh
```

Or manual:

```bash
export SKILLKIT_HOME="$HOME/skillkit"
export TOKEN_BUDGET=low
echo 'export SKILLKIT_HOME="$HOME/skillkit"' >> ~/.bashrc
echo 'export TOKEN_BUDGET=low' >> ~/.bashrc
source ~/.bashrc
```

## Skills

### spec-kit ecosystem

Designed to work with [spec-kit](https://github.com/github/spec-kit) artifacts (`specs/<feature>/spec.md`, `plan.md`, `tasks.md`).

| Skill | Description |
|---|---|
| `speckit.prespec` | Analyze a raw idea, detect ambiguities, generate pre-spec |
| `speckit.diagrams` | Generate Mermaid.js architecture diagrams from spec-kit artifacts |
| `speckit.audit` | Progressive audit of specs, plans, tasks, code |
| `speckit.audit-resolve` | Resolve audit findings with model per finding type |

### Git & CI/CD

Version control, integration planning, and deployment.

| Skill | Description |
|---|---|
| `ci.prepare` | Generate CI integration plan with atomic commits |
| `ci.execute` | Execute a ci/{id}_tasks.md plan with checkpoints and rollback |
| `ci.ship` | Validate, push, and monitor CI for commits |
| `pr-review-expert` | Structured PR review (blast radius, security, breaking changes) |

### QA & Testing

Validation plans and execution for infrastructure, unit tests, flows, stress, and scale.

| Skill | Description |
|---|---|
| `qa.prepare` | Generate QA validation plans by type (infra, unit, flow, stress, scale) |
| `qa.execute` | Execute QA plans — Docker, migrations, tests, HTTP flows |

## Token Budget Engine

Every skill calls `resolve_model(skill_name)` which:

1. Reads `TOKEN_BUDGET` (`low` | `medium` | `high`)
2. Looks up the skill in `lib/models.json` → `skill_mapping`
3. Returns the right model for that budget level
4. Sets `OPENCODE_MODEL`, `OPENCODE_PROVEEDOR`, `OPENCODE_API_URL` automatically
5. **If unavailable**: degrades gracefully — warns, falls back, never crashes

Configure your own mapping by editing `lib/models.json`.

## Directory structure

```
skillkit/
├── lib/                    # Token budget engine
│   ├── __init__.py         # resolve_model(), budget resolution, graceful fallback
│   └── models.json         # Model catalog + per-skill mapping
├── skills/                 # Anthropic-format skills
│   ├── ci.execute/
│   │   ├── SKILL.md
│   │   └── run.py
│   └── ...
└── commands/               # CLI command references
    ├── ci.execute.md
    └── ...
```

## Requirements

- Python 3.10+
- [Ollama](https://ollama.ai) (for `TOKEN_BUDGET=low`)
- `gh` CLI (for PR review and ci.ship)
- `curl` (for remote model calls)

## Credits & Attribution

This project builds upon and adapts open-source skills from the AI coding community. Some skills are original; others are derived from community work.

- **`pr-review-expert`** — derived from a community PR review skill. Original author unknown. If you recognize this as your work, please [open an issue](https://github.com/<user>/skillkit/issues) for proper attribution.
- **`speckit.audit` / `speckit.diagrams` / `speckit.prespec`** — adapted from spec-kit patterns.
- **`ci.execute` / `ci.prepare` / `ci.ship` / `qa.execute` / `qa.prepare`** — original implementations.

See [CREDITS.md](CREDITS.md) for detailed attributions.

## Creating new skills

```bash
# Via opencode CLI
/new-skill my-tool "Does X thing with local model"

# Or tell any AI agent:
"Read $SKILLKIT_HOME/CONTRIBUTING.md and create a skill called my-tool"
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the complete guide — structure, executor pattern, model mapping, required features, and golden rules.

## License

MIT — see [LICENSE](LICENSE) for full text.
