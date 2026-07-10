# Contributing a SkillKit

This document describes how to create a new skill that follows the SkillKit pattern. Every skill in this repo must implement the **Orchestrator + Executor** architecture: the orchestrator (SKILL.md) decomposes the problem into atomic calls, and the executor (run.py) does one thing per call using a model resolved via `TOKEN_BUDGET`.

## Directory structure

```
skillkit/skills/<skill-name>/
├── SKILL.md           # Orchestrator instructions (Anthropic format)
├── run.py             # Executor: atomic local model call
├── templates/         # Optional: prompt templates, YAML steps
├── lib/               # Optional: reusable Python modules (e.g. drivers)
└── scripts/           # Optional: shell scripts for setup/teardown
```

## Step 1: `models.json` — Register the skill

Add an entry to `lib/models.json` → `skill_mapping`:

```json
{
  "my-skill": {
    "task": "Brief description",
    "low": "gemma4:26b",
    "medium": "opencode-go/deepseek-v4-flash",
    "high": "opencode-go/glm-5.2"
  }
}
```

- `low` — local model via Ollama, zero cost
- `medium` — remote balanced model
- `high` — remote premium model

## Step 2: `run.py` — The executor

The executor is a Python script that does **one atomic task** and returns JSON on stdout. Progress, spinners, and logs go to stderr.

### Required imports

```python
#!/usr/bin/env python3
import json, os, re, subprocess, sys, threading, time

sys.stderr.reconfigure(line_buffering=True)

sys.path.insert(0, os.environ["SKILLKIT_HOME"])
from lib import resolve_model
```

### Model resolution

```python
SKILL_NAME = "my-skill"
MODEL = resolve_model(SKILL_NAME)
```

This reads `TOKEN_BUDGET`, looks up `my-skill` in `models.json`, and returns the appropriate model ID. Sets `OPENCODE_MODEL`, `OPENCODE_PROVEEDOR`, etc. automatically. If the model is not available, degrades gracefully (warns + falls back, never crashes).

### Spinner for API calls

```python
def spinner_while_waiting(stop_event, label="Processing"):
    frames = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
    i = 0
    t0 = time.time()
    while not stop_event.is_set():
        elapsed = time.time() - t0
        sys.stderr.write(f'\r  {frames[i % len(frames)]} {label} ({elapsed:.0f}s)   ')
        sys.stderr.flush()
        i += 1
        time.sleep(0.15)
    elapsed = time.time() - t0
    sys.stderr.write(f'\r  \u2705 {label} — completed in {elapsed:.1f}s   \n')
    sys.stderr.flush()
```

### Curl with model API (no argv secrets)

```python
payload = {"model": api_model, "messages": [...]}
payload_path = "/tmp/opencode/my_skill_payload.json"
with open(payload_path, "w") as f:
    json.dump(payload, f, ensure_ascii=False)

headers = ["-H", "Content-Type: application/json"]
if API_KEY:
    os.makedirs("/tmp/opencode", exist_ok=True)
    with open("/tmp/opencode/skillkit_headers.conf", "w") as _hf:
        _hf.write(f"Authorization: Bearer {API_KEY}\n")
    headers += ["-K", "/tmp/opencode/skillkit_headers.conf"]

result = subprocess.run(["curl", "-s", "-X", "POST", url, *headers, "-d", "@" + payload_path], ...)
```

Auth headers go to a temp conf file (`-K`), never in argv. This prevents API keys from being visible in `ps`.

### JSON output

```python
# Success
print(json.dumps({"status": "ok", "result": "...", "_tokens": {"prompt_eval_count": N, "eval_count": N}}))

# Error
print(json.dumps({"status": "error", "error": "description"}))
sys.exit(1)
```

### Progress checkpoint (required for multi-step skills)

