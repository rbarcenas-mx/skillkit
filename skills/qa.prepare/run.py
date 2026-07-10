#!/usr/bin/env python3
"""qa.prepare — Interactive QA plan generation by type.
Model resolved via resolve_model('qa.prepare') according to TOKEN_BUDGET.

Plan types: infra, unit, flow, stress, scale.
Generates one or more plans according to QA_PLAN_TYPES, with per-type cache and validation.
If multiple types, also generates suite_plan.md.
"""

import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime

sys.stderr.reconfigure(line_buffering=True)

sys.path.insert(0, os.environ["SKILLKIT_HOME"])
from lib import resolve_model

WORKDIR = os.environ.get('WORKDIR', '.')
QA_PROJECT_CONTEXT = os.environ.get('QA_PROJECT_CONTEXT', '{}')
QA_EXISTING_PLANS = os.environ.get('QA_EXISTING_PLANS', '')
QA_PLAN_TYPES = os.environ.get('QA_PLAN_TYPES', 'infra,unit,flow').split(',')
QA_STRESS_LEVEL = os.environ.get('QA_STRESS_LEVEL', 'medio') if 'stress' in QA_PLAN_TYPES else ''
QA_SCALE_WORKERS = int(os.environ.get('QA_SCALE_WORKERS', '4')) if 'scale' in QA_PLAN_TYPES else 0
QA_FLOW_USERS = int(os.environ.get('QA_FLOW_USERS', '2'))
QA_FLOW_MANDADOS = int(os.environ.get('QA_FLOW_MANDADOS', '1'))
QA_FLOW_VERIFICACION = os.environ.get('QA_FLOW_VERIFICACION', 'automatica')
QA_FLOW_ADMIN_EXISTS = os.environ.get('QA_FLOW_ADMIN_EXISTS', 'no')
QA_FLOW_DENUNCIAS = os.environ.get('QA_FLOW_DENUNCIAS', 'si')
QA_FLOW_ADMIN_ENDPOINTS = os.environ.get('QA_FLOW_ADMIN_ENDPOINTS', 'si')

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))

def print_model_banner(task_desc):
    mode_raw = os.environ.get("OPENCODE_MODO", "?")
    mode_label = {"low": "Low", "medium": "Medium", "high": "High"}.get(mode_raw, mode_raw)
    model = os.environ.get("OPENCODE_MODEL", "?")
    provider = os.environ.get("OPENCODE_PROVEEDOR", "?")
    desc = os.environ.get("OPENCODE_MODEL_DESC", "")
    sys.stderr.write(f"\n{'='*54}\n")
    sys.stderr.write(f"  Model Router\n")
    sys.stderr.write(f"{'-'*54}\n")
    sys.stderr.write(f"  Mode:     {mode_label}\n")
    sys.stderr.write(f"  Model:    {model} ({provider})\n")
    sys.stderr.write(f"  Reason:   {desc}\n")
    sys.stderr.write(f"  Task:     {task_desc}\n")
    sys.stderr.write(f"{'='*54}\n\n")

TEMPLATES_DIR = os.path.join(SKILL_DIR, 'templates')
PROGRESS_FILE = '/tmp/opencode/qa_prepare_progress.json'
os.makedirs('/tmp/opencode', exist_ok=True)

STRESS_CONFIG = {
    'ligero': {'n': 100, 'c': 10, 'p95': 300, 'rate': 99},
    'medio':  {'n': 500, 'c': 50, 'p95': 500, 'rate': 98},
    'pesado': {'n': 2000, 'c': 100, 'p95': 1000, 'rate': 95},
}

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {}

def save_progress(plan_type, status):
    progress = load_progress()
    progress[plan_type] = status
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(progress, f)

def spinner_while_waiting(stop_event, label="Processing"):
    frames = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
    i = 0
    t0 = time.time()
    while not stop_event.is_set():
        elapsed = time.time() - t0
        sys.stderr.write(f'\r  {frames[i % len(frames)]} {label} ({elapsed:.0f}s)   ')
        sys.stderr.flush()
        i += 1
        time.sleep(0.15)
    elapsed = time.time() - t0
    sys.stderr.write(f'\r  {"\u2705"} {label} — completed in {elapsed:.1f}s   \n')
    sys.stderr.flush()

def get_api_key():
    auth_path = os.path.expanduser("~/.local/share/opencode/auth.json")
    try:
        with open(auth_path) as f:
            auth = json.load(f)
        return auth.get("opencode-go", {}).get("key", "")
    except (FileNotFoundError, json.JSONDecodeError):
        return os.environ.get("OPENCODE_API_KEY", "")

def call_model(system_prompt, user_message):
    model = os.environ.get("OPENCODE_MODEL")
    if not model:
        resolve_model("qa.prepare")
        model = os.environ.get("OPENCODE_MODEL", "")
    provider = os.environ.get("OPENCODE_PROVEEDOR", "ollama")
    api_url = os.environ.get("OPENCODE_API_URL", "http://localhost:11434/v1")

    if not api_url.endswith("/chat/completions"):
        api_url = api_url.rstrip("/") + "/chat/completions"

    payload = {
        "model": model,
        "stream": False,
        "max_tokens": 16384,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]
    }
    payload_path = '/tmp/opencode/qa_prepare_payload.json'
    with open(payload_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False)

    curl_cmd = [
        "curl", "-s", "-X", "POST", api_url,
        "-H", "Content-Type: application/json",
    ]
    if provider != "ollama":
        api_key = get_api_key()
        if api_key:
            os.makedirs("/tmp/opencode", exist_ok=True)
            with open("/tmp/opencode/skillkit_headers.conf", "w") as _hf:
                _hf.write(f"Authorization: Bearer {api_key}\n")
            curl_cmd += ["-K", "/tmp/opencode/skillkit_headers.conf"]
    curl_cmd += ["-d", "@" + payload_path]

    result = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=600)

    if result.returncode != 0:
        print(f"ERROR calling model: {result.stderr}", file=sys.stderr)
        return ''

    try:
        response = json.loads(result.stdout)
        if "error" in response:
            print(f"ERROR API: {json.dumps(response['error'], ensure_ascii=False)[:200]}", file=sys.stderr)
            return ''
        msg = response.get("choices", [{}])[0].get("message", {})
        content = msg.get("content", "")
        reasoning = msg.get("reasoning_content", "")
        if not content and reasoning:
            print("  Model produced reasoning only, no final response", file=sys.stderr)
            content = reasoning
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        print(f"ERROR parsing response: {e}", file=sys.stderr)
        return ''

    content = re.sub(r'ILD.*?XXX', '', content, flags=re.DOTALL)
    return content.strip()

