"""Driver http: ejecuta requests HTTP con variables de contexto,
reintento automatico para errores transitorios y clasificacion de errores."""

import json
import re
import time
import urllib.request
import urllib.error
from typing import Any


class HttpResult:
    def __init__(self, success: bool, status: int = 0, body: Any = None,
                 error: str = '', duration: float = 0.0,
                 error_type: str = ''):
        self.success = success
        self.status = status
        self.body = body
        self.error = error
        self.duration = duration
        self.error_type = error_type



def _classify_error(status: int, error_str: str) -> str:
    if not status:
        low = error_str.lower()
        if 'refused' in low or 'timeout' in low or 'timed out' in low:
            return 'transient'
        return 'unknown'
    if 400 <= status < 500:
        return 'client'
    if status >= 500:
        return 'server'
    return 'unknown'


def _resolve_template(value: Any, context: dict) -> Any:
    """Reemplaza {{var}} en strings con valores del context_store."""
    if isinstance(value, str):
        def replacer(m):
            key = m.group(1)
            return str(context.get(key, m.group(0)))
        return re.sub(r'\{\{(\w+)\}\}', replacer, value)
    if isinstance(value, dict):
        return {k: _resolve_template(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_template(v, context) for v in value]
    return value


def _jsonpath_get(obj: Any, path: str) -> Any:
    """Resuelve un JSONPath simple: $.campo o $.campo.subcampo."""
    if not path.startswith('$.'):
        return None
    parts = path[2:].split('.')
    current = obj
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
        if current is None:
            return None
    return current


def _request(method: str, url: str, headers: dict, body_raw: Any,
             timeout: int) -> tuple[int, Any, float, str, str]:
    """Ejecuta un request HTTP. Retorna (status, body, duration, error, error_type)."""
    t0 = time.time()
    try:
        data = None
        if body_raw and method in ('POST', 'PUT', 'PATCH'):
            data = json.dumps(body_raw).encode('utf-8')
            headers.setdefault('Content-Type', 'application/json')

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        resp = urllib.request.urlopen(req, timeout=timeout)
        duration = time.time() - t0

        status = resp.status
        raw_body = resp.read().decode('utf-8')
        try:
            body = json.loads(raw_body)
        except json.JSONDecodeError:
            body = raw_body

        return status, body, duration, '', ''

    except urllib.error.HTTPError as e:
        duration = time.time() - t0
        try:
            body = json.loads(e.read().decode('utf-8'))
        except Exception:
            body = str(e)
        error_type = _classify_error(e.code, str(e))
        return e.code, body, duration, f'HTTP {e.code}: {e.reason}', error_type

    except urllib.error.URLError as e:
        duration = time.time() - t0
        error_str = f'Conexion fallida: {e.reason}'
        error_type = _classify_error(0, error_str)
        return 0, None, duration, error_str, error_type

    except Exception as e:
        duration = time.time() - t0
        return 0, None, duration, str(e)[:500], 'unknown'


def execute(step: dict, workdir: str, context: dict) -> HttpResult:
    """Ejecuta un paso type: http con reintento automatico para errores transitorios."""
    method = step.get('method', 'GET').upper()
    url = _resolve_template(step.get('url', ''), context)
    headers = _resolve_template(step.get('headers', {}), context)
    body_raw = _resolve_template(step.get('body'), context)
    timeout = step.get('timeout', 30)

    expected = step.get('expected', {})
    expected_status = expected.get('status')
    expected_contains = expected.get('body_contains', [])

    extract_rules = step.get('extract', [])

    status, body, duration, error, error_type = _request(
        method, url, headers, body_raw, timeout
    )

    # Reintento automatico (1 vez) solo para errores transitorios
    if error_type == 'transient':
        _transient_retries = step.get('_transient_retries', 0)
        if _transient_retries < 1:
            step['_transient_retries'] = _transient_retries + 1
            status, body, duration, error, error_type = _request(
                method, url, headers, body_raw, timeout
            )

    # Validar status esperado
    if error and status != expected_status:
        return HttpResult(False, status=status, body=body,
                          error=error, duration=duration,
                          error_type=error_type)
    if expected_status and status != expected_status:
        err_type = _classify_error(status, '')
        return HttpResult(False, status=status, body=body,
                          error=f'Status {status} (esperado {expected_status})',
                          duration=duration, error_type=err_type)
    # Validar body_verify: diccionario clave→valor esperado
    expected_verify = step.get('body_verify', {})
    if isinstance(expected_verify, dict) and expected_verify:
        if isinstance(body, dict):
            for key, expected_val in expected_verify.items():
                actual_val = _jsonpath_get(body, f'$.{key}') if '.' in key else body.get(key)
                if actual_val is None:
                    return HttpResult(False, status=status, body=body,
                                      error=f'Falta clave: {key}',
                                      duration=duration, error_type='client')
                if str(actual_val) != str(expected_val):
                    return HttpResult(False, status=status, body=body,
                                      error=f'{key}={actual_val} (esperado {expected_val})',
                                      duration=duration, error_type='client')
        elif isinstance(body, list):
            for item in body:
                if isinstance(item, dict):
                    for key, expected_val in expected_verify.items():
                        actual_val = _jsonpath_get(item, f'$.{key}') if '.' in key else item.get(key)
                        if actual_val is None:
                            return HttpResult(False, status=status, body=body,
                                              error=f'Falta clave en item: {key}',
                                              duration=duration, error_type='client')
                        if str(actual_val) != str(expected_val):
                            return HttpResult(False, status=status, body=body,
                                              error=f'Item: {key}={actual_val} (esperado {expected_val})',
                                              duration=duration, error_type='client')

    if expected_contains:
        if isinstance(body, dict):
            for field in expected_contains:
                if field not in body and not _jsonpath_get(body, field):
                    return HttpResult(False, status=status, body=body,
                                      error=f'Falta campo esperado: {field}',
                                      duration=duration, error_type='client')
        elif isinstance(body, list):
            for item in body:
                if isinstance(item, dict):
                    for field in expected_contains:
                        if field not in item and not _jsonpath_get(item, field):
                            return HttpResult(False, status=status, body=body,
                                              error=f'Falta campo esperado en item: {field}',
                                              duration=duration, error_type='client')
                else:
                    break

    # Extraer variables
    if extract_rules:
        resolved_body = body if isinstance(body, dict) else {}
        for rule in extract_rules:
            var_name = rule.get('var', '')
            path = rule.get('path', '')
            required = rule.get('required', True)
            value = _jsonpath_get(resolved_body, path) if resolved_body else None
            if value is not None:
                context[var_name] = value
            elif required:
                return HttpResult(False, status=status, body=body,
                                  error=f'No se pudo extraer {var_name} de {path}',
                                  duration=duration, error_type='client')
            else:
                print(f"  ⚠️  Advertencia: no se pudo extraer {var_name} de {path}")

    return HttpResult(True, status=status, body=body, duration=duration)
