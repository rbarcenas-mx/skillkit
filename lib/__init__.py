import json
import os
import subprocess
import sys

BUDGET_LEVELS = ("low", "medium", "high")


def _load_models():
    try:
        with open(os.path.join(os.environ["SKILLKIT_HOME"], "lib", "models.json")) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        print(f"WARNING: Cannot load models.json: {e}", file=sys.stderr)
        return None


def _resolve_budget(budget):
    if budget is not None:
        return budget
    env_budget = os.environ.get("TOKEN_BUDGET")
    if env_budget is not None:
        return env_budget
    legacy = os.environ.get("AHORRO_MODO")
    if legacy is not None:
        return {"ahorro_alto": "low", "ahorro_balanceado": "medium", "ahorro_bajo": "high"}.get(legacy, legacy)
    try:
        cat = _load_models()
        if cat:
            dft = cat.get("config", {}).get("modo", "low")
            return {"ahorro_alto": "low", "ahorro_balanceado": "medium", "ahorro_bajo": "high"}.get(dft, dft)
    except Exception:
        pass
    return "low"


def _set_api_env(proveedor: str, via_opencode_go: bool = False) -> bool:
    if via_opencode_go:
        os.environ["OPENCODE_API_URL"] = "https://opencode.ai/zen/go/v1"
        return _set_opencode_go_key()

    cfg_path = os.path.expanduser("~/.config/opencode/opencode.json")
    try:
        with open(cfg_path) as f:
            cfg = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        cfg = {}
    prov_cfg = cfg.get("provider", {}).get(proveedor, {})

    if prov_cfg:
        os.environ["OPENCODE_API_URL"] = prov_cfg.get("options", {}).get("baseURL", "")
        api_key_raw = prov_cfg.get("options", {}).get("apiKey", "")
        if api_key_raw and api_key_raw.startswith("{env:"):
            env_var = api_key_raw[5:-1]
            api_key_raw = os.environ.get(env_var, "")
        os.environ["OPENCODE_API_KEY"] = api_key_raw
        return bool(api_key_raw)
    elif proveedor and proveedor != "ollama":
        os.environ["OPENCODE_API_URL"] = "https://opencode.ai/zen/go/v1"
        return _set_opencode_go_key()
    else:
        os.environ["OPENCODE_API_URL"] = ""
        os.environ["OPENCODE_API_KEY"] = ""
        return True  # ollama doesn't need API key


def _set_opencode_go_key() -> bool:
    auth_path = os.path.expanduser("~/.local/share/opencode/auth.json")
    try:
        with open(auth_path) as f:
            auth = json.load(f)
        key = auth.get("opencode-go", {}).get("key", "")
        os.environ["OPENCODE_API_KEY"] = key
        return bool(key)
    except (FileNotFoundError, json.JSONDecodeError):
        os.environ["OPENCODE_API_KEY"] = ""
        return False


def _ollama_models_available():
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return []
        lines = result.stdout.strip().split("\n")[1:]
        return [line.split()[0] for line in lines if line.strip()]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []


def _model_available(model_id: str, info: dict) -> bool:
    proveedor = info.get("proveedor", "")
    if proveedor == "ollama":
        return model_id in _ollama_models_available()
    via_go = model_id.startswith("opencode-go/")
    return _set_api_env(proveedor, via_opencode_go=via_go)


def _activate_model(model_id: str, info: dict, budget_real: str) -> str:
    proveedor = info.get("proveedor", "")
    via_go = model_id.startswith("opencode-go/")
    api_model = model_id.replace("opencode-go/", "") if via_go else model_id

    os.environ["OPENCODE_MODEL"] = api_model
    os.environ["OPENCODE_MODEL_DESC"] = info.get("descripcion", "")
    os.environ["OPENCODE_MODO"] = budget_real
    os.environ["OPENCODE_PROVEEDOR"] = proveedor

    if not via_go:
        _set_api_env(proveedor, via_opencode_go=False)

    headroom_url = os.environ.get("HEADROOM_PROXY_URL", "")
    if headroom_url and proveedor and proveedor != "ollama":
        os.environ["HEADROOM_UPSTREAM_URL"] = os.environ.get("OPENCODE_API_URL", "")
        os.environ["OPENCODE_API_URL"] = headroom_url

    return model_id


def _build_chain(budget: str, entry: dict) -> list:
    levels = ["low", "medium", "high"]
    chain = []
    # Start from the requested budget, then try others in priority order
    remaining = [l for l in levels if l != budget]
    chain.append((budget, entry[budget]))
    for l in remaining:
        chain.append((l, entry[l]))
    return chain