def load_template(plan_type):
    template_path = os.path.join(TEMPLATES_DIR, f'{plan_type}_prompt.md')
    if not os.path.exists(template_path):
        return None
    with open(template_path, 'r', encoding='utf-8') as f:
        return f.read()

def load_api_contract():
    """Search and load API contract from specs/*/contracts/api.md"""
    import glob as g
    patterns = [
        os.path.join(WORKDIR, 'specs', '*', 'contracts', 'api.md'),
        os.path.join(WORKDIR, 'specs', '*', 'api.md'),
        os.path.join(WORKDIR, 'docs', 'api.md'),
        os.path.join(WORKDIR, 'API.md'),
    ]
    for pattern in patterns:
        matches = g.glob(pattern)
        if matches:
            with open(matches[0], 'r', encoding='utf-8') as f:
                content = f.read()
            print(f"  API contract loaded: {matches[0]} ({len(content)} chars)", file=sys.stderr)
            return content
    print("  No API contract found (specs/*/contracts/api.md)", file=sys.stderr)
    return "No API contract available. Use project context fields."

def validate_plan(plan_text, plan_type):
    """Returns (ok, list_of_errors). Validates YAML format, structure and critical rules."""
    import yaml
    errors = []

    valid_starts = {
        'infra': '# Plan de Validacion de Infraestructura',
        'unit': '# Plan de Validacion de Codigo',
        'flow': '# Plan de Validacion de Flujo Operativo',
        'stress': '# Plan de Validacion de Estres',
        'scale': '# Plan de Validacion de Escalamiento',
    }
    expected_start = valid_starts.get(plan_type, '# Plan de Validacion')
    if not plan_text.strip().startswith(expected_start):
        errors.append(f"Missing header '{expected_start}'")

    required = ['## README', '## Checklist de Escenarios',
                '## Pasos de Ejecucion', '## Execution Log']
    for section in required:
        if section not in plan_text:
            errors.append(f"Missing section: {section}")

    if '--- STEP' not in plan_text:
        errors.append("No steps found (--- STEP)")

    in_step_block = False
    step_started = False
    for line in plan_text.splitlines():
        if line.strip() == '--- STEP':
            in_step_block = True
            step_started = True
            continue
        if '## Execution Log' in line and step_started:
            in_step_block = False
            continue
        if not in_step_block and line.strip() == '---':
            errors.append("Loose `---` separator outside STEP — breaks YAML parser. Use `--- STEP` only.")
            break

    steps = []
    current_lines = []
    started = False
    broke = False
    for line in plan_text.splitlines():
        if '## Execution Log' in line and started:
            if current_lines:
                try:
                    raw = '\n'.join(current_lines)
                    step = yaml.safe_load(raw)
                    if isinstance(step, dict) and 'id' in step:
                        steps.append(step)
                except yaml.YAMLError as e:
                    sid = 'unknown'
                    for l in current_lines[:5]:
                        m = re.match(r'id:\s*(\S+)', l)
                        if m:
                            sid = m.group(1)
                            break
                    errors.append(f"Invalid YAML in step {sid}: {str(e)[:100]}")
            broke = True
            break
        if line.strip() == '--- STEP':
            if not started:
                started = True
                current_lines = []
            else:
                if current_lines:
                    try:
                        raw = '\n'.join(current_lines)
                        step = yaml.safe_load(raw)
                        if isinstance(step, dict) and 'id' in step:
                            steps.append(step)
                    except yaml.YAMLError as e:
                        sid = 'unknown'
                        for l in current_lines[:5]:
                            m = re.match(r'id:\s*(\S+)', l)
                            if m:
                                sid = m.group(1)
                                break
                        errors.append(f"Invalid YAML in step {sid}: {str(e)[:100]}")
                    current_lines = []
            continue
        if started:
            current_lines.append(line)
    if not broke and current_lines and started:
        try:
            raw = '\n'.join(current_lines)
            step = yaml.safe_load(raw)
            if isinstance(step, dict) and 'id' in step:
                steps.append(step)
        except yaml.YAMLError as e:
            errors.append(f"Invalid YAML in final step: {str(e)[:100]}")

    for step in steps:
        sid = step.get('id', '?')
        if 'type' not in step:
            errors.append(f"Step {sid}: missing type")
        if 'desc' not in step:
            errors.append(f"Step {sid}: missing desc")

        stype = step.get('type', '')
        if stype == 'shell':
            cmd = step.get('command', '')
            if not cmd:
                errors.append(f"Step {sid} type=shell: missing command")
            if cmd:
                if 'npx prisma db seed' in cmd:
                    errors.append(f"Step {sid}: 'npx prisma db seed' does NOT exist. Use 'npx tsx prisma/seed.ts'")
                if 'npx prisma generate' in cmd:
                    errors.append(f"Step {sid}: 'npx prisma generate' is unnecessary. 'prisma db push' already does it")
                if '. .env.qa' in cmd or 'source .env.qa' in cmd:
                    errors.append(f"Step {sid}: use 'export $(grep -v ...)' not '. .env.qa' (source fails)")
            if sid in ('QA-006', 'QA-006'):
                retries = step.get('max_retries', 1)
                if retries < 3:
                    errors.append(f"Step {sid}: max_retries={retries} must be at least 3 (migrations can be slow)")
        elif stype == 'http':
            if 'url' not in step:
                errors.append(f"Step {sid} type=http: missing url")
            expected = step.get('expected', {})
            status = expected.get('status')
            if status is not None and not isinstance(status, int):
                errors.append(f"Step {sid}: expected.status must be integer, not '{status}'")
            headers = step.get('headers', {})
            ct = headers.get('Content-Type', '') if isinstance(headers, dict) else ''
            if 'multipart' in str(ct).lower():
                errors.append(f"Step {sid}: Content-Type multipart not supported by http driver. Use type: shell with curl -F.")
        elif stype == 'stress':
            if 'target' not in step:
                errors.append(f"Step {sid} type=stress: missing target")

    all_text = plan_text
    file_refs = re.findall(r"dummy_\w+\.\w+|/tmp/\w+\.\w+", all_text)
    if file_refs:
        for ref in set(file_refs):
            if 'printf' not in all_text and 'touch' not in all_text:
                errors.append(f"Step references '{ref}' but no step creates it (printf/touch)")

    yaml_errors = [e for e in errors if 'Invalid YAML' in e]
    valid = len(steps) > 0 and len(yaml_errors) == 0
    return valid, errors

