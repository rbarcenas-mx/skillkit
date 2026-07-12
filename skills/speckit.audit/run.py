#!/usr/bin/env python3
"""
Post-Spec Audit — Motor de auditoria atomica spec-kit.

Cada invocacion audita UNA etapa o UN batch de codigo.
Para codigo, primero se prepara un manifiesto (audit/batches/manifest.json)
con todos los lotes. Las llamadas posteriores solo leen el manifiesto.

Variables de entorno:
  AUDIT_WORKDIR        directorio raiz del proyecto (obligatorio)
  AUDIT_FEATURE        feature a auditar (obligatorio)
  AUDIT_STAGE          etapa: spec|plan|tasks|codigo (obligatorio)
  AUDIT_BATCH          indice de batch para codigo (0-based, defecto 0)
  AUDIT_MODEL          override del modelo (opcional)
  AUDIT_PREPARE_ONLY   "true" = solo prepara manifiesto, no audita

Output: JSON en stdout.
"""

import json
import os
import re
import subprocess
import sys
import threading
import time

sys.stderr.reconfigure(line_buffering=True)
from datetime import datetime

sys.path.insert(0, os.environ["SKILLKIT_HOME"])
from lib import resolve_model

NUM_PREDICT = {'spec': 2048, 'plan': 2048, 'tasks': 2048, 'codigo': 2048}

# ── Model banner ─────────────────────────────────────────────
def print_model_banner(stage, tarea_desc):
    modo_raw = os.environ.get("SKILLKIT_MODE", "?")
    modo_label = {"low": "Low", "medium": "Medium", "high": "High"}.get(modo_raw, modo_raw)
    modo_explicacion = {
        "low": "modelos locales via Ollama (sin costo, mayor latencia)",
        "medium": "modelos remotos calidad/costo optimo (DeepSeek/OpenCode)",
        "high": "modelos remotos economicos (costo minimo)",
    }.get(modo_raw, modo_raw)
    modelo = os.environ.get("SKILLKIT_MODEL", "?")
    provider = os.environ.get("SKILLKIT_PROVIDER", "?")
    sys.stderr.write(f"\n{'='*54}\n")
    sys.stderr.write(f"  \U0001f9e0 Model Router\n")
    sys.stderr.write(f"{'─'*54}\n")
    sys.stderr.write(f"  Modo:     {modo_label} — {modo_explicacion}\n")
    sys.stderr.write(f"  Modelo:   {modelo} ({provider})\n")
    sys.stderr.write(f"  Motivo:   {tarea_desc}\n")
    sys.stderr.write(f"  Etapa:    {stage}\n")
    sys.stderr.write(f"{'='*54}\n\n")
    sys.stderr.flush()

# ── Spinner ─────────────────────────────────────────────────
def spinner_while_waiting(stop_event, label="Procesando"):
    frames = ['\u280b', '\u2819', '\u2839', '\u2838', '\u283c', '\u2834', '\u2826', '\u2827', '\u2807', '\u280f']
    i = 0
    t0 = time.time()
    while not stop_event.is_set():
        elapsed = time.time() - t0
        sys.stderr.write(f'\r  {frames[i % len(frames)]} {label} ({elapsed:.0f}s)   ')
        sys.stderr.flush()
        i += 1
        time.sleep(0.15)
    elapsed = time.time() - t0
    sys.stderr.write(f'\r  \u2705 {label} \u2014 completado en {elapsed:.1f}s   \n')
    sys.stderr.flush()


def get_api_url() -> str:
    return os.environ.get("SKILLKIT_API_URL", "http://localhost:11434/v1")


def get_api_key() -> str:
    return os.environ.get("SKILLKIT_API_KEY", "")


# =============================================================================
# UTILIDADES
# =============================================================================

LOG_BUF = []
def log(msg: str) -> None:
    LOG_BUF.append(msg)
    print(msg, file=sys.stderr, flush=True)


