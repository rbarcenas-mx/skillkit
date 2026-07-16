#!/usr/bin/env python3
"""SkillKit interactive setup: detect, configure, install."""

import getpass
import json
import os
import shutil
import subprocess
import sys

SKILLKIT_HOME = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.expanduser("~/.config/skillkit")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")


def c(s, code):
    return f"\033[{code}m{s}\033[0m" if sys.stdout.isatty() else s


def green(s): return c(s, "92")
def yellow(s): return c(s, "93")
def red(s): return c(s, "91")
def bold(s): return c(s, "1")
def dim(s): return c(s, "2")


def step(msg):
    print(f"\n  {bold('→')} {msg}")


def detect_agents():
    agents = {}
    for name, paths in {"opencode": ["opencode", "~/.config/opencode"],
                         "claude": ["claude", "~/.claude"],
                         "aider": ["aider"],
                         "cursor": ["cursor"]}.items():
        for p in paths:
            p = os.path.expanduser(p)
            if os.path.isdir(p) or shutil.which(p):
                agents[name] = p
                break
    return agents


def detect_ollama():
    try:
        r = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return []
        lines = r.stdout.strip().split("\n")[1:]
        return [line.split()[0] for line in lines if line.strip()]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []


def detect_api_keys():
    keys = {}
    for var in ["DEEPSEEK_API_KEY", "OPENCODE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"]:
        val = os.environ.get(var, "")
        if val:
            keys[var] = val[:12] + "..." if len(val) > 15 else "(set)"
    return keys


def detect_shell_rc():
    home = os.path.expanduser("~")
    rc = {"zsh": "~/.zshrc", "bash": "~/.bashrc", "fish": "~/.config/fish/config.fish"}
    shell = os.path.basename(os.environ.get("SHELL", "bash"))
    path = os.path.expanduser(rc.get(shell, "~/.bashrc"))
    return path if os.path.isfile(path) else os.path.join(home, ".profile")


def load_catalog():
    path = os.path.join(SKILLKIT_HOME, "lib", "models.json")
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def load_user_config():
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def ask_yn(prompt_text, default=True):
    d = "Y/n" if default else "y/N"
    a = input(f"    {prompt_text} [{d}] ").strip().lower()
    return default if not a else a.startswith("y")


def ask_choice(prompt_text, options, default=None):
    print(f"    {prompt_text}")
    for i, opt in enumerate(options, 1):
        print(f"      {i}) {opt}{' [default]' if opt == default else ''}")
    while True:
        try:
            idx = input(f"    Choose (1-{len(options)}): ").strip()
            if not idx and default:
                return default
            return options[int(idx) - 1]
        except (ValueError, IndexError):
            print(f"    {red('Invalid')}")


def welcome():
    print(f"\n  {'='*56}")
    print(f"  {bold('SkillKit Setup')}")
    print(f"  {'='*56}")
    print(f"\n  Structured engineering workflows for your AI agent.")
    print(f"  CI, QA, audit, reviews, diagrams — with smart model selection.\n")


def detection_phase():
    agents = detect_agents()
    ollama_models = detect_ollama()
    api_keys = detect_api_keys()
    catalog = load_catalog()
    shell_rc = detect_shell_rc()

    step("Detection")

    print(f"    Agents:      {', '.join(agents) if agents else dim('none detected')}")
    print(f"    Ollama:      {', '.join(ollama_models) if ollama_models else yellow('not found')}")
    print(f"    API keys:    {', '.join(api_keys.keys()) if api_keys else yellow('none detected')}")
    print(f"    Shell rc:    {shell_rc}")

    if not catalog:
        print(f"\n    {red('Error:')} Cannot find {SKILLKIT_HOME}/lib/models.json")
        print(f"    Run from your skillkit directory.")
        sys.exit(1)

    return agents, ollama_models, api_keys, catalog, shell_rc


def budget_phase(ollama_models, api_keys, catalog):
    step("Token budget")

    has_local = len(ollama_models) > 0
    has_remote = len(api_keys) > 0

    print(f"    SkillKit uses low/medium/high to pick the cheapest model")
    print(f"    that can handle each task.")
    print()

    if has_local and not has_remote:
        print(f"    {green('Suggested: low')} (Ollama = $0)")
        budget = ask_choice("Select:", ["low", "medium", "high"], "low")
    elif has_remote and not has_local:
        print(f"    {green('Suggested: medium')} (remote keys detected)")
        budget = ask_choice("Select:", ["medium", "high", "low"], "medium")
    elif has_local and has_remote:
        budget = ask_choice("Select budget:", ["low", "medium", "high"])
    else:
        print(f"    {yellow('No models detected — you can configure models later.')}")
        budget = ask_choice("Select budget:", ["low", "medium", "high"])

    return budget


def ollama_phase(ollama_models, catalog):
    overrides = {}
    if not ollama_models or not ask_yn("Remap Ollama models per skill?", False):
        return overrides

    mapping = catalog.get("skill_mapping", {})
    for skill, entry in mapping.items():
        current = entry.get("low", "")
        if not any(m.get("provider") == "ollama" for m in catalog.get("models", []) if m["id"] == current):
            continue
        choices = ollama_models + ["(keep)"]
        chosen = ask_choice(f"  {skill} (current: {current}):", choices, current if current in ollama_models else "(keep)")
        if chosen != "(keep)":
            overrides[skill] = chosen
    return overrides