def detect_pending():
    """Detect incomplete plans. Returns list of filenames."""
    plan_dir = os.path.join(WORKDIR, 'qa')
    os.makedirs(plan_dir, exist_ok=True)
    import glob as g
    all_files = g.glob(os.path.join(plan_dir, '*_*plan.md'))
    return sorted([os.path.basename(f) for f in all_files if not f.endswith('_completed.md')])

def get_next_id():
    """Calculate next ID based ONLY on completed plans."""
    plan_dir = os.path.join(WORKDIR, 'qa')
    os.makedirs(plan_dir, exist_ok=True)
    import glob as g
    completed = g.glob(os.path.join(plan_dir, '*_completed.md'))
    nums = set()
    for f in completed:
        basename = os.path.basename(f)
        match = re.match(r'(\d+)_', basename)
        if match:
            nums.add(int(match.group(1)))
    return max(nums) + 1 if nums else 1

# --- Template-based generators (no AI) ---

def generate_infra_plan_from_templates(next_id):
    timestamp = datetime.now().strftime('%Y%m%d_%H%M')
    plan_dir = os.path.join(WORKDIR, 'qa')
    os.makedirs(plan_dir, exist_ok=True)
    tpl_dir = os.path.join(SKILL_DIR, 'templates')

    tpl_path = os.path.join(tpl_dir, 'infra_steps.yaml')
    with open(tpl_path) as f:
        steps = f.read()

    total_steps = steps.count('--- STEP')

    plan = (
        f"# Plan de Validacion de Infraestructura\n\n"
        f"- **run_id**: {next_id:03d}\n"
        f"- **desc**: Validacion de infraestructura para proyecto Mandadero\n"
        f"- **date**: {datetime.now().strftime('%Y-%m-%d')}\n"
        f"- **total_steps**: {total_steps}\n\n"
        f"## README\n\n"
        f"Este plan verifica la infraestructura basica: prerrequisitos (Node, npm, Docker), "
        f"dependencias, archivos de configuracion, servicios Docker (PostgreSQL, Redis), "
        f"migraciones y seed de base de datos.\n\n"
        f"## Checklist de Escenarios\n\n"
        f"| ID | Escenario | Pasos | Estado |\n"
        f"|----|-----------|-------|--------|\n"
        f"| INFRA-00 | Reset de entorno | QA-000 | Pendiente |\n"
        f"| INFRA-01 | Prerrequisitos | QA-001, QA-002, QA-003 | Pendiente |\n"
        f"| INFRA-02 | Servicios Docker | QA-004, QA-005 | Pendiente |\n"
        f"| INFRA-03 | Base de datos | QA-006 | Pendiente |\n\n"
        f"## Pasos de Ejecucion\n\n"
        f"{steps}\n"
        f"## Execution Log\n\n(Sin registros)\n"
    )

    plan_name = f'{next_id:03d}_{timestamp}_infra_plan.md'
    plan_path = os.path.join(plan_dir, plan_name)
    with open(plan_path, 'w') as f:
        f.write(plan)

    print(f"  Infra plan generated from templates: {plan_path}", file=sys.stderr)
    print(f"  Total steps: {total_steps}", file=sys.stderr)
    return plan


def generate_unit_plan_from_templates(next_id):
    timestamp = datetime.now().strftime('%Y%m%d_%H%M')
    plan_dir = os.path.join(WORKDIR, 'qa')
    os.makedirs(plan_dir, exist_ok=True)
    tpl_dir = os.path.join(SKILL_DIR, 'templates')

    tpl_path = os.path.join(tpl_dir, 'unit_steps.yaml')
    with open(tpl_path) as f:
        steps = f.read()

    total_steps = steps.count('--- STEP')

    plan = (
        f"# Plan de Validacion de Codigo\n\n"
        f"- **run_id**: {next_id:03d}\n"
        f"- **desc**: Validacion de tests unitarios y calidad de codigo\n"
        f"- **date**: {datetime.now().strftime('%Y-%m-%d')}\n"
        f"- **total_steps**: {total_steps}\n\n"
        f"## README\n\n"
        f"Este plan ejecuta validaciones de calidad de codigo: typecheck TypeScript, "
        f"linting ESLint, tests unitarios (excluyendo integracion) y formateo Prettier.\n\n"
        f"## Checklist de Escenarios\n\n"
        f"| ID | Escenario | Pasos | Estado |\n"
        f"|----|-----------|-------|--------|\n"
        f"| UNIT-01 | Instalacion y typecheck | QA-001, QA-002 | Pendiente |\n"
        f"| UNIT-02 | Lint y tests | QA-003, QA-004 | Pendiente |\n"
        f"| UNIT-03 | Formato | QA-005 | Pendiente |\n\n"
        f"## Pasos de Ejecucion\n\n"
        f"{steps}\n"
        f"## Execution Log\n\n(Sin registros)\n"
    )

    plan_name = f'{next_id:03d}_{timestamp}_unit_plan.md'
    plan_path = os.path.join(plan_dir, plan_name)
    with open(plan_path, 'w') as f:
        f.write(plan)

    print(f"  Unit plan generated from templates: {plan_path}", file=sys.stderr)
    print(f"  Total steps: {total_steps}", file=sys.stderr)
    return plan

