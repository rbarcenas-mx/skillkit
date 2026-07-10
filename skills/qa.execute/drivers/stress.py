"""Driver stress: ejecuta pruebas de carga con autocannon/hey/wrk."""

import json
import os
import re
import subprocess
import time
from typing import Optional


class StressResult:
    def __init__(self, success: bool, tool: str = '', stats: dict = None,
                 error: str = '', duration: float = 0.0, error_type: str = ''):
        self.success = success
        self.tool = tool
        self.stats = stats or {}
        self.error = error
        self.duration = duration
        self.error_type = error_type


def _find_tool() -> Optional[str]:
    """Encuentra una herramienta de estres disponible. Preferencia: autocannon > hey > wrk."""
    for tool in ['autocannon', 'hey', 'wrk']:
        try:
            result = subprocess.run([tool, '--version'], capture_output=True, timeout=5)
            if result.returncode == 0:
                return tool
        except FileNotFoundError:
            continue
    return None


def _ensure_tool() -> Optional[str]:
    """Asegura que haya una herramienta disponible, instalando autocannon si es necesario."""
    tool = _find_tool()
    if tool:
        return tool
    print("  📦 Instalando autocannon...")
    try:
        subprocess.run(['npm', 'install', '-g', 'autocannon'],
                       capture_output=True, text=True, timeout=60)
        if _find_tool() == 'autocannon':
            return 'autocannon'
    except Exception as e:
        print(f"  ⚠️  No se pudo instalar autocannon: {e}")
    return None


def _parse_autocannon(output: str) -> dict:
    """Parsea el output de autocannon a stats."""
    stats = {}
    for line in output.split('\n'):
        m = re.match(r'(\d+)\s*(2xx|4xx|5xx|non 2xx)\s*responses', line.strip())
        if m:
            stats['success_rate'] = float(m.group(1)) if '2xx' in line else 0
        if 'requests/s' in line:
            m = re.match(r'(\d+\.?\d*)\s*req/s', line.strip())
            if m:
                stats['req_per_sec'] = float(m.group(1))
        if 'latency' in line.lower() and 'p95' in line.lower():
            m = re.search(r'p95.*?(\d+\.?\d*)ms', line.lower())
            if m:
                stats['p95_ms'] = float(m.group(1))
    return stats


def _parse_hey(output: str) -> dict:
    """Parsea el output de hey a stats."""
    stats = {}
    m = re.search(r'Requests/sec:\s*([\d.]+)', output)
    if m:
        stats['req_per_sec'] = float(m.group(1))
    m = re.search(r'(\d+)\s*responses.*\[200\]', output)
    if m:
        total_m = re.search(r'Total:\s*(\d+)', output)
        if total_m:
            total = float(total_m.group(1))
            ok = float(m.group(1))
            stats['success_rate'] = round((ok / total) * 100, 1) if total > 0 else 0
    return stats


def execute(step: dict, workdir: str, context: dict) -> StressResult:
    """Ejecuta un paso type: stress."""
    tool = _ensure_tool()
    if not tool:
        return StressResult(False, error='No se encontro herramienta de estres (autocannon/hey/wrk)', error_type='client')

    target = step.get('target', '')
    method = step.get('method', 'GET')
    n = step.get('n', 100)
    concurrency = step.get('concurrency', 10)
    expected = step.get('expected', {})

    t0 = time.time()

    if tool == 'autocannon':
        cmd = ['autocannon', '-m', method, '-c', str(concurrency), '-a', str(n), target]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=workdir)
            duration = time.time() - t0
            stats = _parse_autocannon(result.stdout)
            if result.returncode != 0:
                return StressResult(False, tool=tool, stats=stats,
                                    error=result.stderr[:500], duration=duration,
                                    error_type='client')
        except subprocess.TimeoutExpired:
            duration = time.time() - t0
            return StressResult(False, tool=tool, error='TIMEOUT', duration=duration,
                                error_type='transient')
        except Exception as e:
            duration = time.time() - t0
            return StressResult(False, tool=tool, error=str(e)[:500], duration=duration,
                                error_type='unknown')

    elif tool == 'hey':
        cmd = ['hey', '-n', str(n), '-c', str(concurrency), '-m', method, target]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=workdir)
            duration = time.time() - t0
            stats = _parse_hey(result.stdout)
            if result.returncode != 0:
                return StressResult(False, tool=tool, stats=stats,
                                    error=result.stderr[:500], duration=duration,
                                    error_type='client')
        except subprocess.TimeoutExpired:
            duration = time.time() - t0
            return StressResult(False, tool=tool, error='TIMEOUT', duration=duration,
                                error_type='transient')
        except Exception as e:
            duration = time.time() - t0
            return StressResult(False, tool=tool, error=str(e)[:500], duration=duration,
                                error_type='unknown')

    else:
        return StressResult(False, tool=tool, error=f'Herramienta no soportada: {tool}',
                            error_type='client')

    # Validar contra umbrales esperados
    p95_max = expected.get('p95_ms')
    min_success_rate = expected.get('success_rate')

    if p95_max and stats.get('p95_ms', 0) > p95_max:
        return StressResult(
            False, tool=tool, stats=stats, duration=duration, error_type='client',
            error=f'P95 ({stats["p95_ms"]}ms) supera umbral ({p95_max}ms)'
        )
    if min_success_rate and stats.get('success_rate', 0) < min_success_rate:
        return StressResult(
            False, tool=tool, stats=stats, duration=duration, error_type='client',
            error=f'Success rate ({stats["success_rate"]}%) bajo umbral ({min_success_rate}%)'
        )

    return StressResult(True, tool=tool, stats=stats, duration=duration)
