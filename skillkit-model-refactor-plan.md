# skillkit — model-call refactor (execute later)

Status: DECIDED, not started. Save-point for a future session.

## Decision

Centralize the duplicated model-call logic (currently copy-pasted across 7
skill `run.py` files) into a shared `lib.call_model()` helper. Rationale: the
truncation (`finish_reason=length`) and empty-content detection must live in
ONE place, not be re-added to every caller.

Do NOT force `response_format="json"` on skills that emit prose/markdown
(`prespec`, `audit-resolve`, `qa.prepare`). JSON only for skills that already
parse JSON.

## Baseline (already done this session — do not redo)

- Headroom fully removed (systemd unit + symlink, `~/.bashrc` export,
  `~/.config/opencode/headroom.sh`, pipx `headroom-ai`, and the
  `HEADROOM_PROXY_URL` override in `lib/__init__.py` `_activate_model`).
- `lib/__init__.py` `build_payload`:
  - reasoning models (`deepseek`/`kimi`/`glm`/`qwen`) → `max_tokens=65536`
    (constant `_REASONING_MAX_TOKENS`); non-reasoning → caller `num_predict`.
  - new optional `response_format="json"` → gateway `{"type":"json_object"}`
    / ollama `format:"json"`.
- `skills/speckit.audit/run.py` already migrated: JSON output via
  `response_format="json"`, `parse_audit_response()` (JSON parse + render to
  markdown compatible with `audit-resolve`), truncation/empty detection in
  `run_ollama`.

## Plan

### 1. Add `lib.call_model()` in `lib/__init__.py`

Signature (suggested):

    call_model(model, system_prompt, user_msg, num_predict=2048,
               response_format=None, timeout=600) -> dict

Returns a dict with: `content` (str), `usage` (dict), `finish_reason` (str or
None), `truncated` (bool), `empty` (bool), `error` (str or None).

Behavior (mirrors what `speckit.audit/run.py` `run_ollama` already does):
- build payload via `build_payload(..., response_format=response_format)`.
- POST to `SKILLKIT_API_URL` + `/chat/completions` via curl subprocess, with
  `Authorization: Bearer SKILLKIT_API_KEY` when key present.
- parse JSON response; extract `message.content`, `finish_reason`, `usage`.
- strip `<think>...</think>` from content.
- `truncated=True` when `finish_reason == "length"` (log warning).
- `empty=True` when content is blank (log warning).
- `error` set on timeout / curl failure / non-JSON HTTP body.

### 2. Refactor these skills to call `lib.call_model()`

Replace each local `run_*`/`call_model` body (curl + parse + strip) with a
`call_model(...)` invocation. Keep each skill's own signature/return shape if
callers depend on it (some return `(content, usage)`, others just `content`).

| Skill file | local fn | returns today |
|---|---|---|
| `skills/ci.prepare/run.py` | `run_model` | `(content, usage)` |
| `skills/pr-review-expert/run.py` | `run_ollama` | `(content, usage)` |
| `skills/speckit.diagrams/run.py` | `run_ollama` | `(content, usage)` |
| `skills/speckit.prespec/run.py` | `run_ollama` | `content` |
| `skills/speckit.audit-resolve/run.py` | `run_model` | `content` |
| `skills/qa.prepare/run.py` | `call_model` | `content` |

Notes:
- `qa.prepare` has two extra behaviors to preserve: fallback to
  `reasoning_content` when `content` is empty, and a `re.sub(r'ILD.*?XXX')`
  cleanup. Keep those in the skill after calling `lib.call_model()`.
- `audit-resolve` writes a raw-response debug file on parse failure; keep that
  guard in the skill.

### 3. `response_format="json"` for the JSON-parsing skills

