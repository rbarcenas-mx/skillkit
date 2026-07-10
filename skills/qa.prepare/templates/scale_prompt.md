Eres un ingeniero de infraestructura. Genera un plan de prueba de ESCALAMIENTO para el proyecto.

**IMPORTANTE**: Castellano sin acentos. No envuelvas en ```markdown. Empieza con `# Plan de Validacion de Escalamiento`.

## CONTEXTO
{context}

## WORKERS SOLICITADOS
{scale_workers} (modo cluster de Node.js)

## FORMATO DE PASOS
--- STEP
type: shell
id: SNN
desc: Descripcion
command: "comando con && debe ir entre comillas dobles"
checkpoint: true

--- STEP
type: stress
id: SNN
desc: Descripcion
tool: autocannon
target: http://localhost:3000/api/v1/ENDPOINT
method: GET
n: 500
concurrency: 50
expected:
  p95_ms: 500
  success_rate: 95
checkpoint: true

## REGLAS CRITICAS DE FORMATO YAML

1. **Comandos shell con caracteres especiales**: Si un `command` contiene `&&`, `||`, `>`, `|`, `;`, `-i` o `: ` (dos puntos seguidos de espacio), DEBE ir entre comillas dobles: `command: "pm2 start dist/index.js -i {scale_workers}"`.
2. **URL base**: Todas las URLs deben incluir el prefijo de version del proyecto (ej: `/api/v1/`).
3. **No usar `---` suelto**: Solo usa `---` como delimitador de paso (`--- STEP`).
4. **expected.p95_ms y expected.success_rate**: DEBEN ser enteros.
5. **Pasos type: stress**: Tienen campos `tool`, `target`, `method`, `n`, `concurrency`, `expected`. No usan `command`.

## TAREA
Genera un plan que:
1. QA-001: Instalar pm2 si no esta disponible: `command: "npm install -g pm2 2>/dev/null || echo 'pm2 ya instalado'"`
2. QA-002: Levantar la app con {scale_workers} workers via pm2: `command: "export $(grep -v '^#' .env.qa | xargs) && npm run build > /dev/null 2>&1 && pm2 start dist/index.js -i {scale_workers} && sleep 3 && echo 'Workers iniciados'"`
3. QA-003: Health check: `command: "curl -s -o /dev/null -w '%{http_code}' http://localhost:3000/api/v1/nonexistent | grep -q '404' && echo 'Servidor OK' || exit 1"`
4. S01-S03: Prueba de estres contra endpoints clave con autocannon
5. S04: Medir uso de CPU y memoria durante la prueba: `command: "pm2 monit"` o `command: "ps aux | grep node | grep -v grep"`
6. S05: Detener los workers: `command: "pm2 delete all && echo 'Workers detenidos'"`
7. S06: Verificar que los workers se detuvieron: `command: "pm2 list | grep -q 'no processes' && echo 'Limpieza OK' || echo 'Algunos procesos siguen activos'"`

## SECCIONES OBLIGATORIAS
- Encabezado
- README
- Checklist de Escenarios
- Prerrequisitos (servidor no debe estar corriendo previamente, Docker arriba, .env.qa preexistente)
- Pasos (--- STEP, type: shell y type: stress)
- Execution Log (vacio, solo "(Sin registros)")

## PLANES EXISTENTES
{existing_plans}

Responde EXACTAMENTE con el documento.