#!/usr/bin/env python3
"""
ci.prepare — Generate CI integration plan. Model resolved via resolve_model("ci.prepare").

Receives repository diagnostics via JSON file and delegates analysis
(file classification, commit strategy) to the local model.

Input:  /tmp/skillkit/ci_diagnostics.json
Output: JSON on stdout with classification + commit_strategy
"""

import json
import os
import re
import subprocess
import sys
import threading
import time

sys.stderr.reconfigure(line_buffering=True)

sys.path.insert(0, os.environ["SKILLKIT_HOME"])
from lib import resolve_model

TIMEOUT = 600
PROGRESS_FILE = "/tmp/skillkit/ci_prepare_progress.json"


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


def save_progress(phase: str, status: str = "running") -> None:
    os.makedirs(os.path.dirname(PROGRESS_FILE), exist_ok=True)
    from datetime import datetime, timezone
    progress = {
        "phase": phase,
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False)


def run_model(system_prompt: str, user_msg: str, skill_name: str,
              num_predict: int = 4096) -> tuple:
    resolve_model(skill_name)
    api_model = os.environ.get("SKILLKIT_MODEL", "")

    payload = {
        "model": api_model, "stream": False,
        "options": {"num_predict": num_predict},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
    }
    pfile = '/tmp/skillkit/ci_prepare_payload.json'
    os.makedirs('/tmp/skillkit', exist_ok=True)
    with open(pfile, 'w') as f:
        json.dump(payload, f, ensure_ascii=False)

    api_url = os.environ.get("SKILLKIT_API_URL", "http://localhost:11434/v1")
    api_key = os.environ.get("SKILLKIT_API_KEY", "")
    headers = ["-H", "Content-Type: application/json"]
    if api_key:
        headers += ["-H", f"Authorization: Bearer {api_key}"]
    url = api_url.rstrip('/')
    if not url.endswith('/chat/completions'):
        url += '/chat/completions'

    try:
        r = subprocess.run(
            ["curl", "-s", "-X", "POST", url,
             *headers, "-d", "@" + pfile],
            capture_output=True, text=True, timeout=TIMEOUT)
        if r.returncode != 0:
            return f"ERROR curl: {r.stderr}", {}
        if not r.stdout.strip():
            return "ERROR: empty response", {}

        resp = json.loads(r.stdout)
        if "error" in resp:
            return f"ERROR API: {resp['error']}", {}

        usage = resp.get("usage", {})
        choices = resp.get("choices", [])
        if choices:
            content = choices[0]["message"]["content"]
        else:
            content = resp.get("message", {}).get("content", "")
        return re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip(), usage
    except subprocess.TimeoutExpired:
        return "ERROR: timeout", {}
    except Exception as e:
        return f"ERROR: {e}", {}


