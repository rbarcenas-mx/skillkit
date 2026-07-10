"""Driver shell: ejecuta comandos via subprocess con resolucion de {{var}}."""

import os
import re
import subprocess
import time
from typing import Any, Optional

from lib.recovery import ensure_docker


class ShellResult:
    def __init__(self, success: bool, error: str = '', output: str = '',
                 duration: float = 0.0, docker_recovered: bool = False,
                 error_type: str = ''):
        self.success = success
        self.error = error
        self.output = output
        self.duration = duration
        self.docker_recovered = docker_recovered
        self.error_type = error_type


def _resolve_template(value: str, context: dict) -> str:
    """Reemplaza {{var}} en strings con valores del context_store."""
    def replacer(m):
        key = m.group(1)
        return str(context.get(key, m.group(0)))
    return re.sub(r'\{\{(\w+)\}\}', replacer, value)


def execute(step: dict, workdir: str, context: dict) -> ShellResult:
    """Ejecuta un paso type: shell."""
    command = _resolve_template(step.get('command', ''), context)
    if not command:
        return ShellResult(False, error='Campo command vacio', error_type='client')

    t0 = time.time()
    step_timeout = step.get("timeout", 300)
    env = os.environ.copy()
    bin_path = os.path.join(workdir, 'node_modules', '.bin')
    if os.path.isdir(bin_path):
        env['PATH'] = f"{bin_path}:{env.get('PATH', '')}"
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=step_timeout,
            cwd=workdir,
            env=env,
        )
        duration = time.time() - t0

        if result.returncode == 0:
            return ShellResult(True, output=result.stdout.strip(), duration=duration)

        error_msg = result.stderr[:200] or result.stdout[:200]

        # Auto-recovery si es error de Docker
        if any(kw in error_msg.lower() for kw in ['docker', 'daemon', 'cannot connect']):
            print(f"  🐳 Detectado error de Docker. Intentando recuperacion...")
            if ensure_docker():
                print(f"  🔄 Reintentando (post-recovery)...")
                t0 = time.time()
                result = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=step_timeout,
                    cwd=workdir
                )
                duration = time.time() - t0
                if result.returncode == 0:
                    return ShellResult(True, output=result.stdout.strip(),
                                       duration=duration, docker_recovered=True)
                error_msg = result.stderr[:200] or result.stdout[:200]

        return ShellResult(False, error=error_msg, duration=duration,
                           error_type='client')

    except subprocess.TimeoutExpired:
        duration = time.time() - t0
        return ShellResult(False, error='TIMEOUT (>300s)', duration=duration,
                           error_type='transient')
    except Exception as e:
        duration = time.time() - t0
        return ShellResult(False, error=str(e)[:500], duration=duration,
                           error_type='unknown')
