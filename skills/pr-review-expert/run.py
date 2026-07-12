#!/usr/bin/env python3
"""
pr-review-expert — Review PRs using local/remote model.

Takes a PR diff and metadata, sends them to the model for analysis
of blast radius, security, breaking changes, performance, and code quality.
Supports batching for large diffs with hierarchical consolidation.

Input (environment variables):
  PR_DIFF:             diff content (required)
  PR_DIFF_FILE:        path to .diff file (alternative to PR_DIFF)
  PR_METADATA:         JSON with title, body, labels, etc. (optional)
  PR_REPO_CONTEXT:     path to constitution.md or spec artifacts (optional)
  PR_MODEL:            model override (default: resolved via resolve_model("pr-review"))
  PR_BATCH_ONLY:       run a single batch (value = batch index or "info")
  PR_CONSOLIDATE_DIR:  path to directory with review_partial_*.json files

Output: JSON with structured review (findings, checklist, verdict).
"""

import json
import os
import re
import subprocess
import sys
import threading
import time

sys.stderr.reconfigure(line_buffering=True)
sys.stdout.reconfigure(line_buffering=True)

sys.path.insert(0, os.environ["SKILLKIT_HOME"])
from lib import resolve_model

DEFAULT_MODEL = resolve_model("pr-review")
API_URL = os.environ.get("OPENCODE_API_URL", "http://localhost:11434/v1")
API_KEY = os.environ.get("OPENCODE_API_KEY", "")
TIMEOUT = 600
BATCH_SIZE = 4000
CONSOLIDATION_GROUP_SIZE = 8
PROGRESS_FILE = "/tmp/opencode/pr_review_progress.json"


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


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
    sys.stderr.write(f'\r  {"\u2705"} {label} — completed in {elapsed:.1f}s   \n')
    sys.stderr.flush()


def save_progress(phase: str, total_batches: int = 0, completed_batches: int = 0,
                  status: str = "running") -> None:
    os.makedirs(os.path.dirname(PROGRESS_FILE), exist_ok=True)
    from datetime import datetime, timezone
    progress = {
        "phase": phase,
        "total_batches": total_batches,
        "completed_batches": completed_batches,
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False)


