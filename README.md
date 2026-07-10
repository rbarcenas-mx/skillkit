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

## How to extend SkillKit with new skills

Every skill is a directory under `skills/<name>/` following the **Orchestrator + Executor** pattern. You add three things: a `models.json` entry, a `run.py` executor, and a `SKILL.md` orchestrator.

### 1. Register in models.json

Add an entry to `lib/models.json` → `skill_mapping`:

```json
{
  "my-skill": {
    "task": "What it does",
    "low": "gemma4:26b",
    "medium": "opencode-go/deepseek-v4-flash",
    "high": "opencode-go/glm-5.2"
  }
}
```

`low/medium/high` map to `TOKEN_BUDGET` levels. Low is always a local model via Ollama.

### 2. Create the executor (`skills/<name>/run.py`)

Minimal scaffold:

```python
#!/usr/bin/env python3
import json, os, subprocess, sys, threading, time

sys.stderr.reconfigure(line_buffering=True)
sys.path.insert(0, os.environ["SKILLKIT_HOME"])
from lib import resolve_model

MODEL = resolve_model("my-skill")
SKILL_NAME = "my-skill"
PROGRESS_FILE = f"/tmp/opencode/{SKILL_NAME}_progress.json"

def log(msg):
    print(msg, file=sys.stderr, flush=True)

def spinner(stop, label="Processing"):
    frames = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
    t0 = time.time()
    while not stop.is_set():
        sys.stderr.write(f'\r  {frames[int(time.time()*10)%len(frames)]} {label} ({time.time()-t0:.0f}s)   ')
        sys.stderr.flush()
        time.sleep(0.1)
    sys.stderr.write(f'\r  \u2705 {label} — done ({time.time()-t0:.1f}s)\n')
    sys.stderr.flush()

def save_progress(phase, status="running"):
    os.makedirs("/tmp/opencode", exist_ok=True)
    with open(PROGRESS_FILE, "w") as f:
        json.dump({"phase": phase, "status": status}, f)

# Build payload, send with curl, auth via -K conf file
payload = {"model": MODEL, "messages": [...]}
with open("/tmp/opencode/my_skill_payload.json", "w") as f:
    json.dump(payload, f)

curl = ["curl", "-s", "-X", "POST", URL, "-H", "Content-Type: application/json"]
if API_KEY:
    os.makedirs("/tmp/opencode", exist_ok=True)
    with open("/tmp/opencode/skillkit_headers.conf", "w") as hf:
        hf.write(f"Authorization: Bearer {API_KEY}\n")
    curl += ["-K", "/tmp/opencode/skillkit_headers.conf"]

save_progress("running")
stop = threading.Event()
threading.Thread(target=spinner, args=(stop,)).start()
try:
    r = subprocess.run(curl + ["-d", "@/tmp/opencode/my_skill_payload.json"],
                       capture_output=True, text=True, timeout=600)
finally:
    stop.set()

save_progress("done")
result = {"status": "ok", "result": r.stdout}
print(json.dumps(result))
```

Key rules:
- **API keys never in argv**: use `-K <conf_file>` for Authorization headers
- **JSON on stdout**, progress on stderr
- **Spinner** for model calls longer than a few seconds
- **Checkpoint** at `/tmp/opencode/<skill>_progress.json`
- **`os.environ["SKILLKIT_HOME"]`** not hardcoded paths

### 3. Create the orchestrator (`skills/<name>/SKILL.md`)

```markdown
---
name: my-skill
description: One-line description with usage. Usage: /my-skill
---

# my-skill

## Architecture

```
Orchestrator (this agent)
  ├─ 1. Resolve WORKDIR
  ├─ 2. Resolve model + show TOKEN_BUDGET
  ├─ 3. Show execution plan
  ├─ 4. Copy run.py → execute analysis
  │     └─ run.py returns JSON
  ├─ 5. Present results
  ├─ 6. Execution report
  └─ 7. Token report
```

## Step 1 — Resolve working directory

```bash
pwd
```

## Step 2 — Resolve model and show TOKEN_BUDGET

```bash
python3 -c "
import sys, os
sys.path.insert(0, os.environ['SKILLKIT_HOME'])
from lib import resolve_model
m = resolve_model('my-skill')
print('TOKEN_BUDGET:', os.environ.get('TOKEN_BUDGET', '?'))
print('Model:', m)
print('Provider:', os.environ.get('OPENCODE_PROVEEDOR', '?'))
"
```

Display:

```
╔══════════════════════════════════════════════════╗
║           MY-SKILL                               ║
╠══════════════════════════════════════════════════╣
║  TOKEN_BUDGET:    <mode>                        ║
║  Model:          <model>                       ║
║  Provider:       <provider>                    ║
║  Description:    <brief>                       ║
╚══════════════════════════════════════════════════╝
```

## Step 3 — Execution plan

Briefly list phases so the user knows what to expect.

## Step N-1 — Execution report

```
╔══════════════════════════════════════════════════╗
║           EXECUTION COMPLETED                    ║
╠══════════════════════════════════════════════════╣
║  Steps:          N completed                     ║
║  Duration:        Xm Ys                          ║
╚══════════════════════════════════════════════════╝
```

## Step N — Token report

```
| Source                   | Calls | Input (tok) | Output (tok) | Total (tok) | Cost |
|---|---|---|---|---|---|---|
| **Remote**               |       |             |              |             |      |
| SKILL.md + orchestration | 1     | X,XXX       | —            | X,XXX       | 💰   |
| **Total remote**         |       |             |              | **X,XXX**   |      |
|                          |       |             |              |             |      |
| **Local**                |       |             |              |             |      |
| Analysis (run.py)        | 1     | X,XXX       | X,XXX        | X,XXX       | 🆓   |
| **Total local**          | **1** | **XX,XXX**  | **XX,XXX**   | **XX,XXX**  | 🆓   |
|---|---|---|---|---|---|---|
| Remote share             |       |             |              | X,XXX (~X%)  | 💰   |
| Local share              |       |             |              | XX,XXX (~X%) | 🆓   |
```
```

### 4. (Optional) Add a CLI command reference

If you use opencode, add `commands/<name>.md`:

```markdown
---
description: One-line with usage. Usage: /my-skill [args]
---

Load the `my-skill` skill via the `skill` tool and execute the steps defined in its SKILL.md.

**Arguments**: `$ARGUMENTS` — description of arguments.
```

### Golden rules for all skills

1. **Orchestrator delegates**, executor executes. No heavy model calls in SKILL.md steps.
2. **API keys** go to `/tmp/opencode/skillkit_headers.conf`, never in `-H` argv flags.
3. **Graceful degradation**: if a model isn't available, warn and fall back. Never crash.
4. **`os.environ["SKILLKIT_HOME"]`** everywhere — no hardcoded `~/.config/opencode` or `~/.claude/skills`.
5. **JSON on stdout**, progress on stderr. Always `{"status": "ok|error", ...}` as final print.
6. **Progress checkpoint** at `/tmp/opencode/<skill>_progress.json` for multi-step or multi-batch skills.
7. **English** in SKILL.md and run.py (comments, logs, error messages). System prompts keep the target language of generated content (typically Spanish).
8. **Token report** as final step in every SKILL.md.

## License

MIT — see [LICENSE](LICENSE) for full text.
