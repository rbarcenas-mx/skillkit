#!/bin/bash
set -e

SKILLKIT="${SKILLKIT_HOME:-$HOME/skillkit}"

echo "=== SkillKit Install ==="
echo "SKILLKIT_HOME: $SKILLKIT"
echo ""

# --- env vars ---
if ! grep -q "SKILLKIT_HOME" ~/.bashrc 2>/dev/null; then
    echo "export SKILLKIT_HOME=\"$SKILLKIT\"" >> ~/.bashrc
    echo "[~/.bashrc] Added SKILLKIT_HOME"
fi
if ! grep -q "TOKEN_BUDGET" ~/.bashrc 2>/dev/null; then
    echo "export TOKEN_BUDGET=low" >> ~/.bashrc
    echo "[~/.bashrc] Added TOKEN_BUDGET=low"
fi

# --- ensure skillkit config dir exists ---
mkdir -p "$HOME/.config/skillkit"

# --- symlink skills (Claude) ---
if [ -d "$HOME/.claude/skills" ] && [ ! -L "$HOME/.claude/skills" ]; then
    echo "[~/.claude/skills] Backing up existing directory..."
    mv "$HOME/.claude/skills" "$HOME/.claude/skills.bak"
fi
if [ -d "$HOME/.claude" ]; then
    rm -f "$HOME/.claude/skills"
    ln -sfn "$SKILLKIT/skills" "$HOME/.claude/skills"
    echo "[~/.claude/skills] → $SKILLKIT/skills"
fi

# --- symlink lib (skillkit config) ---
if [ -d "$HOME/.config/skillkit/lib" ] && [ ! -L "$HOME/.config/skillkit/lib" ]; then
    echo "[~/.config/skillkit/lib] Backing up..."
    mv "$HOME/.config/skillkit/lib" "$HOME/.config/skillkit/lib.bak"
fi
rm -rf "$HOME/.config/skillkit/lib"
ln -sfn "$SKILLKIT/lib" "$HOME/.config/skillkit/lib"
echo "[~/.config/skillkit/lib] → $SKILLKIT/lib"

# --- symlink commands (opencode, optional) ---
if [ -d "$HOME/.config/opencode" ]; then
    if [ -d "$HOME/.config/opencode/commands" ] && [ ! -L "$HOME/.config/opencode/commands" ]; then
        echo "[~/.config/opencode/commands] Backing up..."
        mv "$HOME/.config/opencode/commands" "$HOME/.config/opencode/commands.bak"
    fi
    rm -rf "$HOME/.config/opencode/commands"
    ln -sfn "$SKILLKIT/commands" "$HOME/.config/opencode/commands"
    echo "[~/.config/opencode/commands] → $SKILLKIT/commands"
fi

echo ""
echo "=== Done ==="
echo "Source your shell: source ~/.bashrc"
echo "Or restart your terminal."
