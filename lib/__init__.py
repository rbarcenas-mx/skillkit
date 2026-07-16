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
            dft = cat.get("config", {}).get("mode", "low")
            return {"ahorro_alto": "low", "ahorro_balanceado": "medium", "ahorro_bajo": "high"}.get(dft, dft)
    except Exception:
        pass
    return "low"


def _load_user_config(catalog):
    default_path = os.path.expanduser("~/.config/skillkit/config.json")
    config_path = os.environ.get("SKILLKIT_CONFIG_FILE") or catalog.get("config", {}).get("config_file", default_path)
    config_path = os.path.expanduser(config_path)
    try:
        with open(config_path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _get_provider_config(catalog, user_config, provider_name):
    base = catalog.get("providers", {}).get(provider_name, {})
    override = user_config.get("providers", {}).get(provider_name, {})
    merged = dict(base)
    merged.update({k: v for k, v in override.items() if v is not None})
    return merged


def _resolve_api_key(value):
    if value and value.startswith("{env:") and value.endswith("}"):
        return os.environ.get(value[5:-1], "")
    return value or ""


def _set_api_env(provider_cfg):
    url = provider_cfg.get("base_url", "")
    key = _resolve_api_key(provider_cfg.get("api_key", ""))
    os.environ["SKILLKIT_API_URL"] = url
    os.environ["SKILLKIT_API_KEY"] = key
    return bool(url)


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


def _model_available(model_id, info, catalog, user_config):
    provider = info.get("provider", "")
    if provider == "ollama":
        return model_id in _ollama_models_available()
    provider_cfg = _get_provider_config(catalog, user_config, provider)
    _set_api_env(provider_cfg)
    url = os.environ.get("SKILLKIT_API_URL", "")
    key = os.environ.get("SKILLKIT_API_KEY", "")
    if not url:
        return False
    # If the provider config explicitly lists an api_key, it must resolve to a non-empty value.
    # An explicit empty api_key means "no auth required".
    if "api_key" in provider_cfg and not key:
        return False
    return True


def _activate_model(model_id, info, budget_real, catalog, user_config):
    provider = info.get("provider", "")
    provider_cfg = _get_provider_config(catalog, user_config, provider)
    api_model = info.get("api_model", model_id)

    os.environ["SKILLKIT_MODEL"] = api_model
    os.environ["SKILLKIT_MODEL_DESC"] = info.get("description", "")
    os.environ["SKILLKIT_MODE"] = budget_real
    os.environ["SKILLKIT_PROVIDER"] = provider

    _set_api_env(provider_cfg)

    headroom_url = os.environ.get("HEADROOM_PROXY_URL", "")
    if headroom_url and provider and provider != "ollama":
        os.environ["HEADROOM_UPSTREAM_URL"] = os.environ.get("SKILLKIT_API_URL", "")
        os.environ["SKILLKIT_API_URL"] = headroom_url

    return model_id


def _build_chain(budget, entry, fallback_chain):
    chain = [(budget, entry[budget])]
    for level in fallback_chain:
        if level != budget and level in BUDGET_LEVELS:
            chain.append((level, entry[level]))
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
        current = os.environ.get("SKILLKIT_MODEL", "unknown")
        print(f"WARNING: Invalid TOKEN_BUDGET='{budget}'. Must be one of: {', '.join(BUDGET_LEVELS)}", file=sys.stderr)
        print(f"  Keeping current model: {current}", file=sys.stderr)
        os.environ["SKILLKIT_MODE"] = budget + "(invalid)"
        return current

    catalog = _load_models()
    if catalog is None:
        current = os.environ.get("SKILLKIT_MODEL", "unknown")
        print(f"WARNING: Cannot load model catalog from SKILLKIT_HOME/lib/models.json", file=sys.stderr)
        print(f"  Keeping current model: {current}", file=sys.stderr)
        os.environ["SKILLKIT_MODE"] = budget + "(no_catalog)"
        return current

    user_config = _load_user_config(catalog)

    mapping = {k: dict(v) for k, v in catalog.get("skill_mapping", {}).items()}
    overrides = user_config.get("skill_model_overrides", {})
    for skill, override in overrides.items():
        if skill in mapping:
            if isinstance(override, dict):
                mapping[skill].update(override)
            elif isinstance(override, str):
                mapping[skill]["low"] = override

    entry = mapping.get(skill_name)
    if entry is None:
        current = os.environ.get("SKILLKIT_MODEL", "unknown")
        print(f"WARNING: Skill '{skill_name}' not found in skill_mapping", file=sys.stderr)
        print(f"  Available: {', '.join(mapping.keys())}", file=sys.stderr)
        print(f"  Keeping current model: {current}", file=sys.stderr)
        os.environ["SKILLKIT_MODE"] = budget + "(unknown_skill)"
        return current
    models = catalog.get("models", [])
    fallback_chain = catalog.get("config", {}).get("fallback_chain", ["medium", "high", "low"])

    chain = _build_chain(budget, entry, fallback_chain)

    for level, model_id in chain:
        info = next((m for m in models if m["id"] == model_id), {})
        if info and _model_available(model_id, info, catalog, user_config):
            if level != budget:
                print(f"WARNING: TOKEN_BUDGET={budget} -> model '{entry[budget]}' not available", file=sys.stderr)
                print(f"  Falling back to '{model_id}' (TOKEN_BUDGET={level})", file=sys.stderr)
            return _activate_model(model_id, info, budget + f"(fallback_{level})" if level != budget else budget, catalog, user_config)

    current = os.environ.get("SKILLKIT_MODEL", "unknown")
    print(f"WARNING: No model available for TOKEN_BUDGET={budget} -> skill '{skill_name}'", file=sys.stderr)
    print(f"  TOKEN_BUDGET bypassed. Keeping current model: {current}", file=sys.stderr)
    os.environ["SKILLKIT_MODE"] = budget + "(bypassed)"
    return current


def resolve_model_by_id(model_id, budget, catalog=None):
    if catalog is None:
        catalog = _load_models()
    if catalog is None:
        current = os.environ.get("SKILLKIT_MODEL", "unknown")
        print(f"WARNING: Cannot load model catalog from SKILLKIT_HOME/lib/models.json", file=sys.stderr)
        print(f"  Keeping current model: {current}", file=sys.stderr)
        return current

    user_config = _load_user_config(catalog)
    models = catalog.get("models", [])
    info = next((m for m in models if m["id"] == model_id), {})

    if not info:
        current = os.environ.get("SKILLKIT_MODEL", "unknown")
        print(f"WARNING: Model '{model_id}' not found in catalog", file=sys.stderr)
        print(f"  Keeping current model: {current}", file=sys.stderr)
        return current

    os.environ["SKILLKIT_MODEL"] = info.get("api_model", model_id)
    os.environ["SKILLKIT_MODEL_DESC"] = info.get("description", "")
    os.environ["SKILLKIT_MODE"] = budget
    os.environ["SKILLKIT_PROVIDER"] = info.get("provider", "")

    provider_cfg = _get_provider_config(catalog, user_config, info.get("provider", ""))
    _set_api_env(provider_cfg)

    return model_id


def resolve_model_legacy(modelo_local, modelo_remoto, budget=None):
    budget = _resolve_budget(budget)
    target = modelo_local if budget == "low" else modelo_remoto
    return resolve_model_by_id(target, budget)
