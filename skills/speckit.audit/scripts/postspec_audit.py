#!/usr/bin/env python3
"""
Post-Spec Audit — Ejecuta auditoría por lotes para cualquier etapa.
Modo batch general: AUDIT_BATCHES=json_array (funciona para spec/plan/tasks/codigo)
Modo normal: sin AUDIT_BATCHES, un solo payload.

Variables de entorno:
  AUDIT_STAGE: etapa a auditar
  AUDIT_FEATURE: nombre del feature
  AUDIT_MODEL: override del modelo (opcional)
  AUDIT_CONTEXT_DIR: directorio con context_*.txt para batches
  AUDIT_CONSOLIDATE: "true" para solo consolidar reportes parciales
  AUDIT_BATCH_FILES: patrón glob para archivos de batch (ej: "audit_batch_spec_*.txt")
  AUDIT_FIXED_CONTEXT: ruta al contexto fijo que va en todos los batches (opcional)
  AUDIT_RESUME: "true" para saltar batches ya completados
  AUDIT_WORKDIR: directorio del proyecto
  AUDIT_GLOBAL_PROGRESS: "X/Y" (etapa actual de N totales)
"""

import json, subprocess, sys, os, re, glob, shutil

sys.path.insert(0, os.environ["SKILLKIT_HOME"])
from lib import resolve_model

API_URL = os.environ.get("OPENCODE_API_URL", "http://localhost:11434/v1")
API_KEY = os.environ.get("OPENCODE_API_KEY", "")

def log(msg):
    print(msg, file=sys.stderr, flush=True)

def log_progress(current, total, status_msg=""):
    pct = (current / total) * 100 if total > 0 else 0
    bar_len = 30
    filled = int(bar_len * current / total) if total > 0 else 0
    bar = "█" * filled + "░" * (bar_len - filled)
    sys.stderr.write(f"\r  Progreso: |{bar}| {pct:5.1f}%  ({current}/{total})  {status_msg}")
    sys.stderr.flush()
    if current == total:
        sys.stderr.write("\n")

def read_file(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return ""

def run_ollama_prompt(system_prompt, user_content, model, num_predict):
    payload = {
        "model": model,
        "stream": False,
        "options": {"num_predict": num_predict},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]
    }
    payload_path = '/tmp/opencode/payload_batch.json'
    os.makedirs('/tmp/opencode', exist_ok=True)
    with open(payload_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False)

    try:
        headers = ["Content-Type: application/json"]
        if API_KEY:
            headers.append(f"Authorization: Bearer {API_KEY}")
        curl_cmd = ["curl", "-s", "-X", "POST", API_URL] + \
            [item for h in headers for item in ["-H", h]] + \
            ["-d", "@" + payload_path]
        result = subprocess.run(
            curl_cmd,
            capture_output=True, text=True, timeout=600
        )
        if result.returncode != 0:
            return f"ERROR curl (exit {result.returncode}): {result.stderr}"
        if not result.stdout.strip():
            return "ERROR: respuesta vacía de Ollama"
        response_json = json.loads(result.stdout)
        content = response_json.get("message", {}).get("content", "")
        content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL)
        return content.strip()
    except Exception as e:
        return f"ERROR: {e}"

def extract_verdict(report_text):
    if not report_text:
        return "DESCONOCIDO"
    for pattern in [r'❌ REQUIERE CAMBIOS', r'⚠️ APROBADO CON OBSERVACIONES', r'✅ APROBADO']:
        m = re.search(pattern, report_text)
        if m:
            return m.group(0)
    return "DESCONOCIDO"

def extract_finding_counts(report_text):
    if not report_text:
        return 0, 0, 0
    crit = len(re.findall(r'C\d+', report_text.split('## Advertencias')[0] if '## Advertencias' in report_text else report_text))
    adv = len(re.findall(r'W\d+', report_text.split('## Advertencias')[1].split('## Observaciones')[0] if '## Advertencias' in report_text and '## Observaciones' in report_text else report_text))
    obs = len(re.findall(r'O\d+', report_text.split('## Observaciones')[1] if '## Observaciones' in report_text else report_text))
    return crit, adv, obs