def verify_ollama(required_models: list) -> dict:
    try:
        r = subprocess.run(["curl", "-s", "http://localhost:11434/api/tags"],
                           capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return {"ok": False, "error": "Ollama no responde. Ejecuta: ollama serve"}
        data = json.loads(r.stdout)
        available = [m['name'] for m in data.get('models', [])]
        missing = [m for m in required_models if not any(m in a for a in available)]
        return {"ok": len(missing) == 0, "missing": missing, "available": available}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def read_file(path: str) -> str:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return ""


def write_file(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def now_iso() -> str:
    return datetime.now().strftime('%Y-%m-%dT%H:%M:%S')


def now_compact() -> str:
    return datetime.now().strftime('%Y%m%d-%H%M')


def next_audit_id(audit_dir: str) -> int:
    """Calcula el proximo ID incremental basado en archivos *-audit.md existentes."""
    max_id = 0
    if not os.path.isdir(audit_dir):
        return 1
    for f in os.listdir(audit_dir):
        m = re.match(r'(\d+)-.*-audit\.md', f)
        if m:
            max_id = max(max_id, int(m.group(1)))
    return max_id + 1


def save_session(workdir: str, feature: str, stages: list[dict]) -> str:
    """Genera el archivo de sesion con formato {id}-{fecha}-{hora}-audit.md."""
    audit_dir = os.path.join(workdir, 'audit')
    os.makedirs(audit_dir, exist_ok=True)

    audit_id = next_audit_id(audit_dir)
    compact = now_compact()
    filename = f'{audit_id:03d}-{compact}-audit.md'
    path = os.path.join(audit_dir, filename)

    total_criticals = sum(s.get('criticals', 0) for s in stages)
    total_warnings = sum(s.get('warnings', 0) for s in stages)
    total_obs = sum(s.get('observations', 0) for s in stages)

    # Determinar estado global
    if total_criticals > 0:
        global_status = "APROBADO CON OBSERVACIONES"
    else:
        global_status = "APROBADO"

    lines = [
        f"# Auditoria: {feature}",
        f"**ID**: {audit_id:03d}",
        f"**Fecha**: {compact}",
        f"**Feature**: {feature}",
        f"**Estado**: {global_status}",
        "",
        "## Resumen por etapa",
        "",
        "| Etapa | Veredicto | Criticos | Advertencias | Obs. |",
        "|---|---|---|---|---|",
    ]
    for s in stages:
        lines.append(
            f"| {s['stage']} | {s['veredicto']} | {s['criticals']} | {s['warnings']} | {s['observations']} |"
        )
    lines.append(
        f"| **Total** | | **{total_criticals}** | **{total_warnings}** | **{total_obs}** |"
    )
    lines.append("")

    write_file(path, '\n'.join(lines))
    log(f"Sesion guardada: {path} (ID {audit_id:03d})")
    return path


def extract_verdict(report: str) -> str:
    if not report:
        return "DESCONOCIDO"
    for p in [r'REQUIERE\s+CAMBIOS', r'APROBADO\s+CON\s+OBSERVACIONES', r'APROBADO']:
        m = re.search(p, report)
        if m:
            return m.group(0).strip()
    return "DESCONOCIDO"


def extract_findings(report: str) -> tuple:
    if not report:
        return 0, 0, 0
    return (len(re.findall(r'\*\*ID\*\*:\s*C\d+', report)),
            len(re.findall(r'\*\*ID\*\*:\s*W\d+', report)),
            len(re.findall(r'\*\*ID\*\*:\s*O\d+', report)))


# =============================================================================
# OLLAMA
# =============================================================================

def run_ollama(system_prompt: str, user_msg: str, model: str,
               num_predict: int = 2048, timeout: int = 600,
               label: str = "Auditando") -> str:
    # Usar SKILLKIT_MODEL si esta disponible
    api_model = os.environ.get("SKILLKIT_MODEL", model)
    payload = {
        "model": api_model, "stream": False,
        "options": {"num_predict": num_predict},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
    }
    prompt_chars = len(user_msg) + len(system_prompt)
    log(f"  ▶ Payload: {prompt_chars:,} chars, modelo={api_model}")

    pfile = '/tmp/skillkit/payload_audit.json'
    os.makedirs('/tmp/skillkit', exist_ok=True)
    with open(pfile, 'w') as f:
        json.dump(payload, f, ensure_ascii=False)

    stop_spinner = threading.Event()
    spinner_thread = threading.Thread(
        target=spinner_while_waiting,
        args=(stop_spinner, f"Auditando {label}")
    )
    spinner_thread.start()
    try:
        api_url = get_api_url()
        api_key = get_api_key()
        headers = ["-H", "Content-Type: application/json"]
        if api_key:
            headers += ["-H", f"Authorization: Bearer {api_key}"]
        url = api_url.rstrip('/')
        if not url.endswith('/chat/completions'):
            url += '/chat/completions'
        r = subprocess.run(
            ["curl", "-s", "-X", "POST", url,
             *headers, "-d", "@" + pfile],
            capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        stop_spinner.set()
        spinner_thread.join()
        return "ERROR: timeout"
    except Exception as e:
        stop_spinner.set()
        spinner_thread.join()
        return f"ERROR: {e}"
    finally:
        stop_spinner.set()
        spinner_thread.join()

    if r.returncode != 0:
        log(f"  ❌ curl error: {r.stderr[:200]}")
        return f"ERROR curl: {r.stderr}"
    if not r.stdout.strip():
        log("  ❌ Respuesta vacia del modelo")
        return "ERROR: respuesta vacia"

    resp = json.loads(r.stdout)
    choices = resp.get("choices", [])
    content = choices[0]["message"]["content"] if choices else resp.get("message", {}).get("content", "")
    result_text = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
    log(f"  ▶ Respuesta: {len(result_text):,} chars")
    return result_text


# =============================================================================
# SYSTEM PROMPTS
# =============================================================================

SYS_SPEC = """Eres un auditor senior de producto. Revisa la especificacion.

Responde EXACTAMENTE:
# Reporte de Auditoria — Especificacion

## Resumen Ejecutivo

## Hallazgos Criticos
**ID**: C1, **Descripcion**: ..., **Seccion afectada**: ..., **Accion requerida**: ...

## Advertencias
**ID**: W1, **Descripcion**: ..., **Accion sugerida**: ...

## Observaciones
**ID**: O1, **Descripcion**: ..., **Beneficio**: ...

## Veredicto
APROBADO | APROBADO CON OBSERVACIONES | REQUIERE CAMBIOS

## Decisiones Pendientes

Responde solo en espanol."""

SYS_PLAN = """Eres un auditor senior de arquitectura. Revisa el plan tecnico.

Responde EXACTAMENTE:
# Reporte de Auditoria — Plan Tecnico

## Resumen Ejecutivo

## Hallazgos Criticos
**ID**: C1, **Descripcion**: ..., **Artefacto**: ..., **Accion requerida**: ...

## Advertencias
**ID**: W1, **Descripcion**: ..., **Accion sugerida**: ...

## Observaciones

## Veredicto
APROBADO | APROBADO CON OBSERVACIONES | REQUIERE CAMBIOS

## Decisiones Pendientes
Responde solo en espanol."""

SYS_TASKS = """Eres un auditor senior de ingenieria. Revisa las tareas.

Responde EXACTAMENTE:
# Reporte de Auditoria — Tareas

## Resumen Ejecutivo

## Hallazgos Criticos
**ID**: C1, **Descripcion**: ..., **Tarea afectada**: ..., **Accion requerida**: ...

## Advertencias

## Observaciones

## Veredicto
APROBADO | APROBADO CON OBSERVACIONES | REQUIERE CAMBIOS

## Decisiones Pendientes
Responde solo en espanol."""

SYS_LINT = """Eres un auditor senior de calidad de codigo. Revisa la salida de herramientas de linting (ESLint, tsc --noEmit, Prettier) y clasifica los hallazgos.

Responde EXACTAMENTE:
# Reporte de Auditoria — Lint/TypeCheck

## Resumen Ejecutivo

## Hallazgos Criticos
**ID**: C1, **Descripcion**: ..., **Archivo:linea**: ..., **Accion requerida**: ...

## Advertencias
**ID**: W1, **Descripcion**: ..., **Accion sugerida**: ...

## Observaciones

## Veredicto
APROBADO | APROBADO CON OBSERVACIONES | REQUIERE CAMBIOS

Responde solo en espanol."""

SYS_CODIGO = """Eres un auditor senior de ingenieria. Verifica que el codigo sea coherente con la especificacion, plan y tareas.

Responde EXACTAMENTE:
# Reporte de Auditoria — Codigo

## Resumen Ejecutivo

## Hallazgos Criticos
**ID**: C1, **Descripcion**: ..., **Archivo:linea**: ..., **Accion requerida**: ...

## Advertencias

## Observaciones

## Veredicto
APROBADO | APROBADO CON OBSERVACIONES | REQUIERE CAMBIOS

## Cobertura de Requisitos
Tabla FR -> estado.

## Decisiones Pendientes
Responde solo en espanol."""

SYSTEM_PROMPTS = {
    'spec': SYS_SPEC, 'plan': SYS_PLAN, 'tasks': SYS_TASKS, 'codigo': SYS_CODIGO,
    'lint': SYS_LINT,
}


# =============================================================================
# MANIFIESTO DE CODIGO
# =============================================================================

def prepare_manifest(workdir: str) -> dict:
    """Escanea el proyecto y genera manifest.json con todos los batches."""
    layer_dirs = {
        'models': ['prisma/', 'src/models/'],
        'services': ['src/services/'],
        'controllers': ['src/controllers/'],
        'middleware': ['src/middleware/'],
        'repositories': ['src/repositories/'],
        'routes': ['src/routes/'],
        'config': ['src/config/'],
        'utils': ['src/utils/'],
        'tests': ['tests/', 'test/', '__tests__/'],
    }
    extensions = ('.ts', '.tsx', '.js', '.jsx', '.py')
    skip_dirs = {'node_modules', '.git', 'dist', 'build', '.specify',
                 '.opencode', 'audit', 'coverage', '.next', '.cache', 'tmp'}

    layer_files = {l: [] for l in layer_dirs}
    layer_files['other'] = []

    for root, dirs, files in os.walk(workdir):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for f in files:
            if not f.endswith(extensions):
                continue
            rel = os.path.relpath(os.path.join(root, f), workdir)
            matched = False
            for layer, dirs_list in layer_dirs.items():
                for d in dirs_list:
                    if rel.startswith(d):
                        layer_files[layer].append(rel)
                        matched = True
                        break
                if matched:
                    break
            if not matched:
                layer_files['other'].append(rel)

    layer_order = ['models', 'services', 'controllers', 'middleware',
                   'repositories', 'routes', 'config', 'utils', 'tests', 'other']
    batches = []
    for layer in layer_order:
        files = layer_files.get(layer, [])
        if files:
            batches.append({'layer': layer, 'files': sorted(files)})

    manifest = {
        'total_batches': len(batches),
        'batches': batches,
        'prepared_at': now_iso(),
    }
    manif_path = os.path.join(workdir, 'audit', 'batches', 'manifest.json')
    write_file(manif_path, json.dumps(manifest, ensure_ascii=False, indent=2))
    log(f"Manifiesto generado: {manif_path} ({len(batches)} batches)")
    return manifest


def read_manifest(workdir: str) -> dict:
    path = os.path.join(workdir, 'audit', 'batches', 'manifest.json')
    content = read_file(path)
    if not content:
        return None
    return json.loads(content)


def load_batch_content(workdir: str, files: list) -> str:
    parts = []
    for fpath in files:
        fc = read_file(os.path.join(workdir, fpath))
        if fc:
            parts.append(f"--- {fpath} ---\n{fc}")
    return '\n\n'.join(parts)


# =============================================================================
# AUDITORIA
# =============================================================================

def audit_stage_full(workdir: str, feature: str, stage: str, model: str) -> dict:
    base = os.path.join(workdir, 'specs', feature)
    parts = [f"=== FEATURE ===\n{feature}\n=== ETAPA ===\n{stage}"]

    const = read_file(os.path.join(workdir, '.specify', 'memory', 'constitution.md'))
    if const:
        parts.append(f"=== CONSTITUCION ===\n{const}")
        log(f"  ▶ Constitucion: {len(const):,} chars")

    for art in {'spec': ['spec.md'], 'plan': ['spec.md', 'plan.md', 'data-model.md', 'contracts/api.md'],
                'tasks': ['spec.md', 'plan.md', 'tasks.md']}.get(stage, []):
        content = read_file(os.path.join(base, art))
        if content:
            log(f"  ▶ {art}: {len(content):,} chars")
            parts.append(f"=== {art.upper()} ===\n{content}")

    context = '\n\n'.join(parts)
    log(f"  ▶ Contexto total: {len(context):,} chars — enviando a auditar...")
    report = run_ollama(SYSTEM_PROMPTS[stage], f"## Artefactos\n\n{context}",
                        model, NUM_PREDICT.get(stage, 2048), label=stage)
    v = extract_verdict(report)
    c, w, o = extract_findings(report)
    return {'veredicto': v, 'report': report, 'criticals': c, 'warnings': w, 'observations': o,
            'model': model, 'num_predict': NUM_PREDICT.get(stage, 2048)}


def audit_codigo_batch(workdir: str, feature: str, batch_idx: int, model: str,
                       manifest: dict) -> dict:
    if batch_idx < 0 or batch_idx >= manifest['total_batches']:
        return {'veredicto': 'ERROR', 'report': f'Batch #{batch_idx} fuera de rango (0-{manifest["total_batches"]-1})',
                'criticals': 0, 'warnings': 0, 'observations': 0,
                'model': model, 'num_predict': 0, 'batch': None}

    batch_info = manifest['batches'][batch_idx]
    log(f"  ▶ Capa: {batch_info['layer']} — {len(batch_info['files'])} archivos, {sum(read_file(os.path.join(workdir, f)).count(chr(10)) for f in batch_info['files'] if read_file(os.path.join(workdir, f))):,} lineas")
    code_content = load_batch_content(workdir, batch_info['files'])

    # Contexto fijo minimo: solo requisitos funcionales
    base = os.path.join(workdir, 'specs', feature)
    ctx_parts = []
    spec = read_file(os.path.join(base, 'spec.md'))
    if spec:
        import re
        fr_m = re.search(r'(?:### Requisitos Funcionales|### Historias de Usuario)(.*?)(?=### |\Z)', spec, re.DOTALL)
        if fr_m:
            ctx_parts.append(f"=== REQUISITOS FUNCIONALES ===\n{fr_m.group(0).strip()}")

    system = SYSTEM_PROMPTS['codigo']
    if ctx_parts:
        system = f"{system}\n\n## Contexto del Proyecto\n{''.join(ctx_parts)}"

    user_msg = f"Capa: {batch_info['layer']}\nBatch: {batch_idx + 1}/{manifest['total_batches']}\n\n{code_content}"
    report = run_ollama(system, user_msg, model, NUM_PREDICT.get('codigo', 1024),
                        label=f"codigo/{batch_info['layer']}")
    v = extract_verdict(report)
    c, w, o = extract_findings(report)

    return {
        'veredicto': v, 'report': report,
        'criticals': c, 'warnings': w, 'observations': o,
        'model': model, 'num_predict': NUM_PREDICT.get('codigo', 3072),
        'batch': {
            'layer': batch_info['layer'],
            'index': batch_idx,
            'total': manifest['total_batches'],
            'files': batch_info['files'],
        },
    }


def audit_lint(workdir: str, feature: str, model: str) -> dict:
    """Ejecuta lint y typecheck, envia salida al modelo para analisis."""
    # Ejecutar npm run lint
    lint_output = ""
    try:
        r = subprocess.run(
            ["npm", "run", "lint"],
            capture_output=True, text=True, timeout=120,
            cwd=workdir,
        )
        lint_output = r.stdout + r.stderr
        if r.returncode != 0:
            lint_output += f"\nExit code: {r.returncode}"
    except Exception as e:
        lint_output = f"ERROR al ejecutar lint: {e}"

    # Ejecutar npx tsc --noEmit
    tsc_output = ""
    try:
        r = subprocess.run(
            ["npx", "tsc", "--noEmit"],
            capture_output=True, text=True, timeout=120,
            cwd=workdir,
        )
        tsc_output = r.stdout + r.stderr
        if r.returncode != 0:
            tsc_output += f"\nExit code: {r.returncode}"
    except Exception as e:
        tsc_output = f"ERROR al ejecutar tsc: {e}"

    log(f"  ▶ Lint: {len(lint_output):,} chars | TSC: {len(tsc_output):,} chars — enviando a auditar...")
    context = (
        f"=== FEATURE ===\n{feature}\n=== ETAPA ===\nlint\n\n"
        f"=== LINT OUTPUT ===\n{lint_output}\n\n"
        f"=== TSC OUTPUT ===\n{tsc_output}"
    )

    report = run_ollama(SYS_LINT, context, model, 2048, label="lint")
    v = extract_verdict(report)
    c, w, o = extract_findings(report)

    return {
        'veredicto': v, 'report': report,
        'criticals': c, 'warnings': w, 'observations': o,
        'model': model, 'num_predict': 2048,
    }


def save_checkpoint(workdir: str, feature: str, stage: str, result: dict) -> str:
    cp_dir = os.path.join(workdir, 'audit', 'checkpoints')
    os.makedirs(cp_dir, exist_ok=True)
    b = result.get('batch')
    if b:
        fname = f"{feature}_{stage}_{b['layer']}_cp.md"
        title = f"{stage}/{b['layer']} ({b['index']+1}/{b['total']})"
    else:
        fname = f"{feature}_{stage}_cp.md"
        title = stage
    lines = [
        f"# Checkpoint: {title}",
        f"**Fecha**: {now_iso()}",
        f"**Veredicto**: {result.get('veredicto', '?')}",
        f"**Criticos**: {result.get('criticals', 0)}",
        f"**Advertencias**: {result.get('warnings', 0)}",
        f"**Observaciones**: {result.get('observations', 0)}",
        "", "### Reporte", result.get('report', ''),
    ]
    p = os.path.join(cp_dir, fname)
    write_file(p, '\n'.join(lines))
    return p


# =============================================================================
# MAIN
# =============================================================================

def _get_tarea_desc(skill_name: str) -> str:
    """Lee la descripcion de tarea desde skill_mapping en models.json."""
    try:
        config_home = os.environ["SKILLKIT_HOME"]
        with open(os.path.join(config_home, 'lib', 'models.json'), 'r', encoding='utf-8') as f:
            models_data = json.load(f)
        return models_data.get('skill_mapping', {}).get(skill_name, {}).get('tarea', 'Auditoria spec-kit')
    except Exception:
        return 'Auditoria spec-kit'

def main():
    workdir = os.environ.get('AUDIT_WORKDIR', os.getcwd())
    feature = os.environ.get('AUDIT_FEATURE', '')
    stage = os.environ.get('AUDIT_STAGE', '')
    batch_str = os.environ.get('AUDIT_BATCH', '0')
    prepare_only = os.environ.get('AUDIT_PREPARE_ONLY', '') == 'true'
    consolidate_input = os.environ.get('AUDIT_CONSOLIDATE', '')
    model_override = os.environ.get('AUDIT_MODEL', '')

    err = lambda msg: print(json.dumps({"status": "error", "message": msg}))

    # Modo consolidate: genera archivo de sesion a partir de checkpoints existentes
    if consolidate_input:
        stages = json.loads(consolidate_input)
        session_path = save_session(workdir, feature, stages)
        print(json.dumps({"status": "ok", "action": "consolidated",
                          "session_path": session_path}, ensure_ascii=False, indent=2))
        return

    if not feature:
        err("AUDIT_FEATURE es obligatorio"); sys.exit(1)
    if not stage:
        err("AUDIT_STAGE es obligatorio"); sys.exit(1)
    if stage not in ('spec', 'plan', 'tasks', 'codigo', 'lint'):
        err(f"Etapa invalida: {stage}"); sys.exit(1)

    mc = {"ok": True}
    if not mc['ok']:
        print(json.dumps({"status": "error", "code": "models_missing",
                          "missing": mc.get('missing', [])}))
        sys.exit(1)

    skill_name = "audit.codigo" if stage == 'codigo' else ("audit.lint" if stage == 'lint' else "audit.spec_plan_tasks")
    model = model_override or resolve_model(skill_name)

    stage_labels = {'spec': 'Especificacion', 'plan': 'Plan tecnico', 'tasks': 'Tareas', 'codigo': 'Codigo', 'lint': 'Lint y typecheck'}
    print_model_banner(stage_labels.get(stage, stage), _get_tarea_desc(skill_name))

    if stage == 'codigo':
        manifest = read_manifest(workdir)

        # Preparar manifiesto si no existe o si se pide explicitamente
        if not manifest or prepare_only:
            log("  ▶ Preparando manifiesto de archivos...")
            manifest = prepare_manifest(workdir)
            if prepare_only:
                print(json.dumps({"status": "ok", "action": "manifest_prepared",
                                  "total_batches": manifest['total_batches'],
                                  "batches": [{'index': i, 'layer': b['layer'], 'files': len(b['files'])}
                                              for i, b in enumerate(manifest['batches'])]},
                                 ensure_ascii=False, indent=2))
                return

        batch_idx = int(batch_str) if batch_str.isdigit() else 0
        log(f"  ▶ Auditando codigo — batch {batch_idx+1}/{manifest['total_batches']}")
        result = audit_codigo_batch(workdir, feature, batch_idx, model, manifest)
    elif stage == 'lint':
        log("  ▶ Auditando lint y typecheck...")
        result = audit_lint(workdir, feature, model)
    else:
        log(f"  ▶ Auditando {stage_labels.get(stage, stage)} — cargando artefactos...")
        result = audit_stage_full(workdir, feature, stage, model)

    # Resumen en stderr
    v = result.get('veredicto', '?')
    c = result.get('criticals', 0)
    w = result.get('warnings', 0)
    o = result.get('observations', 0)
    symbol = '\u2705' if v.startswith('APROBADO') else ('\u26a0\ufe0f' if 'OBSERVACIONES' in v else '\u274c')
    log(f"  {symbol} Veredicto: {v} | Criticos={c} | Advertencias={w} | Obs={o}")
    log("")

    cp_path = save_checkpoint(workdir, feature, stage, result)
    log(f"Checkpoint: {cp_path}")

    output = {
        "status": "ok",
        "feature": feature,
        "stage": stage,
        "batch": result.get('batch'),
        "result": {
            "veredicto": result['veredicto'],
            "criticals": result['criticals'],
            "warnings": result['warnings'],
            "observations": result['observations'],
            "report": result['report'],
        },
        "checkpoint": cp_path,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