def run_ollama(system_prompt: str, user_msg: str, model: str,
               num_predict: int = 4096) -> tuple:
    api_model = os.environ.get("OPENCODE_MODEL", model)
    payload = {
        "model": api_model,
        "stream": False,
        "options": {"num_predict": num_predict},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
    }
    payload_path = "/tmp/opencode/pr_review_payload.json"
    os.makedirs("/tmp/opencode", exist_ok=True)
    with open(payload_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    try:
        headers = ["-H", "Content-Type: application/json"]
        if API_KEY:
            headers += ["-H", f"Authorization: Bearer {API_KEY}"]
        url = API_URL.rstrip('/')
        if not url.endswith('/chat/completions'):
            url += '/chat/completions'
        result = subprocess.run(
            ["curl", "-s", "-X", "POST", url,
             *headers, "-d", "@" + payload_path],
            capture_output=True, text=True, timeout=TIMEOUT,
        )
        if result.returncode != 0:
            return f"ERROR curl: {result.stderr}", {}
        if not result.stdout.strip():
            return "ERROR: empty response", {}
        resp = json.loads(result.stdout)
        choices = resp.get("choices", [])
        if choices:
            content = choices[0]["message"]["content"]
        else:
            content = resp.get("message", {}).get("content", "")
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
        usage = resp.get("usage", {})
        return content.strip(), usage
    except Exception as e:
        return f"ERROR: {e}", {}


def extract_json(text: str) -> dict:
    m = re.search(r"```json\s*\n(.*?)\n```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return {"error": "Could not extract JSON", "raw": text[:500]}


def split_diff_into_batches(diff: str) -> list:
    """Split diff into batches by file (~BATCH_SIZE chars each)."""
    files = re.split(r'(?=^diff --git )', diff, flags=re.MULTILINE)
    files = [f.strip() for f in files if f.strip()]
    if not files:
        return [{"label": "full", "content": diff}]

    batches = []
    current = ""
    current_label = ""
    for f in files:
        fname = re.search(r'^diff --git a/(.*?) b/', f)
        label = fname.group(1) if fname else "unknown"
        if len(current) + len(f) > BATCH_SIZE and current:
            batches.append({"label": current_label, "content": current})
            current = f
            current_label = label
        else:
            if current:
                current_label += f", {label}"
            else:
                current_label = label
            current += ("\n" if current else "") + f
    if current:
        batches.append({"label": current_label, "content": current})
    return batches


def _grouped(lst: list, size: int):
    for i in range(0, len(lst), size):
        yield lst[i:i + size]


def _flatten_merge(partials: list) -> dict:
    """Merge N partial reports WITHOUT calling the model.
    Merges arrays, takes max blast radius, sums checklist."""
    levels = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}

    result = {
        "blast_radius": {"level": "LOW", "summary": "", "details": []},
        "security": {"findings": []},
        "breaking_changes": {"found": False, "items": []},
        "performance": {"issues": []},
        "code_quality": {"issues": []},
        "tests": {"coverage_assessment": "", "issues": []},
        "checklist_completed": {},
        "verdict": "COMMENT",
        "summary": "",
        "must_fix": [],
        "should_fix": [],
        "suggestions": [],
        "looks_good": [],
    }

    seen_descriptions = set()
    max_level = 0
    total_must = 0
    total_should = 0

    for p in partials:
        if "error" in p:
            continue

        sr = p.get("blast_radius", {})
        lvl = levels.get(sr.get("level", "LOW"), 0)
        if lvl > max_level:
            max_level = lvl
            result["blast_radius"]["level"] = sr.get("level")
            result["blast_radius"]["summary"] = sr.get("summary", "")
        for d in sr.get("details", []):
            if d not in seen_descriptions:
                seen_descriptions.add(d)
                result["blast_radius"]["details"].append(d)

        for finding in p.get("security", {}).get("findings", []):
            desc = finding.get("description", "")
            if desc not in seen_descriptions:
                seen_descriptions.add(desc)
                result["security"]["findings"].append(finding)

        bc = p.get("breaking_changes", {})
        if bc.get("found"):
            result["breaking_changes"]["found"] = True
            for item in bc.get("items", []):
                desc = item.get("description", "")
                if desc not in seen_descriptions:
                    seen_descriptions.add(desc)
                    result["breaking_changes"]["items"].append(item)

        for issue in p.get("performance", {}).get("issues", []):
            desc = issue.get("description", "")
            if desc not in seen_descriptions:
                seen_descriptions.add(desc)
                result["performance"]["issues"].append(issue)

        for issue in p.get("code_quality", {}).get("issues", []):
            desc = issue.get("description", "")
            if desc not in seen_descriptions:
                seen_descriptions.add(desc)
                result["code_quality"]["issues"].append(issue)

        t = p.get("tests", {})
        if t.get("coverage_assessment"):
            result["tests"]["coverage_assessment"] = t["coverage_assessment"]
        for issue in t.get("issues", []):
            if issue not in seen_descriptions:
                seen_descriptions.add(issue)
                result["tests"]["issues"].append(issue)

        chk = p.get("checklist_completed", {})
        for k, v in chk.items():
            if k not in result["checklist_completed"] or v > result["checklist_completed"].get(k, 0):
                result["checklist_completed"][k] = v

        for item in p.get("must_fix", []):
            desc = item.get("description", "")
            if desc not in seen_descriptions:
                seen_descriptions.add(desc)
                item["id"] = len(result["must_fix"]) + 1
                result["must_fix"].append(item)
                total_must += 1

        for item in p.get("should_fix", []):
            desc = item.get("description", "")
            if desc not in seen_descriptions:
                seen_descriptions.add(desc)
                item["id"] = len(result["should_fix"]) + len(result["must_fix"]) + 1
                result["should_fix"].append(item)
                total_should += 1

        for s in p.get("suggestions", []):
            desc = s.get("description", "") if isinstance(s, dict) else s
            if desc not in seen_descriptions:
                seen_descriptions.add(desc)
                result["suggestions"].append(s)

        for g in p.get("looks_good", []):
            if g not in seen_descriptions:
                seen_descriptions.add(g)
                result["looks_good"].append(g)

    if total_must > 0:
        result["verdict"] = "REQUEST_CHANGES"
    elif total_should > 0:
        result["verdict"] = "COMMENT"
    else:
        result["verdict"] = "APPROVE"

    total_findings = (len(result["security"]["findings"]) +
                      len(result["breaking_changes"]["items"]) +
                      len(result["performance"]["issues"]) +
                      len(result["code_quality"]["issues"]))
    result["summary"] = (f"Automatic merge of {len(partials)} partial reports. "
                         f"{total_findings} unique findings, "
                         f"{total_must} must_fix, {total_should} should_fix.")

    return result


# ──────────────────────────────────────────────
# System prompts (Spanish — output is Spanish)
# ──────────────────────────────────────────────

SYSTEM_PROMPT = r"""Eres un revisor de codigo senior. Analiza el diff de un Pull Request y produce una revision estructurada.

## Reglas de revision

### Blast Radius
Para cada archivo modificado, evalua:
- CRITICAL: libreria compartida, modelo DB, auth middleware, contrato API
- HIGH: servicio usado por >3 otros, config compartida, env vars
- MEDIUM: cambio interno de un servicio, funcion utilitaria
- LOW: componente UI, archivo de test, docs

### Seguridad
Busca especificamente:
- SQL injection (string interpolation en queries sin parametrizar)
- Hardcoded secrets (password, api_key, token, private_key en codigo)
- XSS (dangerouslySetInnerHTML, innerHTML sin sanitizar)
- Auth bypass (comentarios TODO auth, bypass, skip auth)
- Hash inseguros (md5, sha1)
- eval/exec con input de usuario
- Path traversal (path.join con req.*)
- Datos sensibles en logs (PII, tokens, passwords)

### Breaking Changes
- Endpoints API removidos o renombrados sin deprecation
- Campos requeridos nuevos en respuestas existentes
- Columnas DB removidas sin migracion en dos fases
- Env vars removidas

### Rendimiento
- Patrones N+1 query (DB calls dentro de loops)
- Bucles no acotados sobre datasets potencialmente grandes
- Dependencias nuevas pesadas sin justificacion
- Faltan indices para nuevos patrones de query

### Calidad de Codigo
- Codigo muerto o imports no usados
- Manejo de errores ausente (catch blocks vacios)
- Consistencia con patrones existentes
- TODOs sin tracking

### Tests
- Nuevas funciones publicas sin tests
- Edge cases no cubiertos (empty, null, max values)
- Tests eliminados sin razon clara
- Cobertura de paths de error

Responde EXACTAMENTE con este JSON (sin texto fuera del JSON):

```json
{
  "blast_radius": {"level": "LOW|MEDIUM|HIGH|CRITICAL", "summary": "...", "details": ["..."]},
  "security": {"findings": [{"severity": "critical|high|medium|low", "file": "...", "line": 42, "description": "...", "fix": "..."}]},
  "breaking_changes": {"found": true, "items": [{"type": "api|db|env|config", "description": "..."}]},
  "performance": {"issues": [{"severity": "high|medium|low", "file": "...", "description": "..."}]},
  "code_quality": {"issues": [{"severity": "high|medium|low", "file": "...", "description": "..."}]},
  "tests": {"coverage_assessment": "...", "issues": ["..."]},
  "checklist_completed": {"scope": 5, "blast_radius": 5, "security": 9, "testing": 6, "breaking": 5, "performance": 6, "quality": 5},
  "verdict": "APPROVE|COMMENT|REQUEST_CHANGES",
  "summary": "...",
  "must_fix": [{"id": 1, "severity": "critical", "description": "...", "file": "...", "fix": "..."}],
  "should_fix": [{"id": 2, "severity": "high", "description": "..."}],
  "suggestions": [{"id": 3, "description": "..."}],
  "looks_good": ["..."]
}
```

Responde unicamente en espanol para descripciones y resumenes. Los nombres de archivo y codigo se mantienen como en el diff."""


CONSOLIDATE_PROMPT = r"""Eres un revisor de codigo senior. CONSOLIDA multiples reportes parciales de revision de PR en UN SOLO reporte unificado.

Instrucciones:
1. Deduplica hallazgos que aparecen en multiples batches
2. Elimina contradicciones entre reportes
3. Determina el blast radius GLOBAL (el maximo nivel entre todos los batches)
4. Consolida checklist (maximos valores)
5. Produce veredicto GLOBAL

Responde con el MISMO formato JSON que los reportes parciales.
Responde unicamente en espanol."""


def _consolidate_group(partials: list, group_label: str, model: str, depth: int = 0) -> dict:
    """Consolidate a group of partial reports. Tries model first,
    falls back to programmatic flatten on failure."""
    indent = "  " * (depth + 1)
    log(f"{indent}Consolidating group '{group_label}' ({len(partials)} reports)...")

    all_json = json.dumps(partials, ensure_ascii=False, indent=2)
    if len(all_json) < 50000:
        msg = f"Partial reports to consolidate (group: {group_label}, {len(partials)} batches):\n\n{all_json}"
        stop_spinner = threading.Event()
        spinner_thread = threading.Thread(
            target=spinner_while_waiting,
            args=(stop_spinner, f"Consolidating {group_label}")
        )
        spinner_thread.start()
        try:
            result, _ = run_ollama(CONSOLIDATE_PROMPT, msg, model, num_predict=4096)
        finally:
            stop_spinner.set()
            spinner_thread.join()
        review = extract_json(result)
        if "error" not in review:
            log(f"{indent}  Model consolidation successful")
            return review

    log(f"{indent}  Model consolidation failed, using programmatic flatten")
    return _flatten_merge(partials)


def main():
    diff = os.environ.get("PR_DIFF", "")
    metadata_str = os.environ.get("PR_METADATA", "")
    model = os.environ.get("PR_MODEL", DEFAULT_MODEL)
    batch_only_raw = os.environ.get("PR_BATCH_ONLY", "")
    consolidate_dir_raw = os.environ.get("PR_CONSOLIDATE_DIR", "")

    if not diff:
        diff_file = os.environ.get("PR_DIFF_FILE", "")
        if diff_file and os.path.exists(diff_file):
            with open(diff_file, "r", encoding="utf-8") as f:
                diff = f.read()
        if not diff:
            result = {"status": "error", "message": "No diff found. Define PR_DIFF or PR_DIFF_FILE."}
            print(json.dumps(result))
            sys.exit(1)

    metadata = {}
    if metadata_str:
        try:
            metadata = json.loads(metadata_str)
        except json.JSONDecodeError:
            log(" WARN: PR_METADATA is not valid JSON, ignoring")

    batches = split_diff_into_batches(diff)
    total = len(batches)

    # ── Info mode: return batch list only ─────────────────
    if batch_only_raw == "info":
        info = {"status": "ok", "total_batches": total, "batches": []}
        for i, b in enumerate(batches, 1):
            info["batches"].append({"index": i, "label": b["label"], "size": len(b["content"])})
        print(json.dumps(info, ensure_ascii=False, indent=2))
        sys.exit(0)

    # ── Consolidation mode: merge partials from /tmp ──────────
    if consolidate_dir_raw:
        import glob as _glob
        partial_paths = sorted(_glob.glob(os.path.join(consolidate_dir_raw, "review_partial_*.json")))
        partials = []
        for pp in partial_paths:
            with open(pp, "r", encoding="utf-8") as f:
                partials.append(json.load(f))
        if not partials:
            result = {"status": "error", "message": "No partials found in " + consolidate_dir_raw}
            print(json.dumps(result))
            sys.exit(1)
        save_progress("consolidate", total_batches=len(partials), completed_batches=0)
        log(f" Consolidating {len(partials)} partials (hierarchical, groups of {CONSOLIDATION_GROUP_SIZE})")
        level = 0
        current_level = partials
        while len(current_level) > 1:
            level += 1
            groups = list(_grouped(current_level, CONSOLIDATION_GROUP_SIZE))
            next_level = []
            for gi, group in enumerate(groups, 1):
                label = f"level{level}_group{gi}"
                consolidated = _consolidate_group(group, label, model, depth=level)
                next_level.append(consolidated)
            current_level = next_level
        review = current_level[0]
        review["status"] = "ok"
        review["model"] = model
        review["batches_processed"] = len(partials)
        review["diff_size"] = len(diff)
        save_progress("done", total_batches=len(partials), completed_batches=len(partials), status="done")
        print(json.dumps(review, ensure_ascii=False, indent=2))
        sys.exit(0)

    # ── Single batch mode ─────────────────────────────────────
    if batch_only_raw:
        bi = int(batch_only_raw)
        if bi < 1 or bi > total:
            result = {"status": "error", "message": f"Batch {bi} out of range 1..{total}"}
            print(json.dumps(result))
            sys.exit(1)
        batch = batches[bi - 1]
        log(f" Batch {bi}/{total}: {batch['label'][:80]}...")

        user_msg = f"## PR Diff (batch {bi}/{total})\nFiles: {batch['label']}\n\n{batch['content']}"
        if metadata:
            user_msg = f"## PR Metadata\n{json.dumps(metadata, indent=2)}\n\n{user_msg}"

        stop_spinner = threading.Event()
        spinner_thread = threading.Thread(
            target=spinner_while_waiting,
            args=(stop_spinner, f"Reviewing batch {bi}/{total}")
        )
        spinner_thread.start()
        try:
            result, usage = run_ollama(SYSTEM_PROMPT, user_msg, model, num_predict=4096)
        finally:
            stop_spinner.set()
            spinner_thread.join()

        review = extract_json(result)
        if "error" in review:
            print(json.dumps({"status": "error", "message": review.get("error", str(review))}))
            sys.exit(1)
        review["status"] = "ok"
        review["_batch"] = bi
        review["_batches_total"] = total
        review["_files"] = batch["label"]
        review["_model"] = model
        review["_tokens"] = {
            "prompt_eval_count": usage.get("prompt_eval_count", 0),
            "eval_count": usage.get("eval_count", 0),
        }
        print(json.dumps(review, ensure_ascii=False, indent=2))
        sys.exit(0)

    # ── Full mode ──────────────────────────────────────────
    log(f" Model: {model}")
    log(f" Diff: {len(diff)} chars")
    log(f" Metadata: {'present' if metadata else 'absent'}")
    log(f" Batches: {total}")

    if total == 1:
        log(" Mode: single batch")
        user_msg = f"## PR Diff\n\n{batches[0]['content']}"
        if metadata:
            user_msg = f"## PR Metadata\n{json.dumps(metadata, indent=2)}\n\n{user_msg}"

        save_progress("batches", total_batches=1, completed_batches=0)
        log(" Sending to model...")
        stop_spinner = threading.Event()
        spinner_thread = threading.Thread(
            target=spinner_while_waiting,
            args=(stop_spinner, "Reviewing PR")
        )
        spinner_thread.start()
        try:
            result, usage = run_ollama(SYSTEM_PROMPT, user_msg, model, num_predict=4096)
        finally:
            stop_spinner.set()
            spinner_thread.join()
        review = extract_json(result)
        review["_tokens"] = {
            "prompt_eval_count": usage.get("prompt_eval_count", 0),
            "eval_count": usage.get("eval_count", 0),
        }
    else:
        save_progress("batches", total_batches=total, completed_batches=0)
        log(f" Mode: {total} batches — phase 1: process individually")
        partials = []

        for i, batch in enumerate(batches, 1):
            files_count = len(batch['label'].split(', '))
            log(f"  Batch {i}/{total}: {batch['label'][:80]}... ({files_count} files)")

            user_msg = f"## PR Diff (batch {i}/{total})\nFiles: {batch['label']}\n\n{batch['content']}"
            if metadata and i == 1:
                user_msg = f"## PR Metadata\n{json.dumps(metadata, indent=2)}\n\n{user_msg}"

            stop_spinner = threading.Event()
            spinner_thread = threading.Thread(
                target=spinner_while_waiting,
                args=(stop_spinner, f"Reviewing batch {i}/{total}")
            )
            spinner_thread.start()
            try:
                result, usage = run_ollama(SYSTEM_PROMPT, user_msg, model, num_predict=4096)
            finally:
                stop_spinner.set()
                spinner_thread.join()

            review = extract_json(result)
            review["_batch"] = i
            review["_files"] = batch["label"]
            review["_tokens"] = {
                "prompt_eval_count": usage.get("prompt_eval_count", 0),
                "eval_count": usage.get("eval_count", 0),
            }
            partials.append(review)

            partial_path = f"/tmp/opencode/review_partial_{i}.json"
            with open(partial_path, "w", encoding="utf-8") as f:
                json.dump(review, f, ensure_ascii=False)

            save_progress("batches", total_batches=total, completed_batches=i)

        save_progress("consolidate", total_batches=total, completed_batches=total)
        log(f" Phase 2: hierarchical consolidation ({len(partials)} reports, groups of {CONSOLIDATION_GROUP_SIZE})")
        level = 0
        current_level = partials

        while len(current_level) > 1:
            level += 1
            groups = list(_grouped(current_level, CONSOLIDATION_GROUP_SIZE))
            log(f"  Level {level}: {len(groups)} groups of ~{CONSOLIDATION_GROUP_SIZE}")

            next_level = []
            for gi, group in enumerate(groups, 1):
                label = f"level{level}_group{gi}"
                consolidated = _consolidate_group(group, label, model, depth=level)
                consolidated["_level"] = level
                consolidated["_group"] = gi
                next_level.append(consolidated)

            current_level = next_level

        review = current_level[0]

    if "error" in review:
        save_progress("done", total_batches=total, completed_batches=total, status="failed")
        print(json.dumps({"status": "error", "message": review.get("error", str(review))}))
        sys.exit(1)

    review["status"] = "ok"
    review["model"] = model
    review["batches_processed"] = len(batches)
    review["diff_size"] = len(diff)
    save_progress("done", total_batches=total, completed_batches=total, status="done")
    print(json.dumps(review, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