def resolve_model(skill_name, budget=None):
    """Resolve the model for a skill according to TOKEN_BUDGET with graceful degradation.

    If the target model is unavailable:
      - Warns on stderr
      - Falls back to the next available budget tier
      - If nothing works: keeps current model, warns, returns it
    Never exits the process.
    """
    budget = _resolve_budget(budget)

    if budget not in BUDGET_LEVELS:
        current = os.environ.get("OPENCODE_MODEL", "unknown")
        print(f"WARNING: Invalid TOKEN_BUDGET='{budget}'. Must be one of: {', '.join(BUDGET_LEVELS)}", file=sys.stderr)
        print(f"  Keeping current model: {current}", file=sys.stderr)
        os.environ["OPENCODE_MODO"] = budget + "(invalid)"
        return current

    catalogo = _load_models()
    if catalogo is None:
        current = os.environ.get("OPENCODE_MODEL", "unknown")
        print(f"WARNING: Cannot load model catalog from SKILLKIT_HOME/lib/models.json", file=sys.stderr)
        print(f"  Keeping current model: {current}", file=sys.stderr)
        os.environ["OPENCODE_MODO"] = budget + "(no_catalog)"
        return current

    if budget not in BUDGET_LEVELS:
        current = os.environ.get("OPENCODE_MODEL", "unknown")
        print(f"WARNING: Invalid TOKEN_BUDGET='{budget}'. Must be one of: {', '.join(BUDGET_LEVELS)}", file=sys.stderr)
        print(f"  Keeping current model: {current}", file=sys.stderr)
        os.environ["OPENCODE_MODO"] = budget + "(invalid)"
        return current

    mapping = catalogo.get("skill_mapping", {})
    entry = mapping.get(skill_name)
    if entry is None:
        current = os.environ.get("OPENCODE_MODEL", "unknown")
        print(f"WARNING: Skill '{skill_name}' not found in skill_mapping", file=sys.stderr)
        print(f"  Available: {', '.join(mapping.keys())}", file=sys.stderr)
        print(f"  Keeping current model: {current}", file=sys.stderr)
        os.environ["OPENCODE_MODO"] = budget + "(unknown_skill)"
        return current

    todos = catalogo.get("local", []) + catalogo.get("remoto", [])
    chain = _build_chain(budget, entry)

    for level, model_id in chain:
        info = next((m for m in todos if m["id"] == model_id), {})
        if _model_available(model_id, info):
            if level != budget:
                print(f"WARNING: TOKEN_BUDGET={budget} → model '{entry[budget]}' not available", file=sys.stderr)
                print(f"  Falling back to '{model_id}' (TOKEN_BUDGET={level})", file=sys.stderr)
            return _activate_model(model_id, info, budget + f"(fallback_{level})" if level != budget else budget)

    current = os.environ.get("OPENCODE_MODEL", "unknown")
    print(f"WARNING: No model available for TOKEN_BUDGET={budget} → skill '{skill_name}'", file=sys.stderr)
    print(f"  TOKEN_BUDGET bypassed. Keeping current model: {current}", file=sys.stderr)
    os.environ["OPENCODE_MODO"] = budget + "(bypassed)"
    return current


def resolve_model_legacy(modelo_local, modelo_remoto, budget=None):
    budget = _resolve_budget(budget)
    target = modelo_local if budget == "low" else modelo_remoto
    return resolve_model_by_id(target, budget)


def resolve_model_by_id(modelo_id, budget):
    catalogo = _load_models()
    todos = catalogo.get("local", []) + catalogo.get("remoto", [])
    info = next((m for m in todos if m["id"] == modelo_id), {})

    if not info:
        current = os.environ.get("OPENCODE_MODEL", "unknown")
        print(f"WARNING: Model '{modelo_id}' not found in catalog", file=sys.stderr)
        print(f"  Keeping current model: {current}", file=sys.stderr)
        return current

    via_go = modelo_id.startswith("opencode-go/")
    api_model = modelo_id.replace("opencode-go/", "") if via_go else modelo_id

    os.environ["OPENCODE_MODEL"] = api_model
    os.environ["OPENCODE_MODEL_DESC"] = info.get("descripcion", "")
    os.environ["OPENCODE_MODO"] = budget
    os.environ["OPENCODE_PROVEEDOR"] = info.get("proveedor", "")

    _set_api_env(info.get("proveedor", ""), via_opencode_go=via_go)

    return modelo_id
