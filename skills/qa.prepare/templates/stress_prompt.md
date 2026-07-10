Eres un ingeniero de rendimiento. Genera un plan de prueba de ESTRES contra endpoints del proyecto.

**IMPORTANTE**: Castellano sin acentos. No envuelvas en ```markdown. Empieza con `# Plan de Validacion de Estres`.

## CONTEXTO
{context}

## NIVEL DE ESTRES SOLICITADO
{stress_level}

## FORMATO DE PASOS
--- STEP
type: stress
id: SNN
desc: Descripcion
tool: autocannon
target: http://localhost:3000/api/v1/ENDPOINT
method: POST
n: 500
concurrency: 50
expected:
  p95_ms: 500
  success_rate: 98
checkpoint: true

--- STEP
type: shell
id: SNN
desc: Health check previo
command: "curl -s -o /dev/null -w '%{http_code}' http://localhost:3000/api/v1/nonexistent | grep -q '404' && echo 'Servidor OK' || exit 1"
checkpoint: true

## REGLAS CRITICAS DE FORMATO YAML

1. **URL base**: Todas las URLs deben incluir el prefijo de version del proyecto (ej: `/api/v1/`). Revisa el contexto del proyecto para determinar el prefijo correcto.
2. **Comandos shell con caracteres especiales**: Si un `command` contiene `&&`, `||`, `>`, `|`, `;` o `: ` (dos puntos seguidos de espacio), DEBE ir entre comillas dobles.
3. **No usar `---` suelto**: Solo usa `---` como delimitador de paso (`--- STEP`).
4. **expected.p95_ms y expected.success_rate**: DEBEN ser enteros, no strings.

## TAREA
Genera pasos de estres contra los endpoints principales del proyecto.
Usa autocannon como herramienta.

Niveles:
- ligero: n=100, c=10, p95<300, rate>99
- medio: n=500, c=50, p95<500, rate>98
- pesado: n=2000, c=100, p95<1000, rate>95

Ajusta segun el nivel: {stress_level}

Incluye:
1. Paso shell previo: verificar que el servidor responde (health check)
2. Para endpoints POST/PUT que requieren autenticacion: incluir paso shell previo que registre un usuario y obtenga token via curl, guardando el token en variable de entorno
3. Pasos stress contra endpoints clave (registro, login, listado, creacion)
4. Paso shell final: verificar que el servidor sigue respondiendo post-estres

## SECCIONES OBLIGATORIAS
- Encabezado
- README (nivel, endpoints probados, umbrales)
- Checklist de Escenarios
- Prerrequisitos (servidor corriendo, Docker arriba, .env.qa preexistente)
- Pasos (--- STEP, type: stress y type: shell)
- Execution Log (vacio, solo "(Sin registros)")

## PLANES EXISTENTES
{existing_plans}

Responde EXACTAMENTE con el documento.