#!/usr/bin/env python3
"""
speckit.audit-resolve — Motor de resolucion de hallazgos post-auditoria.

Modos (via AUDIT_RESOLVE_MODE):
  diagnose  -> escanea checkpoints, genera audit/{id}-audit-resolve.md
  resolve   -> lee resolve.md, itera hallazgos con modelo segun tipo, checkpoint
  finalize  -> escribe **Solucion**: timestamp en resolve.md, touch

Variables de entorno:
  AUDIT_WORKDIR           directorio raiz del proyecto (obligatorio)
  AUDIT_RESOLVE_MODE      diagnose (defecto) | resolve | finalize
  AUDIT_RESOLVE_STAGE     etapa especifica a resolver (opcional)

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

LOG_BUF = []


def log(msg: str) -> None:
    LOG_BUF.append(msg)
    print(msg, file=sys.stderr, flush=True)

# ANSI colors
C = {
    'green': '\033[92m', 'red': '\033[91m', 'yellow': '\033[93m',
    'cyan': '\033[96m', 'blue': '\033[94m', 'bold': '\033[1m',
    'reset': '\033[0m', 'clear': '\033[K',
}

def print_model_banner(modo_label, modelo, proveedor, motivo, accion, action_type="solve"):
    action_label = {"suggest": "Sugiriendo soluciones", "solve": "Aplicando soluciones directamente"}.get(action_type, action_type)
    sys.stderr.write(f"\n{'='*54}\n")
    sys.stderr.write(f"  {C['bold']}\U0001f9e0 Model Router{C['reset']}\n")
    sys.stderr.write(f"{'─'*54}\n")
    sys.stderr.write(f"  Modo:     {modo_label}\n")
    sys.stderr.write(f"  Modelo:   {modelo} ({proveedor})\n")
    sys.stderr.write(f"  Motivo:   {motivo}\n")
    sys.stderr.write(f"  Accion:   {action_label}\n")
    sys.stderr.write(f"  Etapa:    {accion}\n")
    sys.stderr.write(f"{'='*54}\n\n")
    sys.stderr.flush()


def now_iso() -> str:
    return datetime.now().strftime('%Y-%m-%dT%H:%M:%S')


def now_compact() -> str:
    return datetime.now().strftime('%Y%m%d-%H%M')


def read_file(path: str) -> str:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return ""
    except Exception:
        return ""


def write_file(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


# =============================================================================
# PROGRESS BAR
# =============================================================================

def progress_bar(done: int, total: int, label: str = "") -> None:
    if total <= 0:
        return
    pct = int((done / total) * 100)
    filled = int(30 * done / total)
    bar_filled = '\u2588' * filled
    bar_empty = '\u2591' * (30 - filled)
    color = C['green'] if pct == 100 else (C['yellow'] if pct > 50 else C['cyan'])
    sys.stderr.write(f'\r{color}[{bar_filled}{bar_empty}]{C["reset"]} {C["bold"]}{pct}%{C["reset"]} ({done}/{total}) {label}{C["clear"]}')
    sys.stderr.flush()
    if done >= total:
        sys.stderr.write('\n')


# =============================================================================
# CHECKPOINT (reanudacion)
# =============================================================================

PROGRESS_PATH = '/tmp/opencode/audit_resolve_progress.json'


def save_progress(data: dict) -> None:
    data['timestamp'] = now_iso()
    os.makedirs('/tmp/opencode', exist_ok=True)
    with open(PROGRESS_PATH, 'w') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_progress() -> dict | None:
    try:
        with open(PROGRESS_PATH) as f:
            return json.load(f)
    except Exception:
        return None


# =============================================================================
# MODELO
# =============================================================================

def run_model(system_prompt: str, user_msg: str, skill_name: str,
              num_predict: int = 2048, timeout: int = 600) -> str:
    resolve_model(skill_name)
    api_model = os.environ.get("OPENCODE_MODEL", "")

    payload = {
        "model": api_model, "stream": False,
        "options": {"num_predict": num_predict},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
    }
    pfile = '/tmp/opencode/audit_resolve_payload.json'
    os.makedirs('/tmp/opencode', exist_ok=True)
    with open(pfile, 'w') as f:
        json.dump(payload, f, ensure_ascii=False)

    api_url = os.environ.get("OPENCODE_API_URL", "http://localhost:11434/v1")
    api_key = os.environ.get("OPENCODE_API_KEY", "")
    headers = ["-H", "Content-Type: application/json"]
    if api_key:
        os.makedirs("/tmp/opencode", exist_ok=True)
        with open("/tmp/opencode/skillkit_headers.conf", "w") as _hf:
            _hf.write(f"Authorization: Bearer {api_key}\n")
        headers += ["-K", "/tmp/opencode/skillkit_headers.conf"]
    url = api_url.rstrip('/')
    if not url.endswith('/chat/completions'):
        url += '/chat/completions'

    try:
        r = subprocess.run(
            ["curl", "-s", "-X", "POST", url,
             *headers, "-d", "@" + pfile],
            capture_output=True, text=True, timeout=timeout)
        # Guardar respuesta cruda para debug
        rfile = '/tmp/opencode/audit_resolve_raw_response.json'
        with open(rfile, 'w') as f:
            json.dump({"status": "debug", "response": r.stdout[:2000]}, f, ensure_ascii=False)

        if r.returncode != 0:
            return f"ERROR curl: {r.stderr}"
        if not r.stdout.strip():
            return "ERROR: respuesta vacia"

        resp = json.loads(r.stdout)
        if "error" in resp:
            return f"ERROR API: {resp['error']}"
        choices = resp.get("choices", [])
        content = (choices[0]["message"]["content"] if choices
                   else resp.get("message", {}).get("content", ""))
        return re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
    except subprocess.TimeoutExpired:
        return "ERROR: timeout"
    except Exception as e:
        return f"ERROR: {e}"


# =============================================================================
# DIAGNOSE
# =============================================================================

def find_last_audit(audit_dir: str) -> str | None:
    """Busca el archivo *-audit.md mas reciente (sin -resolve)."""
    files = [f for f in os.listdir(audit_dir)
             if f.endswith('-audit.md') and '-resolve' not in f]
    if not files:
        return None
    files.sort(reverse=True)
    return files[0]


def extract_checkpoint_findings(cp_dir: str) -> list[dict]:
    """Lee todos los checkpoints y extrae hallazgos pendientes."""
    findings = []
    if not os.path.isdir(cp_dir):
        return findings

    for fname in sorted(os.listdir(cp_dir)):
        if not fname.endswith('_cp.md'):
            continue
        content = read_file(os.path.join(cp_dir, fname))
        if not content:
            continue

        # Extraer metadatos del checkpoint
        title_m = re.search(r'# Checkpoint:\s*(.+)', content)
        fecha_m = re.search(r'\*\*Fecha\*\*:\s*(.+)', content)
        veredicto_m = re.search(r'\*\*Veredicto\*\*:\s*(.+)', content)
        criticos_m = re.search(r'\*\*Criticos\*\*:\s*(\d+)', content)

        title = title_m.group(1).strip() if title_m else fname
        veredicto = veredicto_m.group(1).strip() if veredicto_m else "?"
        criticos = int(criticos_m.group(1)) if criticos_m else 0

        # Saltar si ya esta aprobado sin criticos
        if criticos == 0 and 'APROBADO' in veredicto:
            continue

        # Extraer hallazgos criticos individuales
        # Formato: **ID**: C1, **Descripcion**: ..., **Archivo:linea**: ..., **Accion requerida**: ...
        for m in re.finditer(
            r'\*\*ID\*\*:\s*(C\d+).*?'
            r'\*\*Descripcion?\*\*:\s*(.+?)(?:\*\*|$)',
            content, re.DOTALL
        ):
            finding_id = m.group(1).strip()
            desc = m.group(2).strip()

            # Extraer archivo:linea si existe
            fl = re.search(
                r'\*\*Archivo:linea\*\*:\s*(.+?)(?:\*\*|$)',
                content[m.end():m.end() + 500]
            )
            archivo = fl.group(1).strip() if fl else ""

            # Extraer accion requerida
            ar = re.search(
                r'\*\*Accion requerida\*\*:\s*(.+?)(?:\*\*|$)',
                content[m.end():m.end() + 500]
            )
            accion = ar.group(1).strip() if ar else ""

            # Determinar tipo de etapa
            stage_type = 'codigo'
            if 'spec' in title.lower():
                stage_type = 'spec'
            elif 'plan' in title.lower():
                stage_type = 'plan'
            elif 'tasks' in title.lower():
                stage_type = 'tasks'

            findings.append({
                'stage_title': title,
                'finding_id': finding_id,
                'descripcion': desc,
                'archivo': archivo,
                'accion': accion,
                'stage_type': stage_type,
                'checkpoint_file': fname,
                'veredicto': veredicto,
            })

        # Si no hay hallazgos individuales con **ID**: C, crear uno global
        if not re.search(r'\*\*ID\*\*:\s*C\d+', content) and criticos > 0:
            findings.append({
                'stage_title': title,
                'finding_id': 'C1',
                'descripcion': f'{criticos} hallazgos criticos en {title}',
                'archivo': '',
                'accion': f'Resolver {criticos} hallazgos criticos',
                'stage_type': 'codigo',
                'checkpoint_file': fname,
                'veredicto': veredicto,
            })

    return findings


def diagnose(workdir: str) -> dict:
    audit_dir = os.path.join(workdir, 'audit')
    cp_dir = os.path.join(audit_dir, 'checkpoints')

    if not os.path.isdir(cp_dir):
        return {"status": "error", "message": "No existe audit/checkpoints/"}

    findings = extract_checkpoint_findings(cp_dir)

    if not findings:
        return {"status": "no_findings", "message": "No hay hallazgos pendientes"}

    # Encontrar ultimo audit
    last_audit = find_last_audit(audit_dir)
    if not last_audit:
        return {"status": "error", "message": "No se encontro archivo *-audit.md en audit/"}

    # Extraer id del audit
    id_m = re.match(r'(\d+)-', last_audit)
    audit_id = id_m.group(1) if id_m else "001"

    # Obtener timestamp del audit
    audit_content = read_file(os.path.join(audit_dir, last_audit))
    audit_ts_m = re.search(r'\*\*Ultima actualizacion\*\*:\s*(.+)', audit_content)
    audit_ts = audit_ts_m.group(1).strip() if audit_ts_m else now_iso()

    # Generar nombre del archivo resolve
    resolve_fname = last_audit.replace('-audit.md', '-audit-resolve.md')
    resolve_path = os.path.join(audit_dir, resolve_fname)

    # Agrupar findings por stage
    stages: dict[str, list[dict]] = {}
    for f in findings:
        st = f['stage_title']
        if st not in stages:
            stages[st] = []
        stages[st].append(f)

    # Construir contenido del resolve.md
    lines = [
        f"# Resolve: {audit_id}",
        f"**Audit**: {audit_ts}",
        f"**Solucion**: (pendiente)",
        "",
    ]

    total = 0
    for stage_name, stage_findings in stages.items():
        lines.append(f"## {stage_name} — {len(stage_findings)} criticos")
        for f in stage_findings:
            archivo = f" — `{f['archivo']}`" if f['archivo'] else ""
            lines.append(f"- [ ] **{f['finding_id']}** {f['descripcion']}{archivo}")
            if f['accion']:
                lines.append(f"  - {f['accion']}")
        lines.append("")
        total += len(stage_findings)

    write_file(resolve_path, '\n'.join(lines))
    log(f"Resolve generado: {resolve_path} ({total} hallazgos)")

    return {
        "status": "ok",
        "resolve_path": resolve_path,
        "total_findings": total,
        "audit_id": audit_id,
        "stages": list(stages.keys()),
    }


# =============================================================================
# RESOLVE
# =============================================================================

SYSTEM_SPEC = """Eres un asistente que ayuda a resolver hallazgos de auditoria en documentacion de especificaciones, planes y tareas. Dado un hallazgo con archivo, descripcion y accion requerida, proporciona el cambio exacto.

