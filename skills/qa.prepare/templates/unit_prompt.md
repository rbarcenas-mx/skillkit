Eres un ingeniero DevOps/QA senior. Genera un plan de validacion de TESTS UNITARIOS Y CALIDAD DE CODIGO.

**IMPORTANTE**: Castellano sin acentos. No envuelvas en ```markdown. Empieza con `# Plan de Validacion de Codigo`.

## CONTEXTO
{context}

## FORMATO DE PASOS (OBLIGATORIO)
Cada paso DEBE usar:

--- STEP
type: shell
id: QA-NNN
desc: Descripcion
command: "comando con && debe ir entre comillas dobles"
checkpoint: true

## REGLAS CRITICAS DE FORMATO YAML

1. **Comandos shell con caracteres especiales**: Si un `command` contiene `&&`, `||`, `>`, `|`, `;` o `: ` (dos puntos seguidos de espacio), DEBE ir entre comillas dobles: `command: "comando && otro"`
2. **No usar `---` suelto**: Solo usa `---` como delimitador de paso (`--- STEP`). Separadores Markdown `---` entre secciones rompen el parser YAML.
3. **Variables de entorno**: `.env.qa` debe ser un archivo preexistente. El plan debe CARGAR sus variables (`export $(grep -v '^#' .env.qa | xargs)`) pero no generarlo.
4. **Tests unitarios**: Si el proyecto solo tiene tests de integracion (no unitarios), el comando de tests debe usar `--passWithNoTests` para no fallar: `command: "export $(grep -v '^#' .env.qa | xargs) && npx jest --passWithNoTests --testPathIgnorePatterns='tests/integration'"`

## TAREA
Genera un plan con estos pasos:
1. QA-001: Instalar dependencias (npm install)
2. QA-002: Typecheck (npx tsc --noEmit)
3. QA-003: Lint (npm run lint o npx eslint src/ tests/ --ext .ts)
4. QA-004: Tests unitarios — cargar .env.qa, ejecutar jest excluyendo tests de integracion. Si no hay tests unitarios, usar --passWithNoTests.
5. QA-005: Formato — primero auto-formatear con `--write`, luego verificar con `--check`: `command: "npx prettier --write 'src/**/*.ts' 'tests/**/*.ts' 'prisma/**/*.ts' && npx prettier --check 'src/**/*.ts' 'tests/**/*.ts' 'prisma/**/*.ts'"`

## REGLA DE COMILLAS
Los comandos con `&&` o `||` DEBEN ir entre comillas dobles: `command: "comando && otro"`

## SECCIONES OBLIGATORIAS
- Encabezado (run_id, desc, date, total_steps)
- README
- Checklist de Escenarios (tabla: ID, Escenario, Pasos, Estado)
- Analisis del Stack
- Prerrequisitos (Node.js, npm, .env.qa preexistente)
- Variables de Entorno (.env.qa — documentar contenido esperado)
- Pasos (--- STEP)
- Execution Log (vacio, solo "(Sin registros)")

## PLANES EXISTENTES
{existing_plans}

Responde EXACTAMENTE con el documento.