def _parse_limit_value(raw_line):
    m = re.search(r"parseInt\s*\(\s*process\.env\.(\w+)\s*\|\|\s*['\"](\d+)['\"]", raw_line)
    if m:
        return m.group(1), int(m.group(2))
    m = re.search(r'(\d+)', raw_line)
    if m:
        return None, int(m.group(1))
    return None, None

def detect_rate_limit():
    app_ts = os.path.join(WORKDIR, 'src', 'app.ts')
    if not os.path.exists(app_ts):
        return {}
    try:
        with open(app_ts, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return {}

    result = {}

    api_match = re.search(
        r'const\s+limiter\s*=\s*rateLimit\s*\(\s*\{.*?\n\s*(max:\s*[^\n]+)',
        content, re.DOTALL
    )
    if api_match:
        max_line = api_match.group(1)
        env_var, default_val = _parse_limit_value(max_line)
        win_match = re.search(
            r'const\s+limiter\s*=\s*rateLimit\s*\(\s*\{.*?\n\s*(windowMs:\s*[^\n]+)',
            content, re.DOTALL
        )
        _, win_default = _parse_limit_value(win_match.group(1)) if win_match else (None, None)
        if default_val is not None:
            result['api'] = (
                env_var or 'API_RATE_LIMIT_MAX',
                default_val,
                win_default if win_default else 15 * 60 * 1000
            )

    auth_match = re.search(
        r'const\s+authLimiter\s*=\s*rateLimit\s*\(\s*\{.*?\n\s*(max:\s*[^\n]+)',
        content, re.DOTALL
    )
    if auth_match:
        max_line = auth_match.group(1)
        env_var, default_val = _parse_limit_value(max_line)
        win_match = re.search(
            r'const\s+authLimiter\s*=\s*rateLimit\s*\(\s*\{.*?\n\s*(windowMs:\s*[^\n]+)',
            content, re.DOTALL
        )
        _, win_default = _parse_limit_value(win_match.group(1)) if win_match else (None, None)
        if default_val is not None:
            result['auth'] = (
                env_var or 'AUTH_RATE_LIMIT_MAX',
                default_val,
                win_default if win_default else 15 * 60 * 1000
            )

    return result

def _read_env_qa():
    env_path = os.path.join(WORKDIR, '.env.qa')
    if not os.path.exists(env_path):
        return {}
    env = {}
    with open(env_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            m = re.match(r'(\w+)\s*=\s*(.+)', line)
            if m:
                env[m.group(1)] = m.group(2).strip()
    return env

def ensure_env_limits():
    defaults = detect_rate_limit()
    if not defaults:
        return

    env_path = os.path.join(WORKDIR, '.env.qa')
    if not os.path.exists(env_path):
        print("  .env.qa does not exist, cannot adjust rate limits", file=sys.stderr)
        return

    env = _read_env_qa()

    n_users = QA_FLOW_USERS
    n_mandados = QA_FLOW_MANDADOS
    auth_needed = max(n_users * 4, 50)
    api_needed = max(n_users * n_mandados * 12 + 100, 500)

    changes = []
    new_lines = []
    with open(env_path, 'r') as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith('API_RATE_LIMIT_MAX='):
                current = int(env.get('API_RATE_LIMIT_MAX', '0'))
                if current < api_needed:
                    new_lines.append(f'API_RATE_LIMIT_MAX={api_needed}\n')
                    changes.append(f'API_RATE_LIMIT_MAX: {current} -> {api_needed}')
                else:
                    new_lines.append(line)
            elif stripped.startswith('AUTH_RATE_LIMIT_MAX='):
                current = int(env.get('AUTH_RATE_LIMIT_MAX', '0'))
                if current < auth_needed:
                    new_lines.append(f'AUTH_RATE_LIMIT_MAX={auth_needed}\n')
                    changes.append(f'AUTH_RATE_LIMIT_MAX: {current} -> {auth_needed}')
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)

    if changes:
        with open(env_path, 'w') as f:
            f.writelines(new_lines)
        print(f"  .env.qa updated:", file=sys.stderr)
        for c in changes:
            print(f"    -> {c}", file=sys.stderr)
        defaults_api = defaults.get('api', (None, 100, 15*60*1000))
        defaults_auth = defaults.get('auth', (None, 5, 15*60*1000))
        print(f"    -> App.ts defaults: API={defaults_api[1]}, AUTH={defaults_auth[1]}", file=sys.stderr)
        print(f"    -> Required: API>={api_needed}, AUTH>={auth_needed}", file=sys.stderr)
    else:
        print(f"  .env.qa OK: API_RATE_LIMIT_MAX={env.get('API_RATE_LIMIT_MAX','?')}, AUTH_RATE_LIMIT_MAX={env.get('AUTH_RATE_LIMIT_MAX','?')}", file=sys.stderr)

def count_http_steps(plan_text):
    return len(re.findall(r'^type:\s*http\s*$', plan_text, re.MULTILINE))

def ensure_rate_limit_capacity(plan_text):
    http_steps = count_http_steps(plan_text)
    env = _read_env_qa()
    api_max = int(env.get('API_RATE_LIMIT_MAX', '100'))
    auth_max = int(env.get('AUTH_RATE_LIMIT_MAX', '5'))

    if http_steps > api_max:
        print(f"  Warning: {http_steps} HTTP steps > API_RATE_LIMIT_MAX={api_max}. May hit 429 if all run within 15min.", file=sys.stderr)
    else:
        print(f"  Rate limit: API_RATE_LIMIT_MAX={api_max}, AUTH_RATE_LIMIT_MAX={auth_max} for {http_steps} HTTP steps", file=sys.stderr)
    return plan_text

def generate_flow_plan_from_templates(next_id):
    timestamp = datetime.now().strftime('%Y%m%d_%H%M')
    plan_dir = os.path.join(WORKDIR, 'qa')
    os.makedirs(plan_dir, exist_ok=True)
    flow_tpl_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates', 'flow')

    def load_tpl(name):
        path = os.path.join(flow_tpl_dir, name)
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        return None

    def replace(text, values):
        for k, v in values.items():
            text = text.replace('{{' + k + '}}', v)
        return text

    parts = []

    def add_tpl(name, values):
        nonlocal parts
        tpl = load_tpl(name)
        if not tpl:
            print(f"  Template not found: {name}", file=sys.stderr)
            return
        tpl = replace(tpl, values)
        parts.append(tpl)

    add_tpl('qa_start.yaml', {})

    usuarios = []
    n_solicitantes = QA_FLOW_USERS // 2
    n_mandaderos = QA_FLOW_USERS - n_solicitantes
    base = 1

    for i in range(n_solicitantes):
        tel = f"+524421{100000 + base + i:06d}"
        usuarios.append({
            'rol': 'solicitante', 'tel': tel, 'nombre': f'Solicitante {i+1}',
            'email': f'solicitante{i+1}@test.com',
            'token_var': f'jwtToken{i+1}', 'refresh_var': f'refreshToken{i+1}',
            'id_var': f'userId{i+1}',
        })
    for i in range(n_mandaderos):
        tel = f"+524421{100000 + base + n_solicitantes + i:06d}"
        usuarios.append({
            'rol': 'mandadero', 'tel': tel, 'nombre': f'Mandadero {i+1}',
            'email': f'mandadero{i+1}@test.com',
            'token_var': f'mandaderoToken{i+1}', 'refresh_var': f'mandaderoRefresh{i+1}',
            'id_var': f'mandaderoId{i+1}',
        })

    for u in usuarios:
        prefix = 'U1' if u['rol'] == 'solicitante' else 'U2'
        add_tpl('user_register.yaml', {
            'ID': f'{prefix}0{usuarios.index(u)+1}',
            'NOMBRE': u['nombre'], 'TELEFONO': u['tel'],
            'EMAIL': u['email'], 'TOKEN_VAR': u['token_var'],
            'REFRESH_VAR': u['refresh_var'], 'ID_VAR': u['id_var'],
        })
        u['replaced_id'] = f'{prefix}0{usuarios.index(u)+1}'

    for u in usuarios:
        idx = usuarios.index(u) + 1
        uid = f'U{idx}'
        new_token_var = f'new{u["token_var"]}'
        new_refresh_var = f'new{u["refresh_var"]}'
        add_tpl('user_upload.yaml', {
            'ID': uid, 'NOMBRE': u['nombre'],
            'TOKEN_OLD': '{{' + u['token_var'] + '}}',
            'REFRESH_TOKEN': '{{' + u['refresh_var'] + '}}',
            'TOKEN_NEW_VAR': new_token_var,
            'REFRESH_NEW_VAR': new_refresh_var,
        })
        u['token_var'] = new_token_var
        u['refresh_var'] = new_refresh_var

    solicitantes = [u for u in usuarios if u['rol'] == 'solicitante']
    mandadero = [u for u in usuarios if u['rol'] == 'mandadero'][0]
    n_mandados_total = 0
    for sol in solicitantes:
        for m in range(QA_FLOW_MANDADOS):
            n_mandados_total += 1
            mid = f'M{n_mandados_total}'
            mandado_id_var = f'mandado{mid}Id'
            oferta_id_var = f'oferta{mid}Id'

            add_tpl('mandado.yaml', {
                'ID': f'{mid}0',
                'NOMBRE': sol['nombre'],
                'TOKEN': '{{' + sol['token_var'] + '}}',
                'TITULO': f'Mandado de prueba {m+1}',
                'DESCRIPCION': f'Descripcion del mandado de prueba {m+1}',
                'MANDADO_ID_EXTRACT': mandado_id_var,
                'MANDADO_ID_VAR': '{{' + mandado_id_var + '}}',
            })

            add_tpl('oferta.yaml', {
                'ID': f'{mid}0',
                'MANDADO_ID_VAR': '{{' + mandado_id_var + '}}',
                'MANDADERO_TOKEN': '{{' + mandadero['token_var'] + '}}',
                'SOLICITANTE_TOKEN': '{{' + sol['token_var'] + '}}',
                'OFERTA_ID_VAR': '{{' + oferta_id_var + '}}',
                'OFERTA_ID_EXTRACT': oferta_id_var,
            })

            add_tpl('mensajes.yaml', {
                'ID': f'{mid}0',
                'MANDADO_ID_VAR': '{{' + mandado_id_var + '}}',
                'TOKEN1': '{{' + sol['token_var'] + '}}',
                'TOKEN2': '{{' + mandadero['token_var'] + '}}',
                'NOMBRE1': sol['nombre'],
                'NOMBRE2': mandadero['nombre'],
                'TEXTO1': 'Hola, gracias por aceptar la oferta',
                'TEXTO2': 'Si, voy en 30 minutos',
            })

            add_tpl('completar.yaml', {
                'ID': f'{mid}0',
                'MANDADO_ID_VAR': '{{' + mandado_id_var + '}}',
                'SOLICITANTE_TOKEN': '{{' + sol['token_var'] + '}}',
                'MANDADERO_TOKEN': '{{' + mandadero['token_var'] + '}}',
                'MANDADERO_ID_VAR': '{{' + mandadero['id_var'] + '}}',
                'SOLICITANTE_ID_VAR': '{{' + sol['id_var'] + '}}',
            })

    if QA_FLOW_DENUNCIAS == 'si':
        sol = solicitantes[0]
        add_tpl('denuncias.yaml', {
            'ID': 'D01',
            'SOLICITANTE_TOKEN': '{{' + sol['token_var'] + '}}',
            'MANDADERO_ID_VAR': '{{' + mandadero['id_var'] + '}}',
            'MANDADO_ID_VAR': '{{mandadoM1Id}}',
            'SOLICITANTE_ID_VAR': '{{' + sol['id_var'] + '}}',
        })

    if QA_FLOW_ADMIN_ENDPOINTS == 'si':
        sol = solicitantes[0]
        add_tpl('admin_denegado.yaml', {
            'ID': 'A01',
            'SOLICITANTE_TOKEN': '{{' + sol['token_var'] + '}}',
        })

    sol = solicitantes[0]
    add_tpl('errores.yaml', {
        'ID': 'E01',
        'TELEFONO': sol['tel'],
        'SOLICITANTE_TOKEN': '{{' + sol['token_var'] + '}}',
        'SOLICITANTE_ID_VAR': '{{' + sol['id_var'] + '}}',
        'MANDADO_ID_VAR': '{{mandadoM1Id}}',
    })

    sol = solicitantes[0]
    new_token_var = f'new{sol["token_var"]}'
    new_refresh_var = f'new{sol["refresh_var"]}'
    add_tpl('cierre.yaml', {
        'ID': 'C01',
        'REFRESH_TOKEN_OLD': '{{' + sol['refresh_var'] + '}}',
        'NEW_TOKEN_VAR': new_token_var,
        'NEW_REFRESH_VAR': new_refresh_var,
        'NEW_TOKEN_VAR_REF': '{{' + new_token_var + '}}',
        'NEW_REFRESH_VAR_REF': '{{' + new_refresh_var + '}}',
        'SOLICITANTE_TOKEN': '{{' + sol['token_var'] + '}}',
        'TELEFONO': sol['tel'],
    })

    all_text = '\n'.join(parts)
    total_steps = all_text.count('--- STEP')

    header = (
        f"# Plan de Validacion de Flujo Operativo\n\n"
        f"## Encabezado\n"
        f"- **run_id**: {next_id:03d}\n"
        f"- **desc**: Validacion de flujo operativo con {n_solicitantes} solicitante(s) y {n_mandaderos} mandadero(s)\n"
        f"- **date**: {datetime.now().strftime('%Y-%m-%d')}\n"
        f"- **total_steps**: {total_steps}\n\n"
        f"## README\n\n"
        f"Plan generado desde templates YAML. Cubre registro, OTP, verificacion de identidad, "
        f"mandados, ofertas, mensajeria, calificaciones, denuncias, errores y cierre de sesion.\n\n"
        f"Usuarios: {QA_FLOW_USERS} ({n_solicitantes} solicitante(s), {n_mandaderos} mandadero(s)).\n"
        f"Mandados por solicitante: {QA_FLOW_MANDADOS}.\n"
        f"Modo verificacion: {QA_FLOW_VERIFICACION}.\n\n"
        f"## Pasos de Ejecucion\n\n"
    )

    plan = header + '\n'.join(parts)
    plan += f"\n## Execution Log\n\n(Sin registros)\n"

    plan = ensure_rate_limit_capacity(plan)

    plan_name = f'{next_id:03d}_{timestamp}_flow_plan.md'
    plan_path = os.path.join(plan_dir, plan_name)
    with open(plan_path, 'w', encoding='utf-8') as f:
        f.write(plan)

    print(f"  Flow plan generated from templates: {plan_path}", file=sys.stderr)
    print(f"  Total steps: {total_steps}", file=sys.stderr)
    return plan


def generate_plan(plan_type, existing_str, next_id):
    """Generate a plan for the given type. Returns text or None."""
    template = load_template(plan_type)
    if not template:
        print(f"  Template not found for type '{plan_type}'", file=sys.stderr)
        return None

    try:
        ctx = json.loads(QA_PROJECT_CONTEXT) if isinstance(QA_PROJECT_CONTEXT, str) else QA_PROJECT_CONTEXT
        ctx_str = json.dumps(ctx, indent=2, ensure_ascii=False)[:8000]
    except:
        ctx_str = str(QA_PROJECT_CONTEXT)[:8000]

    stress_desc = STRESS_CONFIG.get(QA_STRESS_LEVEL, STRESS_CONFIG['medio'])
    stress_str = f"level={QA_STRESS_LEVEL} (n={stress_desc['n']}, c={stress_desc['c']}, p95<={stress_desc['p95']}ms, rate>={stress_desc['rate']}%)"

    system_prompt = template.replace('{context}', ctx_str)
    system_prompt = system_prompt.replace('{existing_plans}', existing_str)
    system_prompt = system_prompt.replace('{stress_level}', stress_str)
    system_prompt = system_prompt.replace('{scale_workers}', str(QA_SCALE_WORKERS))

    flow_config_str = (
        f"\n## FLOW PLAN CONFIGURATION\n"
        f"- **Users**: {QA_FLOW_USERS} ({QA_FLOW_USERS//2} requesters, {QA_FLOW_USERS//2} runners)\n"
        f"- **Orders per requester**: {QA_FLOW_MANDADOS}\n"
        f"- **Verification mode**: {QA_FLOW_VERIFICACION}\n"
        f"- **Admin in DB**: {QA_FLOW_ADMIN_EXISTS}\n"
        f"- **Include complaints**: {QA_FLOW_DENUNCIAS}\n"
        f"- **Include admin endpoints**: {QA_FLOW_ADMIN_ENDPOINTS}\n"
    )
    system_prompt = system_prompt.replace('{flow_config}', flow_config_str)

    if plan_type == 'flow':
        api_contract = load_api_contract()
        system_prompt = system_prompt.replace('{api_contract}', api_contract)
    else:
        system_prompt = system_prompt.replace('{api_contract}', '')

    user_message = f"Genera el plan de validacion tipo '{plan_type}' para este proyecto."

    plan_types_str = os.environ.get('QA_PLAN_TYPES', 'unknown')
    task_desc = f"Generate QA validation plan type {plan_types_str}"

    resolve_model("qa.prepare")
    print_model_banner(task_desc)

    stop_spinner = threading.Event()
    task_label = f"Generating plan {plan_type}"
    spinner_thread = threading.Thread(
        target=spinner_while_waiting,
        args=(stop_spinner, task_label)
    )
    spinner_thread.start()
    try:
        plan = call_model(system_prompt, user_message)
    finally:
        stop_spinner.set()
        spinner_thread.join()

    if not plan:
        return None

    ok, errors = validate_plan(plan, plan_type)
    if not ok:
        print(f"  Validation: {len(errors)} errors — regenerating with corrections", file=sys.stderr)
        for e in errors[:5]:
            print(f"    -> {e}", file=sys.stderr)

        correction_prompt = system_prompt + "\n\n## REQUIRED CORRECTIONS\nThe previous plan has these errors:\n" + \
            "\n".join(f"- {e}" for e in errors) + \
            "\n\nCorrect and regenerate the complete plan. Ensure correct --- STEP format."

        stop_spinner = threading.Event()
        spinner_thread = threading.Thread(
            target=spinner_while_waiting,
            args=(stop_spinner, f"Correcting plan {plan_type}")
        )
        spinner_thread.start()
        try:
            plan = call_model(correction_prompt, user_message)
        finally:
            stop_spinner.set()
            spinner_thread.join()

        if plan:
            ok2, errors2 = validate_plan(plan, plan_type)
            if not ok2:
                print(f"  Correction: {len(errors2)} persistent errors", file=sys.stderr)
                for e in errors2[:3]:
                    print(f"    -> {e}", file=sys.stderr)
            else:
                print(f"  Plan validated successfully", file=sys.stderr)

    return plan

def generate_suite(plan_types, next_id, timestamp):
    """Generate suite_plan.md."""
    plan_names = {t: f'qa/{next_id:03d}_{timestamp}_{t}_plan.md' for t in plan_types}
    deps = {
        'infra': [],
        'unit': [],
        'flow': ['infra'],
        'stress': ['infra', 'flow'],
        'scale': ['infra'],
    }

    lines = [
        '# Suite de Validacion QA',
        f'- **run_id**: {next_id:03d}',
        f'- **desc**: suite-{timestamp}',
        f'- **date**: {datetime.now().strftime("%Y-%m-%d")}',
        f'- **total_plans**: {len(plan_types)}',
        '',
        '## README',
        '',
        'Esta suite ejecuta los siguientes planes en orden secuencial.',
        'Cada plan depende de los anteriores segun se indica.',
        'Si un plan falla, el orquestador pregunta si continuar o abortar.',
        '',
        '## Planes',
        '| Orden | Plan | Dependencias | Estado |',
        '|---|---|---|---|',
    ]

    for i, pt in enumerate(plan_types, 1):
        dep_list = deps.get(pt, [])
        dep_str = ', '.join(dep_list) if dep_list else '—'
        lines.append(f'| {i} | {plan_names[pt]} | {dep_str} | \u23f3 |')

    if 'infra' in plan_types:
        lines.extend([
            '',
            '## Teardown',
            '| Orden | Plan | Comando |',
            '|---|---|---|',
            '| 1 | — | docker-compose -f docker-compose.yml down --volumes |',
        ])

    return '\n'.join(lines) + '\n'

def main():
    # Phase 1: Detect pending plans
    pending = detect_pending()
    if pending:
        print(f"ATTENTION: {len(pending)} pending plan(s) not completed:", file=sys.stderr)
        for p in pending:
            print(f"    - {p}", file=sys.stderr)
        print(file=sys.stderr)
        print("These plans remain from a previous aborted execution.", file=sys.stderr)
        print(file=sys.stderr)
        print("Options:", file=sys.stderr)
        print("  1) Delete them and generate new test set", file=sys.stderr)
        print("  2) Resume them with qa.execute (do not run qa.prepare)", file=sys.stderr)
        print(file=sys.stderr)
        print("PENDING_FILES_DETECTED", file=sys.stderr)
        sys.exit(2)

    progress = load_progress()
    plan_types = [pt.strip() for pt in QA_PLAN_TYPES if pt.strip()]
    next_id = get_next_id()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M')
    plan_dir = os.path.join(WORKDIR, 'qa')
    os.makedirs(plan_dir, exist_ok=True)

    existing_str = QA_EXISTING_PLANS if QA_EXISTING_PLANS.strip() else "No existing plans."
    generated = []

    print(f"Selected plan types: {', '.join(plan_types)}", file=sys.stderr)
    print(f"Stress level: {QA_STRESS_LEVEL}", file=sys.stderr)
    print(f"Scale workers: {QA_SCALE_WORKERS}", file=sys.stderr)
    if 'flow' in plan_types:
        print(f"Flow users: {QA_FLOW_USERS}", file=sys.stderr)
        print(f"Orders per user: {QA_FLOW_MANDADOS}", file=sys.stderr)
        print(f"Verification mode: {QA_FLOW_VERIFICACION}", file=sys.stderr)
        print(f"Admin in DB: {QA_FLOW_ADMIN_EXISTS}", file=sys.stderr)
        print(f"Include complaints: {QA_FLOW_DENUNCIAS}", file=sys.stderr)
        print(f"Include admin endpoints: {QA_FLOW_ADMIN_ENDPOINTS}", file=sys.stderr)
    print(f"Next ID: {next_id:03d}", file=sys.stderr)
    print(file=sys.stderr)

    if 'flow' in plan_types:
        ensure_env_limits()

    for plan_type in plan_types:
        print(f"{'='*54}", file=sys.stderr)
        print(f"  Plan: {plan_type}", file=sys.stderr)
        print(f"{'-'*54}", file=sys.stderr)

        p = progress if isinstance(progress, dict) else {}
        if p.get(plan_type) == "done":
            cache_file = f'/tmp/opencode/qa_prepare_{plan_type}_cached.md'
            if os.path.exists(cache_file):
                print(f"  Cache found for '{plan_type}' — skipping AI generation, writing from cache", file=sys.stderr)
                with open(cache_file, 'r', encoding='utf-8') as f:
                    plan = f.read()
                plan = re.sub(r'- \*\*run_id\*\*: .*', f'- **run_id**: {next_id:03d}', plan)
                plan = re.sub(r'- \*\*date\*\*: .*', f'- **date**: {datetime.now().strftime("%Y-%m-%d")}', plan)
                plan_name = f'{next_id:03d}_{timestamp}_{plan_type}_plan.md'
                plan_path = os.path.join(plan_dir, plan_name)
                with open(plan_path, 'w', encoding='utf-8') as f:
                    f.write(plan)
                print(f"  Plan saved from cache: {plan_path}", file=sys.stderr)
                generated.append((plan_type, plan))
                continue

        print(f"  Preparing project context ({len(QA_PROJECT_CONTEXT)} chars)...", file=sys.stderr)
        save_progress(plan_type, "running")

        if plan_type == 'infra':
            plan = generate_infra_plan_from_templates(next_id)
        elif plan_type == 'unit':
            plan = generate_unit_plan_from_templates(next_id)
        elif plan_type == 'flow':
            plan = generate_flow_plan_from_templates(next_id)
        else:
            plan = generate_plan(plan_type, existing_str, next_id)

        if not plan:
            print(f"  Failed to generate plan '{plan_type}'", file=sys.stderr)
            save_progress(plan_type, "failed")
            continue

        cache_file = f'/tmp/opencode/qa_prepare_{plan_type}_cached.md'
        with open(cache_file, 'w', encoding='utf-8') as f:
            f.write(plan)
        save_progress(plan_type, "done")

        plan = re.sub(r'- \*\*run_id\*\*: .*', f'- **run_id**: {next_id:03d}', plan)
        plan = re.sub(r'- \*\*date\*\*: .*', f'- **date**: {datetime.now().strftime("%Y-%m-%d")}', plan)

        plan_name = f'{next_id:03d}_{timestamp}_{plan_type}_plan.md'
        plan_path = os.path.join(plan_dir, plan_name)
        with open(plan_path, 'w', encoding='utf-8') as f:
            f.write(plan)

        print(f"  Plan saved: {plan_path}", file=sys.stderr)
        generated.append((plan_type, plan))

    if len(generated) > 1:
        print(f"\n{'='*50}", file=sys.stderr)
        print(f"  Generating suite plan...", file=sys.stderr)
        suite_text = generate_suite([pt for pt, _ in generated], next_id, timestamp)
        suite_name = f'{next_id:03d}_{timestamp}_suite_plan.md'
        suite_path = os.path.join(plan_dir, suite_name)
        with open(suite_path, 'w', encoding='utf-8') as f:
            f.write(suite_text)
        print(f"Suite saved: {suite_path}", file=sys.stderr)

    n = len(generated)
    modo_label = {"low": "Low", "medium": "Medium", "high": "High"}.get(os.environ.get("OPENCODE_MODO"), "?")

    remote_input = 2500 + 500 + 1000 + 2000 + 500
    local_input = n * 1200
    local_think = n * 6000 if "deepseek-r1" in os.environ.get("OPENCODE_MODEL", "") else 0
    local_output = n * 2000

    print(f"\n{'='*54}", file=sys.stderr)
    print(f"  Preparation completed", file=sys.stderr)
    print(f"{'-'*54}", file=sys.stderr)
    print(f"  Plans generated: {len(generated)}", file=sys.stderr)
    for pt, _ in generated:
        print(f"    - {pt}", file=sys.stderr)
    if len(generated) > 1:
        print(f"  Suite generated: yes ({suite_name})", file=sys.stderr)
    print(f"{'-'*54}", file=sys.stderr)
    print(f"  Model Router: {modo_label}", file=sys.stderr)
    print(f"  Model: {os.environ.get('OPENCODE_MODEL', '?')} ({os.environ.get('OPENCODE_PROVEEDOR', '?')})", file=sys.stderr)
    print(file=sys.stderr)
    print(f"  {'Source':<30} {'Tokens est.':>12} {'Cost':>8}", file=sys.stderr)
    print(f"  {'-'*52}", file=sys.stderr)
    print(f"  {'Remote — Load SKILL.md':<30} {2500:>12} {'$$':>8}", file=sys.stderr)
    print(f"  {'Remote — Ask user':<30} {500:>12} {'$$':>8}", file=sys.stderr)
    print(f"  {'Remote — Collect context':<30} {1000:>12} {'$$':>8}", file=sys.stderr)
    print(f"  {'Remote — Read generated plans':<30} {2000:>12} {'$$':>8}", file=sys.stderr)
    print(f"  {'Remote — Present summary':<30} {500:>12} {'$$':>8}", file=sys.stderr)
    print(f"  {'Total remote':<30} {remote_input:>12} {'$$':>8}", file=sys.stderr)
    print(f"  {'':54}", file=sys.stderr)
    print(f"  {'Local — Input x N plans':<30} {local_input:>12} {'$0':>8}", file=sys.stderr)
    if local_think:
        print(f"  {'Local — Reasoning x N':<30} {local_think:>12} {'$0':>8}", file=sys.stderr)
    print(f"  {'Local — Output x N':<30} {local_output:>12} {'$0':>8}", file=sys.stderr)
    print(f"  {'Total local':<30} {local_input + local_think + local_output:>12} {'free':>8}", file=sys.stderr)
    local_total = local_input + local_think + local_output
    total_tokens = remote_input + local_total
    if total_tokens > 0:
        pct_remote = int(remote_input * 100 / total_tokens)
        pct_local = 100 - pct_remote
        print(f"  {'-'*52}", file=sys.stderr)
        print(f"  {'% Remote':<30} {pct_remote:>11}%", file=sys.stderr)
        print(f"  {'% Local':<30} {pct_local:>11}%", file=sys.stderr)
    print(f"{'='*54}\n", file=sys.stderr)

    result = {
        "status": "ok",
        "plans_generated": len(generated),
        "plan_types": [pt for pt, _ in generated],
        "suite": len(generated) > 1,
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
