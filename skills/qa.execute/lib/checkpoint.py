"""Checkpoint: registro persistente de cada paso en el plan."""

import os
from datetime import datetime, timezone


def append_log(plan_path: str, entry: str) -> None:
    """Agrega una entrada al Execution Log del plan."""
    with open(plan_path, 'a', encoding='utf-8') as f:
        f.write(entry + '\n')


def format_success(step_id: str, desc: str, duration: float, is_checkpoint: bool) -> str:
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    prefix = '📌 ' if is_checkpoint else ''
    return f'{prefix}{step_id} {ts} ✅ ({duration:.1f}s) {desc}'


def format_failure(step_id: str, desc: str, duration: float, error: str) -> str:
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    return f'{step_id} {ts} ❌ ({duration:.1f}s) {desc} — {error[:500]}'


def format_skip(step_id: str, desc: str) -> str:
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    return f'{step_id} {ts} ⏭️ {desc}'


def write_summary(plan_path: str, completed: int, failed: int, skipped: int, total: int) -> None:
    estado = '✅ Completado' if failed == 0 and skipped == 0 else '⚠️ Con incidencias'
    summary = (
        f'\n### Resumen final\n\n'
        f'**Estado:** {estado} — {completed}/{total} pasos exitosos\n'
        f'**Fallidos:** {failed}  **Saltados:** {skipped}\n'
    )
    append_log(plan_path, summary)


def read_exec_log(plan_path: str) -> list[str]:
    """Lee las entradas del Execution Log desde el archivo del plan."""
    if not os.path.exists(plan_path):
        return []
    entries = []
    in_log = False
    with open(plan_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip().startswith('## Execution Log'):
                in_log = True
                continue
            if in_log:
                stripped = line.strip()
                if stripped.startswith('### Resumen final'):
                    entries.append(stripped)
                    continue
                if stripped and not stripped.startswith('##'):
                    entries.append(stripped)
                elif stripped.startswith('##'):
                    break
    return entries
