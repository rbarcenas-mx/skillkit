"""Decisiones ante fallos: reglas locales por defecto, modelo solo como fallback."""

import sys

sys.stderr.reconfigure(line_buffering=True)

RETRY = "RETRY"
SKIP = "SKIP"
ABORT = "ABORT"


def decide(step_id: str, desc: str, error: str,
           error_type: str, status: int,
           retry_count: int, max_retries: int) -> str:
    """Decide que hacer ante un fallo usando reglas locales.
    
    Solo consulta al modelo como fallback si el tipo de error es 'unknown'.
    """
    # Error transitorio: reintentar si no se agotaron los reintentos
    if error_type == 'transient':
        if retry_count < max_retries:
            return RETRY
        return SKIP

    # Errores 4xx: datos o estado del cliente incorrectos
    if error_type == 'client':
        if status == 401:
            return ABORT
        if status in (404, 422, 400):
            return SKIP
        return SKIP

    # Errores 5xx: reintentar si quedan reintentos
    if error_type == 'server':
        if retry_count < max_retries:
            return RETRY
        return ABORT

    # Error desconocido: consultar al modelo como fallback
    return ask_model(step_id, desc, error)


def ask_model(step_id: str, desc: str, error: str) -> str:
    """Fallback: consulta al modelo solo para casos que las reglas no cubren."""
    import json
    import os
    import re
    import subprocess
    import sys

    sys.path.insert(0, os.environ["SKILLKIT_HOME"])
    from lib import resolve_model

    prompt = (
        f"Eres un ingeniero DevOps. Una ejecucion de QA fallo en un paso. Decide que hacer.\n\n"
        f"Paso: {step_id} — {desc}\n"
        f"Error: {error[:500]}\n"
        f"Tipo de error: desconocido (no coincide con reglas predefinidas)\n\n"
        f"Opciones:\n"
        f"- RETRY: reintentar el paso\n"
        f"- SKIP: saltar este paso y continuar\n"
        f"- ABORT: detener toda la ejecucion\n\n"
        f"Responde SOLO con una palabra: RETRY, SKIP o ABORT."
    )

    modelo = resolve_model("qa.execute")
    api_url = os.environ.get("OPENCODE_API_URL", "http://localhost:11434/v1")
    api_key = os.environ.get("OPENCODE_API_KEY", "")
    if not api_url.endswith("/chat/completions"):
        api_url = api_url.rstrip("/") + "/chat/completions"

    payload = {
        "model": modelo,
        "stream": False,
        "messages": [{"role": "user", "content": prompt}]
    }
    payload_path = '/tmp/opencode/qa_execute_decision_payload.json'
    os.makedirs('/tmp/opencode', exist_ok=True)
    with open(payload_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False)

    curl_cmd = [
        "curl", "-s", "-X", "POST", api_url,
        "-H", "Content-Type: application/json",
    ]
    if api_key:
        os.makedirs("/tmp/opencode", exist_ok=True)
        with open("/tmp/opencode/skillkit_headers.conf", "w") as _hf:
            _hf.write(f"Authorization: Bearer {api_key}\n")
        curl_cmd += ["-K", "/tmp/opencode/skillkit_headers.conf"]
    curl_cmd += ["-d", "@" + payload_path]

    result = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=120)

    if result.returncode != 0:
        return ABORT

    try:
        response = json.loads(result.stdout)
        content = response.get("choices", [{}])[0].get("message", {}).get("content", "").strip().upper()
        content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
        if 'RETRY' in content:
            return RETRY
        if 'SKIP' in content:
            return SKIP
        return ABORT
    except Exception:
        return ABORT
