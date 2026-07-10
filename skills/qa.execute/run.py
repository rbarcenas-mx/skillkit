#!/usr/bin/env python3
"""qa.execute — Orquestador de ejecucion de planes QA con drivers especializados.

Soporta pasos type: shell, http, stress.
Modo normal: ejecuta un plan individual.
Modo suite: ejecuta una secuencia de planes con dependencias y teardown.
"""

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Optional

sys.stderr.reconfigure(line_buffering=True)

import yaml
from lib.progress import show_progress
from lib.checkpoint import (
    append_log, format_success, format_failure, format_skip,
    write_summary, read_exec_log
)
from lib.decision import decide, ask_model, RETRY, SKIP, ABORT
from lib.recovery import ensure_docker

import importlib.util
_config = os.environ["SKILLKIT_HOME"]
_spec = importlib.util.spec_from_file_location(
    'opencode_lib',
    os.path.join(_config, 'lib', '__init__.py')
)
_opencode_lib = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_opencode_lib)
resolve_model = _opencode_lib.resolve_model

sys.stdout.reconfigure(line_buffering=True)

# ── Model banner ─────────────────────────────────────────────
MODELO_JUSTIFICACION = {
    "low": "Modelo local ejecutado via Ollama sin costo remoto. Adecuado para tareas de coordinacion y parseo de resultados estructurados.",
    "medium": "Modelo remoto con buena relacion costo/calidad. Suficiente para interpretar resultados de ejecucion y decidir accion ante fallos.",
    "high": "Modelo remoto de maxima calidad para coordinacion de ejecucion critica con decisions de retry/skip/abort.",
}

def print_model_banner():
    modo_raw = os.environ.get("OPENCODE_MODO", "?")
    modo_label = {"low": "Low", "medium": "Medium", "high": "High"}.get(modo_raw, modo_raw)
    modelo = os.environ.get("OPENCODE_MODEL", "?")
    proveedor = os.environ.get("OPENCODE_PROVEEDOR", "?")
    desc = os.environ.get("OPENCODE_MODEL_DESC", "")
    justificacion = MODELO_JUSTIFICACION.get(modo_raw, "")
    es_local = proveedor == "ollama"
    sys.stderr.write(f"\n{'='*54}\n")
    sys.stderr.write(f"  Modelo de Orquestacion\n")
    sys.stderr.write(f"{'─'*54}\n")
    sys.stderr.write(f"  Modo:       {modo_label}\n")
    sys.stderr.write(f"  Modelo:     {modelo} ({proveedor})\n")
    sys.stderr.write(f"  Tipo:       {'Local ($0)' if es_local else 'Remoto ($$)'}\n")
    sys.stderr.write(f"  Descripcion: {desc}\n")
    sys.stderr.write(f"  Justificacion: {justificacion}\n")
    sys.stderr.write(f"{'='*54}\n\n")