Debes responder EXACTAMENTE en este formato (sin texto adicional):

```diff
// ruta/al/archivo.md
- linea original
+ linea modificada
```"""

SYSTEM_CODIGO = """Eres un asistente que ayuda a resolver hallazgos de auditoria en codigo. Dado un hallazgo con archivo, descripcion y accion requerida, proporciona el codigo exacto que debe modificarse.

Debes responder EXACTAMENTE en este formato (sin texto adicional):

```diff
// ruta/al/archivo.ts
- linea original
+ linea modificada
```"""


def get_model_name(stage_type: str) -> str:
    if stage_type in ('spec', 'plan', 'tasks'):
        return 'audit.resolve_spec'
    return 'audit.resolve_codigo'


def get_system_prompt(stage_type: str) -> str:
    if stage_type in ('spec', 'plan', 'tasks'):
        return SYSTEM_SPEC
    return SYSTEM_CODIGO


def _extract_archivo(desc: str) -> str:
    """Extrae ruta de archivo desde backticks en la descripcion del hallazgo.
    Ej: `src/services/mandado.service.ts:68-96,` → src/services/mandado.service.ts"""
    m = re.search(r'`([^`]+\.(ts|js|rb|py|md|json|yaml|yml))', desc)
    if m:
        path = m.group(1).split(':')[0].rstrip(',').strip()
        return path
    return ''


def _extract_accion(desc: str) -> str:
    """Extrae la accion requerida del texto del hallazgo si esta presente."""
    m = re.search(r'Accion requerida[^:]*:\s*([^.]+)', desc)
    if m:
        return m.group(1).strip()
    return ''


def resolve_finding(workdir: str, finding: dict, idx: int, action: str = "solve") -> dict:
    stage_type = finding['stage_type']
    skill_name = get_model_name(stage_type)
    system = get_system_prompt(stage_type)

    # Leer contexto del archivo afectado
    context = ""
    archivo = finding.get('archivo', '')
    if archivo:
        # Extraer solo el nombre del archivo (sin ruta completa)
        fname = archivo.split('`')[0].strip() if '`' in archivo else archivo
        fpath = os.path.join(workdir, fname)
        context = read_file(fpath)
        if len(context) > 3000:
            context = context[:1500] + "\n... [truncado] ...\n" + context[-1500:]

    user_msg = (
        f"## Hallazgo\n"
        f"**ID**: {finding['finding_id']}\n"
        f"**Descripcion**: {finding['descripcion']}\n"
        f"**Archivo**: {finding.get('archivo', 'N/A')}\n"
        f"**Accion requerida**: {finding.get('accion', 'N/A')}\n"
    )
    if context:
        user_msg += f"\n## Contexto del archivo\n```\n{context}\n```\n"

    user_msg += "\nProporciona el cambio exacto para resolver este hallazgo."

    log(f"  Enviando hallazgo {finding['finding_id']} ({finding['stage_title']}) a modelo {skill_name}...")
    suggestion = run_model(system, user_msg, skill_name)

    # Guardar sugerencia
    safe_stage = re.sub(r'[^a-zA-Z0-9_-]', '_', finding['stage_title'])
    sug_path = f'/tmp/opencode/audit_resolve_suggestion_{safe_stage}_{idx}.md'
    write_file(sug_path, suggestion)

    # Aplicar sugerencia solo en modo solve
    apply_result = {"applied": False, "file": "", "message": "Modo sugerencia — no se aplico cambio"}
    if action == "solve":
        apply_result = apply_suggestion(workdir, suggestion, finding)
        if apply_result['applied']:
            log(f"  ✅ {apply_result['message']}")
        else:
            log(f"  ⚠️  Sugerencia generada pero no aplicada: {apply_result['message']}")
    else:
        log(f"  💡 Sugerencia generada (modo suggest): {sug_path}")

    return {
        "finding_id": finding['finding_id'],
        "stage": finding['stage_title'],
        "suggestion_path": sug_path,
        "suggestion_preview": suggestion[:200] + "..." if len(suggestion) > 200 else suggestion,
        "suggestion_full": suggestion,
        "applied": apply_result,
        "action": action,
    }


def apply_suggestion(workdir: str, suggestion: str, finding: dict = None) -> dict:
    """Parsea un diff de la sugerencia y lo aplica al archivo fuente.
    Retorna {'applied': True/False, 'file': '...', 'message': '...'}"""
    # Prioridad 1: ruta desde el hallazgo (archivo extraido de resolve.md)
    file_path = ''
    if finding and finding.get('archivo'):
        file_path = finding['archivo']

    # Prioridad 2: detectar desde el diff (// ruta/al/archivo.ts  o  --- a/...)
    if not file_path:
        # Buscar // ruta/al/archivo.ts (comentario que el modelo pone al inicio del diff)
        for m in re.finditer(r'//\s*(\S+\.(?:ts|js|json|rb|py|md|prisma|yaml|yml))', suggestion):
            file_path = m.group(1)
            break
    if not file_path:
        for m in re.finditer(r'---\s+a/(\S+)', suggestion):
            file_path = m.group(1)
            break
    if not file_path:
        return {'applied': False, 'file': '', 'message': 'No se pudo detectar el archivo a modificar'}

    fpath = os.path.join(workdir, file_path)
    if not os.path.exists(fpath):
        return {'applied': False, 'file': file_path, 'message': f'Archivo no encontrado: {fpath}'}

    # Extraer bloque diff entre ```diff y ```
    diff_match = re.search(r'```diff\n(.+?)```', suggestion, re.DOTALL)
    if not diff_match:
        # Intentar con ``` simplemente
        diff_match = re.search(r'```\n(.+?)```', suggestion, re.DOTALL)
    if not diff_match:
        return {'applied': False, 'file': file_path, 'message': 'No se encontro bloque diff en la sugerencia'}

    diff_text = diff_match.group(1).strip()
    content = read_file(fpath)

    # Parsear el diff: agrupar lineas - como old_text y + como new_text
    # Soporta:
    #   - old line
    #   + new line
    # O con contexto:
    #   context line
    #   - old line
    #   + new line
    lines = diff_text.split('\n')
    old_lines = []
    new_lines = []
    i = 0
    changes = 0

    while i < len(lines):
        line = lines[i]
        if line.startswith('-') and not line.startswith('---'):
            # Recolectar todas las lineas - consecutivas
            old_block = [line[1:]]  # remove leading -
            i += 1
            while i < len(lines) and lines[i].startswith('-') and not lines[i].startswith('---'):
                old_block.append(lines[i][1:])
                i += 1
            # Ahora recolectar las lineas + que correspondan
            new_block = []
            while i < len(lines) and lines[i].startswith('+') and not lines[i].startswith('+++'):
                new_block.append(lines[i][1:])
                i += 1
            old_text = '\n'.join(old_block)
            new_text = '\n'.join(new_block)
            if old_text in content:
                content = content.replace(old_text, new_text, 1)
                changes += 1
        else:
            i += 1

    if changes == 0:
        return {'applied': False, 'file': file_path, 'message': 'No se encontraron cambios para aplicar (diff no coincide)'}

    write_file(fpath, content)
    return {'applied': True, 'file': file_path, 'message': f'Aplicados {changes} cambio(s) en {file_path}'}


def resolve_stage(workdir: str, stage_title: str, action: str = "solve") -> dict:
    """Resuelve los hallazgos de UNA sola etapa.
    Retorna resultados para que el orquestador los muestre y decida si aplicar."""
    audit_dir = os.path.join(workdir, 'audit')

    resolve_files = [f for f in os.listdir(audit_dir) if f.endswith('-audit-resolve.md')]
    if not resolve_files:
        return {"status": "error", "message": "No hay archivos *-audit-resolve.md. Ejecuta diagnose primero."}
    resolve_files.sort(reverse=True)
    resolve_path = os.path.join(audit_dir, resolve_files[0])
    resolve_content = read_file(resolve_path)
    if not resolve_content:
        return {"status": "error", "message": f"No se pudo leer {resolve_path}"}

    # Extraer hallazgos de la etapa especifica
    findings = []
    in_target_stage = False
    for line in resolve_content.split('\n'):
        if line.startswith('## '):
            in_target_stage = (stage_title.lower() in line.lower())
            continue
        if not in_target_stage:
            continue
        m = re.match(r'- \[ \] \*\*(C\d+)\*\*\s+(.+)', line)
        if m:
            stage_type = 'codigo'
            cl = stage_title.lower()
            if 'spec' in cl:
                stage_type = 'spec'
            elif 'plan' in cl:
                stage_type = 'plan'
            elif 'tasks' in cl:
                stage_type = 'tasks'
            findings.append({
                'finding_id': m.group(1),
                'descripcion': m.group(2).strip(),
                'stage_title': stage_title,
                'stage_type': stage_type,
                'archivo': _extract_archivo(m.group(2)),
                'accion': _extract_accion(m.group(2)),
            })

    if not findings:
        return {"status": "error", "message": f"No se encontraron hallazgos para etapa '{stage_title}'"}

    # Reanudacion
    progress = load_progress()
    completed = set()
    if progress:
        completed = set(progress.get('completed_findings', []))

    total = len(findings)
    results = []
    last_stage_type = None

    log(f"\n{'─'*54}")
    log(f"  Etapa: {stage_title} — {total} hallazgos — Modo: {action}")
    log(f"{'─'*54}")

    for i, finding in enumerate(findings):
        finding_key = f"{finding['stage_title']}/{finding['finding_id']}"
        if finding_key in completed:
            log(f"  Saltando {finding_key} (ya completado)")
            progress_bar(i + 1, total, finding_key)
            continue

        # Mostrar banner por grupo de modelo
        current_type = finding['stage_type']
        if current_type != last_stage_type:
            skill_name = get_model_name(current_type)
            resolve_model(skill_name)
            modo_raw = os.environ.get("OPENCODE_MODO", os.environ.get("TOKEN_BUDGET", "?"))
            modo_label = {"low": "Low", "medium": "Medium", "high": "High"}.get(modo_raw, modo_raw)
            modelo = os.environ.get("OPENCODE_MODEL", "?")
            proveedor = os.environ.get("OPENCODE_PROVEEDOR", "?")
            group_label = current_type.upper() if current_type in ('spec','plan','tasks') else 'CODIGO'
            print_model_banner(modo_label, modelo, proveedor,
                               f"Resolviendo hallazgos de {group_label}",
                               f"{stage_title} [{i+1}/{total}] {finding['finding_id']}",
                               action_type=action)
            last_stage_type = current_type

        log(f"\n[{i+1}/{total}] Resolviendo {finding_key}...")
        result = resolve_finding(workdir, finding, i, action=action)
        results.append(result)

        # Actualizar checkpoint
        completed.add(finding_key)
        save_progress({
            "stage_name": stage_title,
            "stage_index": i,
            "finding_index": i,
            "completed_stages": list(set(f['stage_title'] for f in findings
                                          if f"{f['stage_title']}/{f['finding_id']}" in completed)),
            "completed_findings": list(completed),
        })

        progress_bar(i + 1, total, finding_key)
        time.sleep(0.5)

    return {
        "status": "ok",
        "stage": stage_title,
        "total": total,
        "resolved": len(results),
        "action": action,
        "results": results,
        "resolve_path": resolve_path,
    }


def resolve(workdir: str, stage_filter: str | None = None, resolve_index: int | None = None,
            action: str = "solve") -> dict:
    audit_dir = os.path.join(workdir, 'audit')

    # Encontrar ultimo resolve
    resolve_files = [f for f in os.listdir(audit_dir) if f.endswith('-audit-resolve.md')]
    if not resolve_files:
        return {"status": "error", "message": "No hay archivos *-audit-resolve.md. Ejecuta diagnose primero."}

    resolve_files.sort(reverse=True)
    resolve_path = os.path.join(audit_dir, resolve_files[0])
    resolve_content = read_file(resolve_path)
    if not resolve_content:
        return {"status": "error", "message": f"No se pudo leer {resolve_path}"}

    # Verificar que no este ya resuelto
    if '**Solucion**:' in resolve_content and '(pendiente)' not in resolve_content:
        return {"status": "already_resolved", "message": "Ya resuelto anteriormente"}

    # Extraer hallazgos del resolve.md
    findings = []
    current_stage = None
    for line in resolve_content.split('\n'):
        if line.startswith('## '):
            current_stage = line[3:].strip()
        m = re.match(r'- \[ \] \*\*(C\d+)\*\*\s+(.+)', line)
        if m and current_stage:
            # Determinar tipo de etapa
            stage_type = 'codigo'
            cl = current_stage.lower()
            if 'spec' in cl:
                stage_type = 'spec'
            elif 'plan' in cl:
                stage_type = 'plan'
            elif 'tasks' in cl:
                stage_type = 'tasks'
            findings.append({
                'finding_id': m.group(1),
                'descripcion': m.group(2).strip(),
                'stage_title': current_stage,
                'stage_type': stage_type,
                'archivo': _extract_archivo(m.group(2)),
                'accion': _extract_accion(m.group(2)),
            })

    if not findings:
        return {"status": "error", "message": "No se encontraron hallazgos pendientes en resolve.md"}

    # Filtrar por etapa si se especifico
    if stage_filter:
        findings = [f for f in findings if stage_filter.lower() in f['stage_title'].lower()]
        if not findings:
            return {"status": "error", "message": f"No hay hallazgos para etapa '{stage_filter}'"}

    # Reanudacion
    progress = load_progress()
    completed = set()
    if progress:
        completed = set(progress.get('completed_findings', []))
        log(f"Reanudando: {len(completed)} hallazgos ya completados")

    total = len(findings)
    results = []
    last_stage_type = None

    for i, finding in enumerate(findings):
        finding_key = f"{finding['stage_title']}/{finding['finding_id']}"
        if finding_key in completed:
            log(f"  Saltando {finding_key} (ya completado)")
            progress_bar(i + 1, total, finding_key)
            continue

        # Si se especifico un indice, solo procesar ese
        if resolve_index is not None and i != resolve_index:
            continue

        # Si se especifico un indice, es el unico a procesar
        if resolve_index is not None:
            log(f"\n[{i+1}/{total}] Resolviendo {finding_key} (unico)...")

        # Mostrar banner por grupo de modelo
        current_type = finding['stage_type']
        if current_type != last_stage_type:
            skill_name = get_model_name(current_type)
            resolve_model(skill_name)
            modo_raw = os.environ.get("OPENCODE_MODO", os.environ.get("TOKEN_BUDGET", "?"))
            modo_label = {"low": "Low", "medium": "Medium", "high": "High"}.get(modo_raw, modo_raw)
            modelo = os.environ.get("OPENCODE_MODEL", "?")
            proveedor = os.environ.get("OPENCODE_PROVEEDOR", "?")
            group_label = current_type.upper() if current_type in ('spec','plan','tasks') else 'CODIGO'
            print_model_banner(modo_label, modelo, proveedor,
                               f"Resolviendo hallazgos de {group_label}",
                               f"Hallazgo {i+1}/{total}: {finding['finding_id']}",
                               action_type=action)
            last_stage_type = current_type

        log(f"\n[{i+1}/{total}] Resolviendo {finding_key}...")
        result = resolve_finding(workdir, finding, i, action=action)
        results.append(result)

        # Actualizar checkpoint
        completed.add(finding_key)
        save_progress({
            "stage_index": i,
            "finding_index": i,
            "completed_stages": list(set(f['stage_title'] for f in findings
                                          if f"{f['stage_title']}/{f['finding_id']}" in completed)),
            "completed_findings": list(completed),
        })

        progress_bar(i + 1, total, finding_key)
        # Pequena pausa entre hallazgos
        import time
        time.sleep(0.5)

    return {
        "status": "ok",
        "total": total,
        "resolved": len(results),
        "results": results,
        "resolve_path": resolve_path,
    }


# =============================================================================
# FINALIZE
# =============================================================================

def verify_timestamps(workdir: str, resolve_content: str, target_ts: str) -> dict:
    """Verifica que el timestamp de solucion sea estrictamente mayor que el mtime
    de todos los archivos referenciados en los hallazgos del resolve.md.
    Si no, ajusta el timestamp y espera hasta que se cumpla la condicion.
    Retorna {'ok': bool, 'timestamp': str, 'max_mtime': str, 'archivos': [...]}"""
    # Parsear archivos referenciados
    archivos_ref = set()
    # Patron 1: rutas entre backticks con extension (`src/file.ts:line`)
    for m in re.finditer(r'`([^`]+\.\w+)(?::\d+(?:[-,]\d+)*)?`', resolve_content):
        rel_path = m.group(1).split(':')[0].rstrip(',;. ').strip()
        fpath = os.path.join(workdir, rel_path)
        if os.path.exists(fpath):
            archivos_ref.add(fpath)

    # Patron 2: rutas que empiezan con directorios conocidos del proyecto
    for m in re.finditer(
        r'(?:specs|src|prisma|qa|templates|tests|docs|scripts)/'
        r'[^\s)`;,]+\.\w+',
        resolve_content,
    ):
        raw = m.group(0).rstrip(',;. ')
        # Limpiar posibles sufijos como :line,col
        clean = re.sub(r':\d+(?:[-,]\d+)*', '', raw)
        fpath = os.path.join(workdir, clean)
        if os.path.exists(fpath):
            archivos_ref.add(fpath)

    # Patron 3: rutas con prefijo de modulo como src/... o tests/... sin extension explicita
    # que aparecen en descripciones de hallazgos
    for m in re.finditer(
        r'(?:src|tests|specs|docs|prisma|scripts)/[^\s)`;,]+',
        resolve_content,
    ):
        raw = m.group(0).rstrip(',;. ')
        clean = re.sub(r':\d+(?:[-,]\d+)*', '', raw)
        # Solo considerar si parece una ruta valida (tiene / y no es solo un directorio)
        if clean.count('/') >= 1 and not clean.endswith('/'):
            fpath = os.path.join(workdir, clean)
            if os.path.exists(fpath):
                archivos_ref.add(fpath)

    if not archivos_ref:
        return {"ok": True, "timestamp": target_ts, "max_mtime": target_ts, "archivos": []}

    # Obtener mtime maximo de todos los archivos referenciados
    max_mtime = 0.0
    archivos_info = []
    for fpath in sorted(archivos_ref):
        try:
            mtime = os.path.getmtime(fpath)
            mtime_str = datetime.fromtimestamp(mtime).strftime('%Y-%m-%dT%H:%M:%S')
            archivos_info.append({"archivo": os.path.relpath(fpath, workdir), "mtime": mtime_str})
            if mtime > max_mtime:
                max_mtime = mtime
        except OSError:
            continue

    max_mtime_str = datetime.fromtimestamp(max_mtime).strftime('%Y-%m-%dT%H:%M:%S') if max_mtime > 0 else target_ts

    # Parsear el timestamp objetivo
    try:
        ts_dt = datetime.strptime(target_ts, '%Y-%m-%dT%H:%M:%S')
        ts_epoch = ts_dt.timestamp()
    except ValueError:
        ts_epoch = time.time()

    if ts_epoch <= max_mtime and max_mtime > 0:
        # El timestamp es menor o igual que algun mtime → ajustar
        log(f"  ⚠️  Timestamp {target_ts} <= max mtime {max_mtime_str} de archivos")
        log(f"  Ajustando timestamp...")
        # Usar max_mtime + 1 segundo para garantizar que sea estrictamente mayor
        new_epoch = max_mtime + 2
        new_ts = datetime.fromtimestamp(new_epoch).strftime('%Y-%m-%dT%H:%M:%S')
        log(f"  Nuevo timestamp: {new_ts}")
        return {"ok": True, "timestamp": new_ts, "max_mtime": max_mtime_str, "archivos": archivos_info, "adjusted": True}

    return {"ok": True, "timestamp": target_ts, "max_mtime": max_mtime_str, "archivos": archivos_info, "adjusted": False}


def finalize(workdir: str) -> dict:
    audit_dir = os.path.join(workdir, 'audit')

    # Encontrar ultimo resolve
    resolve_files = [f for f in os.listdir(audit_dir) if f.endswith('-audit-resolve.md')]
    if not resolve_files:
        return {"status": "error", "message": "No hay archivos *-audit-resolve.md"}

    resolve_files.sort(reverse=True)
    resolve_path = os.path.join(audit_dir, resolve_files[0])
    content = read_file(resolve_path)
    if not content:
        return {"status": "error", "message": f"No se pudo leer {resolve_path}"}

    # Verificar y ajustar timestamp para que sea mayor que mtimes de archivos
    ts_raw = now_iso()
    verify_result = verify_timestamps(workdir, content, ts_raw)
    ts = verify_result["timestamp"]

    if verify_result.get("adjusted"):
        log(f"  Timestamp ajustado para ser > mtime de archivos modificados")
    log(f"  Archivos referenciados: {len(verify_result.get('archivos', []))}")
    if verify_result.get("archivos"):
        for a in verify_result["archivos"]:
            log(f"    {a['archivo']} (mtime: {a['mtime']})")

    # Reemplazar timestamp con el verificado (soporta (pendiente) o timestamp previo)
    new_content = content.replace('**Solucion**: (pendiente)', f'**Solucion**: {ts}')
    if new_content == content:
        # Si ya habia timestamp, reemplazarlo
        ts_match = re.search(r'\*\*Solucion\*\*:\s*\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', content)
        if ts_match:
            new_content = content.replace(ts_match.group(0), f'**Solucion**: {ts}')
        else:
            return {"status": "error", "message": "No se encontro '**Solucion**: (pendiente)' ni timestamp previo en resolve.md"}

    write_file(resolve_path, new_content)

    # Touch para sincronizar mtime
    os.utime(resolve_path, None)

    log(f"Resolve finalizado: {resolve_path} (solucion: {ts})")
    return {
        "status": "ok",
        "resolve_path": resolve_path,
        "solucion_timestamp": ts,
        "max_mtime_archivos": verify_result.get("max_mtime", ""),
        "archivos_verificados": len(verify_result.get("archivos", [])),
    }


# =============================================================================
# MAIN
# =============================================================================

def main():
    workdir = os.environ.get('AUDIT_WORKDIR', os.getcwd())
    mode = os.environ.get('AUDIT_RESOLVE_MODE', 'diagnose')
    stage_filter = os.environ.get('AUDIT_RESOLVE_STAGE', '')
    index_str = os.environ.get('AUDIT_RESOLVE_INDEX', '')
    action = os.environ.get('AUDIT_RESOLVE_ACTION', 'solve')
    # Validar action
    if action not in ('suggest', 'solve'):
        action = 'solve'

    if mode == 'diagnose':
        result = diagnose(workdir)
    elif mode == 'resolve_stage':
        # Modo nuevo: resuelve UNA etapa especifica
        if not stage_filter:
            result = {"status": "error", "message": "AUDIT_RESOLVE_STAGE es obligatorio para mode=resolve_stage"}
        else:
            result = resolve_stage(workdir, stage_filter, action=action)
    elif mode == 'resolve':
        index = int(index_str) if index_str.isdigit() else None
        result = resolve(workdir, stage_filter if stage_filter else None, index, action=action)
    elif mode == 'finalize':
        result = finalize(workdir)
    else:
        result = {"status": "error", "message": f"Modo invalido: {mode}"}

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