def save_checkpoint(audit_path, batch_idx, total_batches, layer, feature, report, global_progress=""):
    fecha = __import__('datetime').datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
    pct = int((batch_idx / total_batches) * 100) if total_batches > 0 else 0
    verdict = extract_verdict(report)
    crit, adv, obs = extract_finding_counts(report)
    gp_line = f"\n- **Progreso global**: {global_progress}" if global_progress else ""

    entry = f"""
## Checkpoint #{batch_idx} — Batch: {layer}
- **Fecha**: {fecha}{gp_line}
- **Etapa**: codigo
- **Feature**: {feature}
- **Progreso**: {pct}% ({batch_idx}/{total_batches})
- **Veredicto parcial**: {verdict}
- **Hallazgos**: {crit} críticos, {adv} advertencias, {obs} observaciones

### Reporte Parcial
{report}

---
"""
    with open(audit_path, 'a', encoding='utf-8') as f:
        f.write(entry)

def get_completed_layers(audit_path):
    """Lee audit.md y devuelve los layers ya completados (para reanudación)."""
    content = read_file(audit_path)
    completed = set()
    for m in re.finditer(r'^## Checkpoint #\d+ — Batch: (\w+)', content, re.MULTILINE):
        completed.add(m.group(1))
    return completed

def main():
    stage = os.environ.get('AUDIT_STAGE', 'spec')
    feature = os.environ.get('AUDIT_FEATURE', '')
    model = os.environ.get('AUDIT_MODEL', resolve_model("audit.spec_plan_tasks"))
    num_predict = {'spec': 2048, 'plan': 2048, 'tasks': 2048, 'codigo': 3072}.get(stage, 2048)
    context_dir = os.environ.get('AUDIT_CONTEXT_DIR', '/tmp/opencode')
    workdir = os.environ.get('AUDIT_WORKDIR', os.getcwd())
    audit_path = os.path.join(workdir, 'audit.md')

    # --- Modo consolidación ---
    if os.environ.get('AUDIT_CONSOLIDATE') == 'true':
        log(" Consolidando reportes parciales...")
        partials = {}
        for fpath in sorted(glob.glob(os.path.join(context_dir, 'report_partial_*.txt'))):
            layer = os.path.basename(fpath).replace('report_partial_', '').replace('.txt', '')
            partials[layer] = read_file(fpath)

        if not partials:
            log("ERROR: no se encontraron reportes parciales")
            sys.exit(1)

        log(f" Capas a consolidar ({len(partials)}): {', '.join(partials.keys())}")
        layers_summary = "\n".join([f"- **{k}**: {len(v.split(chr(10)))} líneas" for k, v in partials.items()])
        all_reports = "\n\n".join([f"=== REPORTE {k.upper()} ===\n{v}" for k, v in partials.items()])

        consolidate_prompt = f"""Eres un auditor senior de ingeniería de software. CONSOLIDA múltiples reportes parciales de auditoría de código en UN SOLO reporte unificado.

Capas: {', '.join(partials.keys())}.

Instrucciones:
1. Deduplica hallazgos que aparecen en múltiples capas
2. Elimina contradicciones entre reportes
3. Asigna severidad correcta (CRITICAL > HIGH > MEDIUM > LOW)
4. Produce veredicto GLOBAL

Responde EXACTAMENTE con:

# Reporte de Auditoría — Código (Consolidado)

## Resumen Ejecutivo

## Hallazgos Críticos 🔴

## Advertencias 🟡

## Observaciones 🟢

## Veredicto
✅ APROBADO | ⚠️ APROBADO CON OBSERVACIONES | ❌ REQUIERE CAMBIOS

## Cobertura de Requisitos
Tabla FR vs implementación detectada.

Responde únicamente en español."""

        user_msg = f"""Feature: {feature}
Etapa: codigo
Capas ({len(partials)}): {', '.join(partials.keys())}

{layers_summary}

Reportes:
{all_reports}"""

        result = run_ollama_prompt(consolidate_prompt, user_msg, model, 3072)
        print(result)
        return

    # --- Modo batch (general: spec/plan/tasks/codigo) ---
    batch_files_pattern = os.environ.get('AUDIT_BATCH_FILES', '')
    batches_raw = os.environ.get('AUDIT_BATCHES', '[]')
    has_batches = False
    
    if batch_files_pattern:
        # Modo batch basado en archivos
        batch_files = sorted(glob.glob(os.path.join(context_dir, batch_files_pattern)))
        if not batch_files:
            log(f"ERROR: no se encontraron archivos con patrón {batch_files_pattern}")
            sys.exit(1)
        batches = [{'file': f, 'label': os.path.basename(f).replace('.txt', '')} for f in batch_files]
        has_batches = True
        log(f" Modo batch por archivos: {len(batches)} lotes desde {batch_files_pattern}")
    elif batches_raw and batches_raw != '[]':
        try:
            batches = json.loads(batches_raw)
            has_batches = True
            log(f" Modo batch por JSON: {len(batches)} lotes")
        except json.JSONDecodeError:
            log("WARN: AUDIT_BATCHES inválido, ignorando")
    
    if has_batches:
        global_progress = os.environ.get('AUDIT_GLOBAL_PROGRESS', '')
        total = len(batches)
        resume = os.environ.get('AUDIT_RESUME') == 'true'
        completed_layers = get_completed_layers(audit_path) if resume else set()
        context_fixed = read_file(os.environ.get('AUDIT_FIXED_CONTEXT', os.path.join(context_dir, 'audit_context_fixed.txt')))
        system_prompt_path = '/tmp/opencode/audit_system_prompt.txt'
        system_prompt = read_file(system_prompt_path) if batch_files_pattern else f"""Eres un auditor senior. Audita este lote.

Contexto del proyecto:
{context_fixed[:4000]}

Responde con:
# Reporte Parcial
## Hallazgos
## Resumen
Responde únicamente en español."""

        log(f"\n{'='*60}")
        log(f" Auditoría de código por lotes")
        log(f" Total batches: {total}")
        log(f" Reanudación: {'SÍ' if resume else 'NO'}")
        log(f"{'='*60}\n")

        for idx, batch in enumerate(batches, 1):
            label = batch.get('layer') or batch.get('label', f'batch{idx}')
            files = batch.get('files', [])
            filepath = batch.get('file', '')

            if filepath:
                # Modo batch por archivo
                status = f"Batch {idx}/{total} — {label}"
                batch_label = label.replace('audit_batch_', '').replace('.txt', '')
            else:
                status = f"Batch {idx}/{total} — {label} ({len(files)} archivos)"
                batch_label = label

            if resume and label in completed_layers:
                log_progress(idx, total, f"⏭️  {status} [ya completado, saltando]")
                continue

            log_progress(idx, total, f"▶️  {status}")
            log(f"\n ▶️  {status}")

            if filepath:
                user_msg = read_file(filepath)
                if not user_msg.strip():
                    user_msg = "Lote vacío."
            else:
                code_content = ""
                for fpath in files:
                    content = read_file(fpath)
                    if content:
                        code_content += f"\n--- {fpath} ---\n{content}\n"
                user_msg = f"Capa: {label}\n\n{code_content}" if code_content.strip() else "Sin contenido."

            result = run_ollama_prompt(system_prompt, user_msg, model, num_predict)

            partial_path = os.path.join(context_dir, f'report_partial_{batch_label}.txt')
            with open(partial_path, 'w', encoding='utf-8') as f:
                f.write(result or "Sin contenido generado")

            save_checkpoint(audit_path, idx, total, batch_label, feature, result or "Sin contenido", global_progress)
            log(f" Checkpoint #{idx} guardado ({batch_label})")

        log_progress(total, total, "✅ Todos los batches completados")
        log("\n✅ Todos los batches completados.")
        log("▶️  Ejecuta con AUDIT_CONSOLIDATE=true para consolidar.")
        return

    # --- Modo normal (spec/plan/tasks) ---
    system_prompt = read_file('/tmp/opencode/audit_system_prompt.txt')
    context = read_file('/tmp/opencode/audit_context.txt')
    if not system_prompt or not context:
        log("ERROR: faltan audit_system_prompt.txt o audit_context.txt")
        sys.exit(1)

    log(" Ejecutando auditoría...")
    user_msg = f"## Artefactos a Auditar\n\nFeature: {feature}\nEtapa: {stage}\n\n{context}"
    result = run_ollama_prompt(system_prompt, user_msg, model, num_predict)
    print(result)

if __name__ == '__main__':
    main()