def print_token_table(total_plans):
    n = total_plans
    modo_raw = os.environ.get("OPENCODE_MODO", "?")
    modo_label = {"low": "Low", "medium": "Medium", "high": "High"}.get(modo_raw, modo_raw)
    proveedor = os.environ.get("OPENCODE_PROVEEDOR", "ollama")
    es_local = proveedor == "ollama"

    remoto_input = 2500 + 500 + 1000 + 2000 + 500

    if es_local:
        local_input = n * 1200
        local_think = n * 6000 if "deepseek-r1" in os.environ.get("OPENCODE_MODEL", "") else 0
        local_output = n * 2000
        local_total = local_input + local_think + local_output
    else:
        local_input = 0
        local_think = 0
        local_output = 0
        local_total = 0

    total_tokens = remoto_input + local_total
    pct_remoto = int(remoto_input * 100 / total_tokens) if total_tokens else 0
    pct_local = 100 - pct_remoto

    sys.stderr.write(f"\n{'='*54}\n")
    sys.stderr.write(f"  Tokens — {modo_label}\n")
    sys.stderr.write(f"{'─'*54}\n")
    sys.stderr.write(f"  {'Fuente':<30} {'Tokens est.':>12} {'Costo':>8}\n")
    sys.stderr.write(f"  {'─'*52}\n")
    sys.stderr.write(f"  {'Remoto — Cargar SKILL.md':<30} {2500:>12} {'$$':>8}\n")
    sys.stderr.write(f"  {'Remoto — Preguntar usuario':<30} {500:>12} {'$$':>8}\n")
    sys.stderr.write(f"  {'Remoto — Recolectar contexto':<30} {1000:>12} {'$$':>8}\n")
    sys.stderr.write(f"  {'Remoto — Leer resultados':<30} {2000:>12} {'$$':>8}\n")
    sys.stderr.write(f"  {'Remoto — Presentar resumen':<30} {500:>12} {'$$':>8}\n")
    sys.stderr.write(f"  {'Total remoto':<30} {remoto_input:>12} {'💰':>8}\n")
    sys.stderr.write(f"  {'':54}\n")
    if es_local:
        sys.stderr.write(f"  {'Local — Input x N':<30} {local_input:>12} {'$0':>8}\n")
        if local_think:
            sys.stderr.write(f"  {'Local — Razonamiento':<30} {local_think:>12} {'$0':>8}\n")
        sys.stderr.write(f"  {'Local — Output x N':<30} {local_output:>12} {'$0':>8}\n")
        sys.stderr.write(f"  {'Total local':<30} {local_total:>12} {'🆓':>8}\n")
    else:
        sys.stderr.write(f"  {'Local — (no aplica)'}\n")
        sys.stderr.write(f"  {'Total local':<30} {0:>12} {'—':>8}\n")
    sys.stderr.write(f"  {'─'*52}\n")
    sys.stderr.write(f"  {'% Remoto':<30} {pct_remoto:>11}%\n")
    sys.stderr.write(f"  {'% Local':<30} {pct_local:>11}%\n")
    if not es_local:
        sys.stderr.write(f"\n  Nota: Modo {modo_label} usa modelo remoto ({os.environ.get('OPENCODE_MODEL', '?')}).\n")
        sys.stderr.write(f"  En modo Low estas tareas serian locales ($0) via Ollama.\n")
    sys.stderr.write(f"{'='*54}\n")


# ── Contexto global del orquestador ────────────────────────
context_store: dict = {}  # variables extraidas entre pasos del mismo plan

# ── Parse del plan (formato hibrido Markdown + YAML) ───────
def parse_plan(filepath: str) -> dict:
    """Parsea un archivo de plan QA. Retorna header, steps, exec_log."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Parsear header (lineas Markdown: - **key**: value)
    header = {}
    for line in content.split('\n'):
        m = re.match(r'- \*\*(\w+)\*\*: (.+)', line)
        if m:
            header[m.group(1)] = m.group(2).strip()

    # Parsear pasos: bloques entre --- STEP (YAML puro)
    steps = []
    current_lines = []
    started = False
    broke = False
    for line in content.splitlines():
        if line.strip() == '## Execution Log' and started:
            if current_lines:
                try:
                    block = yaml.safe_load('\n'.join(current_lines))
                    if block and isinstance(block, dict):
                        steps.append(block)
                except yaml.YAMLError:
                    pass
            broke = True
            break
        if line.strip() == '--- STEP':
            if not started:
                started = True
                current_lines = []
            else:
                if current_lines:
                    try:
                        block = yaml.safe_load('\n'.join(current_lines))
                        if block and isinstance(block, dict):
                            steps.append(block)
                    except yaml.YAMLError:
                        pass
                    current_lines = []
            continue
        if started:
            current_lines.append(line)
    if not broke and current_lines and started:
        try:
            block = yaml.safe_load('\n'.join(current_lines))
            if block and isinstance(block, dict):
                steps.append(block)
        except yaml.YAMLError:
            pass

    # Parsear execution log existente
    exec_log = read_exec_log(filepath)

    return {
        'header': header,
        'steps': steps,
        'exec_log': exec_log,
        'filepath': filepath,
    }


def parse_suite_plan(filepath: str) -> dict:
    """Parsea un suite_plan.md: lista de planes, dependencias y teardown."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Parsear header
    header = {}
    for line in content.split('\n'):
        m = re.match(r'- \*\*(\w+)\*\*: (.+)', line)
        if m:
            header[m.group(1)] = m.group(2).strip()

    # Parsear tabla de planes: | orden | plan | dependencias | estado |
    plans = []
    in_table = False
    for line in content.split('\n'):
        if '## Teardown' in line:
            break
        if '| Orden | Plan | Dependencias | Estado |' in line:
            in_table = True
            continue
        if in_table and line.startswith('|') and '---' not in line:
            cols = [c.strip() for c in line.split('|') if c.strip()]
            if len(cols) >= 3:
                plans.append({
                    'orden': cols[0],
                    'plan': cols[1],
                    'dependencias': [d.strip() for d in cols[2].split(',') if d.strip() and d.strip() != '—'],
                    'estado': cols[3] if len(cols) > 3 else '⏳',
                })

    # Parsear teardown
    teardown = []
    in_teardown = False
    for line in content.split('\n'):
        if '## Teardown' in line:
            in_teardown = True
            continue
        if in_teardown and line.startswith('|') and '---' not in line:
            cols = [c.strip() for c in line.split('|') if c.strip()]
            if len(cols) >= 3 and cols[1] != 'Plan':
                teardown.append({
                    'orden': cols[0],
                    'comando': cols[2],
                })

    return {
        'header': header,
        'plans': plans,
        'teardown': teardown,
        'filepath': filepath,
    }


