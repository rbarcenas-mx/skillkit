#!/usr/bin/env bash
# Detecta la etapa actual del proyecto spec-kit basado en artefactos existentes
# Output: JSON con stage y paths detectados

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

REPO_ROOT="${1:-.}"
cd "$REPO_ROOT"

HAS_SPEC=false
HAS_PLAN=false
HAS_TASKS=false
HAS_CODE=false
FEATURES=()

# Buscar directorios de features en specs/
if [ -d "specs" ]; then
    for feature_dir in specs/*/; do
        feature_name=$(basename "$feature_dir")
        FEATURES+=("$feature_name")
        [ -f "${feature_dir}spec.md" ] && HAS_SPEC=true
        [ -f "${feature_dir}plan.md" ] && HAS_PLAN=true
        [ -f "${feature_dir}tasks.md" ] && HAS_TASKS=true
    done
fi

# Detectar si existe código fuente relevante
[ -d "src" ] && HAS_CODE=true
[ -d "app" ] && HAS_CODE=true
[ -d "lib" ] && HAS_CODE=true
[ -f "package.json" ] && HAS_CODE=true

# Censo de código (si aplica)
CODE_CENSUS="null"
if $HAS_CODE && [ -f "$SCRIPT_DIR/census-code.sh" ]; then
  CODE_CENSUS=$(bash "$SCRIPT_DIR/census-code.sh" "$REPO_ROOT" 2>/dev/null || echo "null")
fi

# Determinar la etapa
STAGE="none"
if $HAS_CODE && $HAS_TASKS && $HAS_PLAN && $HAS_SPEC; then
    STAGE="codigo"
elif $HAS_TASKS && $HAS_PLAN && $HAS_SPEC; then
    STAGE="tasks"
elif $HAS_PLAN && $HAS_SPEC; then
    STAGE="plan"
elif $HAS_SPEC; then
    STAGE="spec"
fi

cat <<EOF
{
  "stage": "$STAGE",
  "features": [$(printf '"%s",' "${FEATURES[@]}" | sed 's/,$//')],
  "has_spec": $HAS_SPEC,
  "has_plan": $HAS_PLAN,
  "has_tasks": $HAS_TASKS,
  "has_code": $HAS_CODE,
  "code_census": $CODE_CENSUS
}
EOF
