#!/usr/bin/env bash
# Censa archivos fuente del proyecto, los agrupa por capa y calcula líneas totales
# Output: JSON con layers, total_files, total_lines

set -euo pipefail

REPO_ROOT="${1:-.}"
cd "$REPO_ROOT"

# Definir capas con patrones de ruta (expansion de glob)
declare -A LAYER_PATTERNS
LAYER_PATTERNS["models"]="prisma/ src/models/"
LAYER_PATTERNS["services"]="src/services/"
LAYER_PATTERNS["controllers"]="src/controllers/"
LAYER_PATTERNS["middleware"]="src/middleware/"
LAYER_PATTERNS["repositories"]="src/repositories/"
LAYER_PATTERNS["routes"]="src/routes/"
LAYER_PATTERNS["config"]="src/config/"
LAYER_PATTERNS["utils"]="src/utils/"
LAYER_PATTERNS["tests"]="tests/ test/ __tests__/"

declare -A LAYER_FILES
declare -A LAYER_LINES
for l in models services controllers middleware repositories routes config utils tests other; do
  LAYER_FILES[$l]=0
  LAYER_LINES[$l]=0
done
TOTAL_FILES=0
TOTAL_LINES=0

# Recolectar todos los archivos fuente
ALL_FILES=()
while IFS= read -r -d '' f; do
  ALL_FILES+=("$f")
done < <(find . -type f \( -name "*.ts" -o -name "*.tsx" -o -name "*.js" -o -name "*.jsx" -o -name "*.py" \) -not -path './node_modules/*' -not -path './.git/*' -not -path './dist/*' -not -path './build/*' -not -path './.specify/*' -not -path './.opencode/*' -print0 2>/dev/null | sort -z)

# Asignar cada archivo a una capa
for f in "${ALL_FILES[@]}"; do
  matched=false
  for layer in models services controllers middleware repositories routes config utils tests; do
    for pattern in ${LAYER_PATTERNS[$layer]}; do
      if [[ "$f" == ./$pattern* ]] || [[ "$f" == $pattern* ]]; then
        lines=$(wc -l < "$f" 2>/dev/null || echo 0)
        LAYER_FILES[$layer]=$((LAYER_FILES[$layer] + 1))
        LAYER_LINES[$layer]=$((LAYER_LINES[$layer] + lines))
        TOTAL_FILES=$((TOTAL_FILES + 1))
        TOTAL_LINES=$((TOTAL_LINES + lines))
        matched=true
        break 2
      fi
    done
  done
  if [ "$matched" = false ]; then
    lines=$(wc -l < "$f" 2>/dev/null || echo 0)
    LAYER_FILES["other"]=$((LAYER_FILES["other"] + 1))
    LAYER_LINES["other"]=$((LAYER_LINES["other"] + lines))
    TOTAL_FILES=$((TOTAL_FILES + 1))
    TOTAL_LINES=$((TOTAL_LINES + lines))
  fi
done

# Construir JSON de capas
LAYER_JSON=""
for layer in models services controllers middleware repositories routes config utils tests other; do
  count=${LAYER_FILES[$layer]:-0}
  linecount=${LAYER_LINES[$layer]:-0}
  [ -n "$LAYER_JSON" ] && LAYER_JSON="$LAYER_JSON,"
  LAYER_JSON="$LAYER_JSON\"$layer\":{\"files\":$count,\"lines\":$linecount}"
done

# Calcular batches sugeridos (~500 líneas por batch, mínimo 1 batch si hay archivos)
BATCH_JSON=""
for layer in models services controllers middleware repositories routes config utils tests other; do
  count=${LAYER_FILES[$layer]:-0}
  linecount=${LAYER_LINES[$layer]:-0}
  if [ "$count" -gt 0 ]; then
    batches=$(( (linecount / 500) + 1 ))
  else
    batches=0
  fi
  [ -n "$BATCH_JSON" ] && BATCH_JSON="$BATCH_JSON,"
  BATCH_JSON="$BATCH_JSON\"$layer\":$batches"
done

cat <<EOF
{
  "total_files": $TOTAL_FILES,
  "total_lines": $TOTAL_LINES,
  "layers": {$LAYER_JSON},
  "batches_suggested": {$BATCH_JSON}
}
EOF
