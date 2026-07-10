"""Recuperacion automatica de Docker."""

import os
import subprocess
import time


def ensure_docker() -> bool:
    """Intenta iniciar Docker si no esta disponible. Retorna True si funciona."""
    docker_bin = "docker"

    try:
        subprocess.run([docker_bin, "--version"], capture_output=True, timeout=10)
    except FileNotFoundError:
        win_docker = "/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"
        if os.path.exists(win_docker):
            docker_bin = win_docker
            print(f"  🐳 Usando Docker CLI de Windows: {docker_bin}")
        else:
            print("  🐳 Docker CLI no encontrado. Intentando iniciar daemon...")
    else:
        result = subprocess.run([docker_bin, "info"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return True
        print("  🐳 Docker daemon no responde. Intentando iniciar...")

    for cmd in [
        "sudo service docker start 2>/dev/null",
        "sudo dockerd &>/dev/null &",
    ]:
        try:
            subprocess.run(cmd, shell=True, capture_output=True, timeout=10)
            time.sleep(3)
            probe = subprocess.run([docker_bin, "info"], capture_output=True, timeout=10)
            if probe.returncode == 0:
                print("  ✅ Docker iniciado correctamente.")
                return True
        except Exception:
            continue

    if os.path.exists("/proc/sys/fs/binfmt_misc/WSLInterop"):
        print("  🪟 WSL detectado. Intentando abrir Docker Desktop en Windows...")
        try:
            subprocess.Popen(
                'cmd.exe /c start "Docker Desktop" "C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe"',
                shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            print("  ⏳ Esperando a que Docker Desktop inicie (20s)...")
            time.sleep(20)
            probe = subprocess.run([docker_bin, "info"], capture_output=True, timeout=10)
            if probe.returncode == 0:
                print("  ✅ Docker Desktop iniciado correctamente desde Windows.")
                return True
        except Exception as e:
            print(f"  ⚠️  No se pudo abrir Docker Desktop: {e}")

    print("  ⚠️  No se pudo iniciar Docker. Inicia Docker Desktop manualmente.")
    return False
