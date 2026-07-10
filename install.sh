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

# --- symlink skills (Claude) ---
if [ -d "$HOME/.claude/skills" ] && [ ! -L "$HOME/.claude/skills" ]; then
    echo "[~/.claude/skills] Backing up existing directory..."
    mv "$HOME/.claude/skills" "$HOME/.claude/skills.bak"
fi
rm -f "$HOME/.claude/skills"
ln -sfn "$SKILLKIT/skills" "$HOME/.claude/skills"
echo "[~/.claude/skills] → $SKILLKIT/skills"

# --- symlink lib (opencode) ---
if [ -d "$HOME/.config/opencode/lib" ] && [ ! -L "$HOME/.config/opencode/lib" ]; then
    echo "[~/.config/opencode/lib] Backing up..."
    mv "$HOME/.config/opencode/lib" "$HOME/.config/opencode/lib.bak"
fi
rm -rf "$HOME/.config/opencode/lib"
ln -sfn "$SKILLKIT/lib" "$HOME/.config/opencode/lib"
echo "[~/.config/opencode/lib] → $SKILLKIT/lib"

# --- symlink commands (opencode) ---
if [ -d "$HOME/.config/opencode/commands" ] && [ ! -L "$HOME/.config/opencode/commands" ]; then
    echo "[~/.config/opencode/commands] Backing up..."
    mv "$HOME/.config/opencode/commands" "$HOME/.config/opencode/commands.bak"
fi
rm -rf "$HOME/.config/opencode/commands"
ln -sfn "$SKILLKIT/commands" "$HOME/.config/opencode/commands"
echo "[~/.config/opencode/commands] → $SKILLKIT/commands"

echo ""
echo "=== Done ==="
echo "Source your shell: source ~/.bashrc"
echo "Or restart your terminal."