```python
PROGRESS_FILE = "/tmp/opencode/my_skill_progress.json"

def save_progress(phase, total=0, completed=0, status="running"):
    os.makedirs("/tmp/opencode", exist_ok=True)
    from datetime import datetime, timezone
    progress = {"phase": phase, "total": total, "completed": completed, "status": status, "timestamp": datetime.now(timezone.utc).isoformat()}
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f)
```

## Step 3: `SKILL.md` — The orchestrator

### Frontmatter

```yaml
---
name: my-skill
description: One-line description with Usage. Model resolved via TOKEN_BUDGET through resolve_model().
---
```

### Architecture section

```markdown
## Architecture

```
Orchestrator (this agent)
  ├─ 1. Resolve WORKDIR
  ├─ 2. Resolve model + show TOKEN_BUDGET
  ├─ 3. Show execution plan
  ├─ 4. Copy run.py → execute analysis
  │     └─ run.py calls model → returns JSON
  ├─ 5. Present results
  ├─ 6. Execution report
  └─ 7. Token report
```
```

### Step 2 — Standard header

```markdown
## Step 2 — Resolve model and show TOKEN_BUDGET

```bash
python3 -c "
import sys, os, json
sys.path.insert(0, os.environ['SKILLKIT_HOME'])
from lib import resolve_model
model_id = resolve_model('my-skill')
print('TOKEN_BUDGET:', os.environ.get('TOKEN_BUDGET', os.environ.get('OPENCODE_MODO', 'unknown')))
print('Model:', model_id)
print('Provider:', os.environ.get('OPENCODE_PROVEEDOR', '?'))
"
```

Display:

```
╔══════════════════════════════════════════════════╗
║           MY-SKILL                              ║
╠══════════════════════════════════════════════════╣
║  TOKEN_BUDGET:    <mode>                        ║
║  Model:          <model>                       ║
║  Provider:       <provider>                    ║
║  Description:    <brief>                       ║
╚══════════════════════════════════════════════════╝
```
```

### Step 3 — Execution plan

Briefly list the phases so the user knows what will happen.

### Step 3+N — Execution report

```markdown
```
╔══════════════════════════════════════════════════╗
║           EXECUTION COMPLETED                    ║
╠══════════════════════════════════════════════════╣
║  Total steps:     N                               ║
║  Completed:       N  ✅                           ║
║  Failed:          F  ❌                           ║
║  Duration:        Xm Ys                           ║
╚══════════════════════════════════════════════════╝
```
```

### Final step — Token report

```markdown
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
| **Total local**          | **N** | **XX,XXX**  | **XX,XXX**   | **XX,XXX**  | 🆓   |
|---|---|---|---|---|---|---|
| Remote share             |       |             |              | X,XXX (~X%)  | 💰   |
| Local share              |       |             |              | XX,XXX (~X%) | 🆓   |
```
```

## Step 4: `commands/<skill>.md` — opencode CLI reference (optional)

```markdown
---
description: One-line description with Usage. Usage: /my-skill [args]
---

Load the `my-skill` skill via the `skill` tool and execute the steps defined in its SKILL.md.

**Arguments**: `$ARGUMENTS` — description of arguments.
```

## Golden rules

1. **Orchestrator never does heavy processing** — it decomposes, delegates, presents. The model call goes in run.py.
2. **Executor never orchestrates** — one atomic call, one JSON on stdout, no branching logic.
3. **API keys never in argv** — use `-K <conf_file>` for Authorization headers.
4. **Graceful everything** — if a model isn't available, warn and fall back. Never crash.
5. **SKILLKIT_HOME, not hardcoded paths** — all references use `os.environ["SKILLKIT_HOME"]`.
6. **English in SKILL.md and run.py** (comments, logs, errors). System prompts keep the target language.
7. **Checkpoint for multi-step** — `/tmp/opencode/<skill>_progress.json` saves after each step.
8. **Language** — All generated content (reports, diagrams, PR reviews, etc.) in Spanish without accents or special characters, unless the skill is explicitly for another language.
