Eres un ingeniero DevOps/QA senior. Tu tarea es analizar el contexto de un proyecto de software y generar un plan de validacion de INFRAESTRUCTURA.

**IMPORTANTE**: 
- Responde unicamente en castellano/espanol SIN acentos ni caracteres especiales.
- NO envuelvas el documento en bloques ```markdown. 
- El documento debe empezar directamente con `# Plan de Validacion de Infraestructura`.
- NO uses `---` como separador de secciones Markdown. Solo usa `--- STEP` como delimitador de pasos. 
- Cualquier `---` suelto causara que el parser YAML falle y el plan sea RECHAZADO.

## CONTEXTO DEL PROYECTO
{context}

## FORMATO DE PASOS (OBLIGATORIO)

Cada paso DEBE usar este formato YAML exacto delimitado por `--- STEP`:

--- STEP
type: shell
id: QA-NNN
desc: Descripcion breve del paso
command: "comando con && debe ir entre comillas dobles"
checkpoint: true
max_retries: 1

## REGLAS CRITICAS DE FORMATO YAML

1. **Comandos shell con caracteres especiales**: Si un `command` contiene `&&`, `||`, `>`, `|`, `;` o `: ` (dos puntos seguidos de espacio), DEBE ir entre comillas dobles: `command: "comando && otro"`
2. **NO usar `---` suelto**: Solo usa `---` como delimitador de paso (`--- STEP`). Separadores Markdown `---` entre secciones rompen el parser YAML y el plan sera RECHAZADO.
3. **No usar printf para generar archivos al vuelo**: Los archivos de configuracion (.env.qa, docker-compose.yml) DEBEN ser preexistentes. El plan debe VERIFICAR que existen.
4. **NO usar `npx prisma db seed`**: Este comando NO EXISTE en Prisma. Causara error. Usar `npx tsx prisma/seed.ts`.
5. **NO incluir `npx prisma generate`**: El comando `prisma db push` ya genera el cliente automaticamente. Incluirlo solo agrega tiempo innecesario.

## TAREA

Genera un plan de validacion de infraestructura con EXACTAMENTE estos pasos y comandos. NO modifiques los comandos, NY inventes nuevos:

1. QA-001: Verificar prerrequisitos: `command: "node --version && npm --version && docker --version && docker compose version"`
2. QA-002: Instalar dependencias: `command: "npm install"`
3. QA-003: Verificar archivos: `command: "test -f .env.qa && test -f docker-compose.yml && echo 'Archivos OK' || (echo 'Falta configuracion' && exit 1)"`
4. QA-004: Levantar Docker: `command: "docker compose up -d"`
5. QA-005: Health check Postgres+Redis. NO hay servicio "api" en docker-compose.yml: `command: "docker compose ps && docker compose exec -T db pg_isready -U postgres -d mandadero && docker compose exec -T redis redis-cli ping"`
6. QA-006: Migraciones y seed. Usar `grep -v '^#'` (NO `cat`): `command: "export $(grep -v '^#' .env.qa | xargs) && for i in 1 2 3 4 5; do docker compose exec -T db pg_isready -U postgres -d mandadero && break || sleep 2; done && npx prisma db push --accept-data-loss && npx tsx prisma/seed.ts"`

## SECCIONES OBLIGATORIAS

El plan debe incluir:
- Encabezado con `- **run_id**: NNN` (formato exacto: `- **run_id**: 001`, con el guion al inicio), desc, date, total_steps
- README explicando que se prueba y como leer resultados
- Checklist de Escenarios (tabla con ID, Escenario, Pasos, Depende de, Estado)
- Analisis del Stack (tabla con Componente, Detectado, Detalle)
- Prerrequisitos
- Infraestructura Requerida (YAML de docker-compose)
- Variables de Entorno (.env.qa con valores mock — DOCUMENTAR el contenido esperado, no generarlo al vuelo)
- Estrategia de Mocking (Twilio, Cloudinary en modo mock)
- Pasos de Ejecucion (formato --- STEP)
- Execution Log (vacio, solo texto "(Sin registros)" sin tablas)

## PLANES EXISTENTES
{existing_plans}

Responde EXACTAMENTE con el documento markdown generado.