- `ci.prepare`, `pr-review-expert`, `speckit.diagrams`: pass
  `response_format="json"` and simplify their `extract_json*` (drop the
  ```json-fence hunting; keep a `json.loads` fallback for safety).

### 4. Leave unchanged (no model calls)

- `skills/ci.execute`, `skills/ci.ship`, `skills/qa.execute`.

### 5. Tests + verification

- Update/extend `tests/test_lib.py` (call_model payload + response parsing,
  mock subprocess).
- `python3 -m pytest tests/ -q`.
- `python3 -c "import ast; ast.parse(open(...).read())"` on each edited run.py.
- Smoke-run one refactored skill with a tiny prompt to confirm content returns.

## Open / optional (decide when executing)

- Whether `call_model` should log a "respuesta truncada" warning or return it
  silently via the `truncated` flag (audit logs + returns an error string;
  other skills may just want the flag).
- Pre-existing `audit-resolve` regex bug: `**Descripcion**: (.+?)(?:\*\*|$)`
  consumes the `**` before `**Archivo:linea**`, so `archivo` extracts with a
  stray backtick. Fix = positive lookahead `(?=\*\*|$)` — separate, low-risk.

---

## Task 2 — reselect per-skill models (mid/high) by cost + need

Source: https://opencode.ai/docs/es/go/ (fetched 2026-08-19). Data may drift.

### opencode-go model catalog + pricing (per 1M tokens)

| id | endpoint | input $ | output $ | reasoning? | note |
|---|---|---|---|---|---|
| grok-4.5 | /responses | 2.00 | 6.00 | ? | |
| gpt-5.6-luna | /responses | 0.20 | 1.20 | ? | |
| glm-5.3 | /chat/completions | 1.40 | 4.40 | yes | |
| glm-5.2 | /chat/completions | 1.40 | 4.40 | yes | |
| glm-5.1 | /chat/completions | 1.40 | 4.40 | yes | |
| kimi-k3 | /chat/completions | 3.00 | 15.00 | yes | expensive |
| kimi-k2.7-code | /chat/completions | 0.95 | 4.00 | yes | code-specialized |
| kimi-k2.6 | /chat/completions | 0.95 | 4.00 | yes | |
| deepseek-v4-pro | /chat/completions | 0.66 | 1.98 | yes | ×2 peak |
| deepseek-v4-flash | /chat/completions | 0.22 | 0.66 | yes | ×2 peak |
| mimo-v2.5 | /chat/completions | 0.14 | 0.28 | no | cheapest safe |
| mimo-v2.5-pro | /chat/completions | 0.435 | 0.87 | no | |
| minimax-m3 | /messages | 0.30 | 1.20 | ? | anthropic-style |
| minimax-m2.7 | /messages | 0.30 | 1.20 | ? | anthropic-style |
| minimax-m2.5 | /messages | 0.30 | 1.20 | ? | anthropic-style |
| muse-spark-1.2 | /responses | 0.10 | 0.20 | ? | **trains on data** — avoid sensitive |
| qwen3.8-max | /messages | 2.00 | 6.00 | ? | anthropic-style |
| qwen3.7-max | /messages | 2.50 | 7.50 | ? | anthropic-style |
| qwen3.7-plus | /messages | 0.40 | 1.60 | ? | anthropic-style |
| qwen3.6-plus | /messages | 0.50 | 3.00 | ? | anthropic-style |
| hy3 | /chat/completions | 0.14 | 0.58 | ? | |

### Key constraints discovered

1. **Endpoint mismatch**: skillkit only calls `/chat/completions` (hardcoded in
   every `run_*`). Models on `/messages` (qwen3.7/3.8-max, qwen3.6/3.7-plus,
   minimax-*) and `/responses` (grok-4.5, gpt-5.6-luna, muse-spark-1.2) are
   NOT usable until the client supports those endpoints + payload shapes.
   Usable today: glm-*, kimi-*, deepseek-v4-*, mimo-v2.5(-pro), hy3.
2. **DeepSeek peak hours ×2**: 01:00–04:00 and 06:00–10:00 UTC. All other
   hours are off-peak.
3. **Reasoning burn** (measured): deepseek-v4-flash on a 44k-char audit prompt
   emits ~13–18k reasoning tokens before content. With the new 65536 cap it
   completes, but output cost is ~15x a non-reasoning model for the same task.
   mimo-v2.5 emits 0 reasoning tokens (content only).
4. **Privacy**: muse-spark-1.2 trains on prompts/responses (Meta). Do not use
   for anything non-public.

### Rough cost per audit-style call (44k-char prompt, ~11k input tokens)

| model | output tokens | est. output cost |
|---|---|---|
| deepseek-v4-flash (off-peak) | ~22k (reasoning+content) | ~$0.015 |
| mimo-v2.5 | ~2k | ~$0.0006 |
| kimi-k2.7-code | ~2k | ~$0.008 |
| glm-5.2 | ~2k | ~$0.009 |

### Steps

1. Re-check current `lib/models.json` `skill_mapping` mid/high against the
   pricing + reasoning-behavior table above.
2. Define per-skill model choice by **action need** (deep analysis = reasoning
   model, OK to pay; mechanical/classification = non-reasoning cheap model).
   Candidate default mapping:
   - reasoning-heavy (audit spec/plan/tasks, pr-review, prespec): keep a
     reasoning model (deepseek-v4-flash/pro) OR kimi-k2.7-code.
   - mechanical/cost-sensitive (diagrams, lint, code batch audit, ci/qa
     classify): mimo-v2.5.
3. Decide whether to add `/messages` + `/responses` client support to unlock
   the cheaper/higher-quality qwen/minimax/gpt models (separate work item).
4. Update `lib/models.json` (and any `token_cost`/description fields), run the
   per-skill smoke tests.

### Open question to decide at execution

- Is `mimo-v2.5` quality acceptable for audit/spec tasks (its reports are
  terse), or keep deepseek-v4-flash for the deep-reasoning stages and pay the
  reasoning premium? Baseline evidence: mimo returned real content but with
  fewer findings than deepseek on the same spec.