def remote_phase(api_keys, catalog):
    config_updates = {}

    if not ask_yn("Configure remote providers?", False):
        return config_updates, []

    providers_info = {
        "deepseek": {"env": "DEEPSEEK_API_KEY", "url": "https://api.deepseek.com"},
        "opencode-go": {"env": "OPENCODE_API_KEY", "url": "https://opencode.ai/zen/go/v1"},
        "anthropic": {"env": "ANTHROPIC_API_KEY", "url": "https://api.anthropic.com"},
    }

    existing = load_user_config().get("providers", {})
    env_exports = []

    for prov, info in providers_info.items():
        if info["env"] in api_keys or prov in existing:
            print(f"    {green('✓')} {prov} ({info['env']} configured)")
            continue
        print(f"\n    {bold(prov)} — {info['url']}")
        if ask_yn(f"  Add {prov}?", False):
            key = getpass.getpass(f"    {info['env']}: ")
            if key:
                config_updates[prov] = {"api_key": f"{{env:{info['env']}}}"}
                if ask_yn(f"  Export in shell rc?", True):
                    env_exports.append(f"export {info['env']}=\"{key}\"")
    return config_updates, env_exports


def write_config(budget, ollama_overrides, provider_config, env_exports):
    config = load_user_config()
    config["mode"] = budget

    if provider_config:
        providers = config.get("providers", {})
        providers.update(provider_config)
        config["providers"] = providers

    if ollama_overrides:
        skill_overrides = config.get("skill_model_overrides", {})
        for skill, model in ollama_overrides.items():
            skill_overrides[skill] = {"low": model}
        config["skill_model_overrides"] = skill_overrides

    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    os.chmod(CONFIG_FILE, 0o600)
    print(f"\n    {green('✔')} Saved: {CONFIG_FILE}")

    return env_exports


def update_rc(shell_rc, budget, env_exports):
    step("Shell environment")
    exports = []
    if "SKILLKIT_HOME" not in os.environ:
        exports.append(f"\n# SkillKit\nexport SKILLKIT_HOME=\"{SKILLKIT_HOME}\"")
    if "TOKEN_BUDGET" not in os.environ:
        exports.append(f"export TOKEN_BUDGET={budget}")
    exports.extend(env_exports)

    if not exports:
        print(f"    {green('Already configured')}")
        return

    with open(shell_rc, "a") as f:
        f.write("\n".join(exports) + "\n")
    print(f"    {green('✔')} Added to {shell_rc}")
    print(f"    {dim('Run: source ' + shell_rc)}")


def symlink_phase(agents):
    step("Agent integration")

    if "claude" in agents:
        claude = os.path.expanduser("~/.claude")
        if os.path.isdir(claude) and not os.path.islink(os.path.join(claude, "skills")):
            shutil.move(os.path.join(claude, "skills"), os.path.join(claude, "skills.bak")) if os.path.isdir(os.path.join(claude, "skills")) else None
            os.symlink(os.path.join(SKILLKIT_HOME, "skills"), os.path.join(claude, "skills"))
            print(f"    {green('✔')} Claude skills → ~/.claude/skills")

    if "opencode" in agents:
        oc = os.path.expanduser("~/.config/opencode")
        if os.path.isdir(oc) and not os.path.islink(os.path.join(oc, "commands")):
            shutil.move(os.path.join(oc, "commands"), os.path.join(oc, "commands.bak")) if os.path.isdir(os.path.join(oc, "commands")) else None
            os.symlink(os.path.join(SKILLKIT_HOME, "commands"), os.path.join(oc, "commands"))
            print(f"    {green('✔')} opencode commands → ~/.config/opencode/commands")


def instructions_phase(agents):
    step("Agent usage")
    tips = {
        "opencode": "  Run: /ci.prepare  (commands auto-discovered)",
        "claude": "  Skills auto-loaded in ~/.claude/skills/",
        "aider": "  Use: aider --read skills/<name>/SKILL.md",
        "cursor": "  Add SKILL.md as context (@mention or instructions)",
    }
    if agents:
        for a in agents:
            if a in tips:
                print(f"  {bold(a)}: {tips[a]}")
    else:
        print(f"  {yellow('No agent detected.')} SkillKit works with any agent that")
        print(f"  reads Markdown and runs bash. See README.md.")
    print(f"\n  {dim('Docs: README.md | CONTRIBUTING.md')}")


def summary(budget, providers, shell_rc):
    print(f"\n  {'='*56}")
    print(f"  {green(bold('Setup complete!'))}")
    print(f"  {'='*56}")
    print(f"\n  Budget:     {bold(budget)}")
    print(f"  Providers:  {', '.join(providers) if providers else 'none'}")
    print(f"  Config:     {CONFIG_FILE}")
    print(f"  Shell rc:   {shell_rc}")
    print(f"\n  {dim('Run: source ' + os.path.basename(shell_rc))}")
    print()


def main():
    welcome()

    agents, ollama_models, api_keys, catalog, shell_rc = detection_phase()
    budget = budget_phase(ollama_models, api_keys, catalog)
    ollama_overrides = ollama_phase(ollama_models, catalog)
    provider_config, env_exports = remote_phase(api_keys, catalog)

    write_config(budget, ollama_overrides, provider_config, env_exports)
    update_rc(shell_rc, budget, env_exports)
    symlink_phase(agents)
    instructions_phase(agents)
    summary(budget, provider_config, shell_rc)


if __name__ == "__main__":
    main()
