#!/bin/bash
set -e

SKILLKIT="${SKILLKIT_HOME:-$HOME/skillkit}"

echo "=== SkillKit Install ==="
echo ""

# Validate prerequisites
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Install Python 3.10+ first."
    exit 1
fi

if [ ! -f "$SKILLKIT/configure.py" ]; then
    echo "ERROR: configure.py not found in $SKILLKIT"
    echo "  Run this script from your skillkit directory or set SKILLKIT_HOME."
    exit 1
fi

# Interactive configuration via Python
python3 "$SKILLKIT/configure.py"

# --- ensure config dir ---
mkdir -p "$HOME/.config/skillkit"

# --- symlink lib (skillkit config) ---
if [ -d "$HOME/.config/skillkit/lib" ] && [ ! -L "$HOME/.config/skillkit/lib" ]; then
    echo "[~/.config/skillkit/lib] Backing up..."
    mv "$HOME/.config/skillkit/lib" "$HOME/.config/skillkit/lib.bak"
fi
rm -rf "$HOME/.config/skillkit/lib"
ln -sfn "$SKILLKIT/lib" "$HOME/.config/skillkit/lib"
echo "[~/.config/skillkit/lib] → $SKILLKIT/lib"

echo ""
echo "=== Done ==="
echo "Source your shell: source ~/.bashrc"
echo "Or restart your terminal."