def extract_json_from_response(text: str) -> dict:
    m = re.search(r"```json\s*\n(.*?)\n```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    m = re.search(r"```\s*\n(.*?)\n```", text, re.DOTALL)
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
    return {"error": "Could not extract JSON from response", "raw": text[:500]}


# ──────────────────────────────────────────────
# System prompt (Spanish — output is Spanish)
# ──────────────────────────────────────────────

SYSTEM_PROMPT = """Eres un ingeniero DevOps senior. Tu tarea es analizar el estado de un repositorio de software y generar un plan de integracion a GitHub con commits atomicos siguiendo Conventional Commits.

## Reglas de clasificacion de archivos

### INCLUIR (deben versionarse)
- Codigo fuente (.ts, .tsx, .js, .jsx, .py, .java, .go, .rs, etc.)
- Configuracion del proyecto (package.json, tsconfig.json, .eslintrc.*, .prettierrc, jest.config.*, etc.)
- Archivos de dependencias (package-lock.json, yarn.lock, Cargo.lock, etc.)
- Documentacion (README.md, AGENTS.md, docs/, specs/)
- Tests (tests/, __tests__/, *.test.*, *.spec.*)
- Schemas de base de datos (prisma/schema.prisma, migrations/)
- Configuracion de CI/CD (.github/workflows/, .gitlab-ci.yml)
- Configuracion de herramientas (.specify/, .opencode/, .vscode/settings.json)
- Archivos de entorno de ejemplo (.env.example, .env.template)
- .gitignore

### EXCLUIR (NO deben versionarse)
- Dependencias instaladas (node_modules/, vendor/, .venv/)
- Artefactos de build (dist/, build/, .next/, out/)
- Cobertura y reportes (coverage/, .nyc_output/)
- Secretos y credenciales (.env, .env.local, .env.production, *-secret*, *.pem, *.key)
- Archivos de sistema (.DS_Store, Thumbs.db)
- Logs (*.log, logs/)
- Directorios de cache (.cache/, .turbo/, __pycache__/, *.pyc)
- Archivos temporales (/tmp/*, *.tmp, *.swp, *~)
- Archivos binarios grandes sin justificacion (*.zip, *.tar.gz, *.mp4, *.bin)

### DECIDIR (requiere decision del usuario)
- Archivos que no caen claramente en incluir/excluir
- Archivos de datos grandes que podrian ser necesarios (seed data, fixtures)
- Archivos de configuracion local que podrian ser utiles para otros (.vscode/launch.json)
- Archivos de analisis o auditoria (audit.md, idea.txt, payload*.json)

## Reglas para commits atomicos

1. Cada commit representa una unidad logica independiente
2. Usar Conventional Commits: feat, fix, chore, docs, style, refactor, test, ci, build
3. Separar codigo fuente de configuracion
4. Mensajes descriptivos en espanol o ingles (segun el proyecto)
5. No agrupar archivos no relacionados en un mismo commit
6. Si el repo no existe, el primer commit debe ser el setup inicial
7. Si el repo ya existe, generar commits incrementales sobre lo modificado/no trackeado
8. Verificar que cada archivo existe realmente antes de incluirlo

Responde EXACTAMENTE con el siguiente JSON (sin texto adicional fuera del JSON):

```json
{
  "classification": {
    "include": [
      {"category": "Configuracion raiz", "files": ["package.json", "tsconfig.json", "..."], "justification": "Infraestructura del proyecto"},
      {"category": "Codigo fuente", "files": ["src/archivo1.ts", "..."], "justification": "Logica de negocio"}
    ],
    "exclude": [
      {"file": "node_modules/", "reason": "Dependencias — se instalan con npm install"},
      {"file": ".env", "reason": "Secretos — debe estar en .gitignore"}
    ],
    "decide": [
      {"file": "audit.md", "reason": "Historial de auditorias — versionar o mantener solo local?"}
    ],
    "gitignore_missing": [".env", ".env.local"],
    "secrets_detected": [".env.siin secreto detectado"],
    "summary": "Resumen ejecutivo de 2-3 frases del estado del repositorio"
  },
  "commit_strategy": [
    {
      "id": 1,
      "type": "chore",
      "scope": "",
      "description": "initial project setup",
      "files": ["package.json", "package-lock.json", "tsconfig.json", ".gitignore", ".env.example"],
      "message": "chore: initial project setup",
      "command": "git add package.json package-lock.json tsconfig.json .gitignore .env.example",
      "needs_init": false,
      "checkpoint": true
    }
  ],
  "dangerous_commits": [1],
  "total_commits": 6
}
```

Responde unicamente en espanol para los campos de texto libre (justification, reason, summary, description). Los mensajes de commit pueden estar en ingles si el proyecto ya usa ese idioma."""


def main():
    diag_path = os.environ.get("CI_DIAGNOSTICS_FILE", "/tmp/skillkit/ci_diagnostics.json")
    try:
        with open(diag_path, "r", encoding="utf-8") as f:
            diagnostics = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        result = {"status": "error", "error": f"Could not read diagnostics: {e}"}
        print(json.dumps(result))
        sys.exit(1)

    log(f" Diagnostics loaded: {len(json.dumps(diagnostics))} chars")
    log(f" Repo exists: {diagnostics.get('repo_exists', False)}")
    log(f" Total files: {len(diagnostics.get('files_all', []))}")

    save_progress("analysis", "running")

    user_msg = json.dumps(diagnostics, ensure_ascii=False, indent=2)

    model_used = os.environ.get("SKILLKIT_MODEL", "default model")
    provider = os.environ.get("SKILLKIT_PROVIDER", "local")
    log(f" Using model: {model_used} ({provider})")

    stop_spinner = threading.Event()
    spinner_thread = threading.Thread(
        target=spinner_while_waiting,
        args=(stop_spinner, "Analyzing repository")
    )
    spinner_thread.start()
    try:
        result, usage = run_model(SYSTEM_PROMPT, user_msg, "ci.prepare", num_predict=4096)
    finally:
        stop_spinner.set()
        spinner_thread.join()

    log(f" Response received: {len(result)} chars")

    plan = extract_json_from_response(result)
    if "error" in plan:
        log(f" ERROR extracting JSON: {plan['error']}")
        save_progress("analysis", "failed")
        print(json.dumps(plan, ensure_ascii=False))
        sys.exit(1)

    plan["status"] = "ok"
    plan["_tokens"] = {
        "prompt_eval_count": usage.get("prompt_eval_count", 0),
        "eval_count": usage.get("eval_count", 0),
    }

    save_progress("done", "done")

    log(f" Classification: {len(plan.get('classification', {}).get('include', []))} included categories")
    log(f" Commits: {plan.get('total_commits', 0)} total")
    print(json.dumps(plan, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