# ── Ejecucion de un paso ───────────────────────────────────
def execute_step(step: dict, workdir: str) -> tuple[bool, str, float, str, int]:
    """Ejecuta un paso delegando al driver segun type. Retorna (success, error, duration, error_type, status)."""
    step_type = step.get('type', 'shell')

    if step_type == 'shell':
        from drivers.shell import execute as run_shell
        result = run_shell(step, workdir, context_store)
        return result.success, result.error, result.duration, result.error_type, 0

    elif step_type == 'http':
        from drivers.http import execute as run_http
        result = run_http(step, workdir, context_store)
        error = result.error
        if not result.success and result.status:
            error = f'HTTP {result.status}: {error}'
        return result.success, error, result.duration, result.error_type, result.status

    elif step_type == 'stress':
        from drivers.stress import execute as run_stress
        result = run_stress(step, workdir, context_store)
        return result.success, result.error, result.duration, result.error_type, 0

    else:
        return False, f'Tipo de paso desconocido: {step_type}', 0.0, 'unknown', 0


# ── Ejecucion de un plan individual ────────────────────────
def run_plan(plan_path: str, workdir: str) -> dict:
    """Ejecuta un plan QA individual. Retorna stats: {completed, failed, skipped, total}."""
    global context_store
    context_store = {}  # reset entre planes

    resolve_model("qa.execute")
    print_model_banner()

    plan = parse_plan(plan_path)
    steps = plan['steps']
    exec_log = plan['exec_log']
    total = len(steps)
    completed = len([e for e in exec_log if '✅' in e])
    failed = 0
    skipped = 0
    retry_counts: dict = {}

    show_progress(completed, total)

        # Pre-flight: Docker si hay pasos shell que lo requieran
    docker_steps = [s for s in steps if s.get('type', 'shell') == 'shell' and 'docker' in s.get('command', '').lower()]
    if docker_steps:
        print(f"\n{'='*54}")
        print(f"  🐳 Pre-flight: {len(docker_steps)} pasos requieren Docker — verificando disponibilidad")
        if not ensure_docker():
            print(f"  ⚠️  Docker no disponible — los pasos Docker pueden fallar")

    for step in steps:
        sid = step.get('id', 'UNKNOWN')
        desc = step.get('desc', '')
        step_type = step.get('type', 'shell')
        is_checkpoint = step.get('checkpoint', False)
        dangerous = step.get('dangerous', False)
        max_retries = step.get('max_retries', 1)

        # Tracking de reintentos por paso
        retry_count = retry_counts.get(sid, 0)

        # Ya completado?
        already_done = any(sid in e and '✅' in e for e in exec_log)
        if already_done:
            print(f"\n  ⏭️  {sid}: {desc} — ya completado en ejecucion anterior")
            continue

        # Fallo previo?
        already_failed = any(sid in e and '❌' in e for e in exec_log)
        if already_failed:
            print(f"\n  ⚠️  {sid}: {desc} — fallo en ejecucion anterior, reintentar?")

        # Mostrar paso
        danger_label = "⚠️ PELIGROSO" if dangerous else ""
        cp_label = "📌 checkpoint" if is_checkpoint else ""
        print(f"\n{'='*54}")
        print(f"  ▶ {sid}: {desc}")
        print(f"  Tipo: {step_type} {'| ' + danger_label if danger_label else ''} {'| ' + cp_label if cp_label else ''}")
        print(f"{'─'*54}")

        success, error, duration, error_type, status = execute_step(step, workdir)

        if success:
            log_success(sid, desc, duration, is_checkpoint, plan_path)
            completed += 1
            show_progress(completed, total)
            print(f"  ✅ Paso completado en {duration:.1f}s")
        else:
            failed += 1
            print(f"  ❌ Error: {error[:200]}")
            print(f"  Tipo error: {error_type}, Status: {status}")

            # Auto-recovery: si es error de Docker
            if 'docker' in error.lower() or 'daemon' in error.lower():
                print(f"  🐳 Error de Docker detectado — intentando recuperacion...")
                if ensure_docker():
                    print(f"  🔄 Recovery exitoso — reintentando paso...")
                    success2, error2, duration2, _, _ = execute_step(step, workdir)
                    if success2:
                        log_success(sid, desc, duration2, is_checkpoint, plan_path)
                        completed += 1
                        failed -= 1
                        show_progress(completed, total)
                        print(f"  ✅ Paso completado en {duration2:.1f}s (post-recovery)")
                        continue
                    else:
                        print(f"  ❌ Recovery fallo")

            log_failure(sid, desc, duration, error, plan_path)

            # Decision: reglas locales o modelo como fallback
            if error_type == 'unknown':
                decision = ask_model(sid, desc, error)
            else:
                decision = decide(sid, desc, error, error_type, status,
                                  retry_count, max_retries)

            if decision == RETRY and retry_count < max_retries:
                retry_counts[sid] = retry_count + 1
                print(f"  🔄 Decision: RETRY (intento {retry_count + 1}/{max_retries}) — reintentando...")
                success2, error2, duration2, _, _ = execute_step(step, workdir)
                if success2:
                    log_success(sid, desc, duration2, is_checkpoint, plan_path)
                    completed += 1
                    failed -= 1
                    show_progress(completed, total)
                    print(f"  ✅ Paso completado en {duration2:.1f}s (reintento)")
                else:
                    print(f"  ❌ Reintento fallo — saltando paso")
                    log_skip(sid, desc, plan_path)
                    skipped += 1
            elif decision == SKIP:
                log_skip(sid, desc, plan_path)
                skipped += 1
                print(f"  ⏭️  Decision: SKIP — omitiendo paso")
            else:  # ABORT
                print(f"  🛑 Decision: ABORT — deteniendo ejecucion")
                break

    # Resumen del plan
    show_progress(total, total)
    print(f"\n{'='*54}")
    print(f"  Resumen — {os.path.basename(plan_path)}")
    print(f"{'─'*54}")
    print(f"  Completados:   {completed}  ✅")
    print(f"  Fallidos:      {failed}  ❌")
    print(f"  Saltados:      {skipped}  ⏭️")
    print(f"{'═'*54}")

    write_summary(plan_path, completed, failed, skipped, total)
    print_token_table(1)

    return {
        'completed': completed,
        'failed': failed,
        'skipped': skipped,
        'total': total,
    }


# ── Helpers de log (wrappers de checkpoint) ────────────────
def log_success(sid: str, desc: str, duration: float, is_cp: bool, plan_path: str):
    entry = format_success(sid, desc, duration, is_cp)
    append_log(plan_path, entry)


def log_failure(sid: str, desc: str, duration: float, error: str, plan_path: str):
    entry = format_failure(sid, desc, duration, error)
    append_log(plan_path, entry)


def log_skip(sid: str, desc: str, plan_path: str):
    entry = format_skip(sid, desc)
    append_log(plan_path, entry)


# ── Modo suite ─────────────────────────────────────────────
def run_suite(suite_path: str, workdir: str) -> None:
    """Ejecuta una suite de planes QA con dependencias y teardown."""
    suite = parse_suite_plan(suite_path)
    plans = suite['plans']
    teardown_steps = suite.get('teardown', [])
    plan_results = {}  # plan_name -> resultado de ejecucion

    resolve_model("qa.execute")
    print_model_banner()

    print(f"\n{'#'*54}")
    print(f"# Suite QA — {len(plans)} planes")
    print(f"{'#'*54}")

    for item in plans:
        plan_name = item['plan']
        deps = item['dependencias']
        plan_full_path = os.path.join(workdir, plan_name)

        if not os.path.exists(plan_full_path):
            print(f"\n❌ Plan no encontrado: {plan_full_path}")
            plan_results[plan_name] = {'failed': 1, 'completed': 0, 'total': 0}
            continue

        # Verificar dependencias
        deps_ok = True
        for dep in deps:
            dep_key = dep if dep.startswith('qa/') else ''
            if dep_key in plan_results:
                if plan_results[dep_key]['failed'] > 0:
                    print(f"\n⚠️  Dependencia fallida: {dep}. Saltando {plan_name}.")
                    deps_ok = False
                    break
            else:
                # Dependencia por nombre (ej: 'infra' -> buscar plan con 'infra' en nombre)
                found = False
                for k, v in plan_results.items():
                    if dep.lower() in k.lower():
                        found = True
                        if v['failed'] > 0:
                            print(f"\n⚠️  Dependencia fallida: {k}. Saltando {plan_name}.")
                            deps_ok = False
                        break

        if not deps_ok:
            plan_results[plan_name] = {'failed': 1, 'completed': 0, 'total': 0}
            continue

        print(f"\n{'─'*54}")
        print(f"  ▶ Ejecutando plan: {plan_name}")
        print(f"{'─'*54}")

        result = run_plan(plan_full_path, workdir)
        plan_results[plan_name] = result

        if result['failed'] > 0:
            total_steps = result.get('total', 1)
            pct_failed = result['failed'] * 100 / total_steps
            if pct_failed > 50:
                print(f"\n  🛑 Suite abortada — {result['failed']}/{total_steps} pasos fallidos ({pct_failed:.0f}%)")
                break
            else:
                print(f"\n  ➡ Continuando suite — {result['completed']}/{total_steps} pasos exitosos")

    # Teardown
    if teardown_steps:
        print(f"\n{'='*54}")
        print(f"  🧹 Teardown — limpiando infraestructura")
        print(f"{'─'*54}")
        for td in teardown_steps:
            cmd = td.get('comando', '')
            if cmd:
                print(f"  ▶ Ejecutando: {cmd}")
                try:
                    result = subprocess.run(cmd, shell=True, capture_output=True,
                                            text=True, timeout=60, cwd=workdir)
                    if result.returncode == 0:
                        print(f"  ✅ Teardown completado")
                    else:
                        print(f"  ⚠️  Teardown: {result.stderr[:200]}")
                except Exception as e:
                    print(f"  ⚠️  Teardown: {e}")

    # Resumen consolidado
    total_with_fails = sum(1 for r in plan_results.values() if r.get('failed', 0) > 0)
    total_ok = len(plan_results) - total_with_fails
    print(f"\n{'#'*54}", flush=True)
    print(f"# Resumen Consolidado de Suite", flush=True)
    print(f"{'─'*54}", flush=True)
    print(f"  Total planes:    {len(plans)}", flush=True)
    print(f"  Planes OK:       {total_ok}  ✅", flush=True)
    print(f"  Planes con fallo:{total_with_fails}  ⚠️", flush=True)
    print(f"{'─'*54}")
    for name, result in plan_results.items():
        icon = '✅' if result['failed'] == 0 else '⚠️'
        print(f"  {icon} {name}: {result['completed']}/{result['total']} pasos exitosos")

    print_token_table(len(plans))

# ── Main ───────────────────────────────────────────────────
def main():
    plan_file = os.environ.get('QA_PLAN_FILE', '')
    workdir = os.environ.get('WORKDIR', '.')

    if not plan_file or not os.path.exists(plan_file):
        print(f"ERROR: Archivo de plan no encontrado: {plan_file}", file=sys.stderr)
        sys.exit(1)

    os.chdir(workdir)
    os.makedirs('/tmp/opencode', exist_ok=True)

    # Detectar si es suite o plan individual por nombre de archivo
    if 'suite' in plan_file.lower():
        run_suite(plan_file, workdir)
    else:
        run_plan(plan_file, workdir)

    print()  # newline final


if __name__ == '__main__':
    main()
