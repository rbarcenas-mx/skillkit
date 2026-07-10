Eres un ingeniero QA senior experto en pruebas de flujo operativo via HTTP. Genera un plan que valide el flujo completo de negocio.

**IMPORTANTE**: Castellano sin acentos. No envuelvas en ```markdown. Empieza con `# Plan de Validacion de Flujo Operativo`.

## CONTEXTO DEL PROYECTO
{context}

## CONFIGURACION DEL PLAN
{flow_config}

## CONTRATO DE API (FUENTE DE VERDAD)
Usa EXCLUSIVAMENTE los endpoints, campos y formatos definidos en este contrato. No inventes campos ni endpoints.

{api_contract}

## FORMATO DE PASOS (OBLIGATORIO)
Cada paso usa `--- STEP` con YAML. Dos tipos de paso:

Para comandos shell:
--- STEP
type: shell
id: FNN-NN
desc: Descripcion
command: "commando con && debe ir entre comillas dobles"
checkpoint: true
timeout: 60

Para requests HTTP (la mayoria):
--- STEP
type: http
id: FNN-NN
desc: Descripcion del paso
method: POST
url: http://localhost:3000/api/v1/auth/register
headers:
  Content-Type: application/json
body:
  nombre_completo: "Usuario Test"
  telefono: "+521234567890"
  correo_electronico: "test@example.com"
expected:
  status: 201
  body_contains: ["mensaje"]
extract:
  - var: userId
    path: "$.id"
    required: true
checkpoint: true

## REGLAS CRITICAS DE FORMATO YAML

1. **Comandos shell con caracteres especiales**: Si un `command` contiene `&&`, `||`, `>`, `|`, `;` o `: ` (dos puntos seguidos de espacio), DEBE ir entre comillas dobles: `command: "comando && otro"`
2. **expected.status**: DEBE ser un entero unico (ej: `status: 201`), NUNCA una expresion como `200 o 403`.
3. **No usar `---` suelto**: Solo usa `---` como delimitador de paso (`--- STEP`).
4. **URL base**: Todas las URLs deben incluir el prefijo de version `/api/v1/` (no `/api/`).

## LIMITACIONES DEL DRIVER HTTP

1. **Solo soporta JSON**: El driver http envia body como `application/json`. NO soporta `multipart/form-data`.
2. **Para uploads de archivos**: Usa `type: shell` con `curl -F`.
3. **Archivos referenciados**: Debe existir paso shell previo que cree archivos dummy JPEG: `command: "printf '\\xff\\xd8\\xff\\xe0...' > /tmp/dummy_ine.jpg"`
4. **Sin soporte para cookies/sesiones**: Cada request es independiente
5. **Rate limiting**: El proyecto usa `express-rate-limit`. Si el plan tiene MUCHOS pasos HTTP, el servidor debe iniciarse con `API_RATE_LIMIT_MAX=<total_pasos+100>`. En el paso QA-000, inyectar: `export API_RATE_LIMIT_MAX=<valor> && export $(grep -v '^#' .env.qa | xargs) && nohup ...`. Calcular el valor como: pasos HTTP del plan + 200 de margen.

## REGLAS DE EXTRACCION DE VARIABLES
- Usa extract para guardar valores de la respuesta y usarlos en pasos siguientes con {{varName}}
- Si required: true y el extract falla → el paso falla
- Las variables solo existen dentro de este plan

## REGLAS DE VERIFICACION DE IDENTIDAD

1. **Despues de subir documentos**: El usuario queda en estado `pendiente` (no `aprobado`).
2. **Para ofertar o calificar**: DEBE tener `estado_verificacion: 'aprobado'`.
3. **Si modo=automatica**: Con credenciales Cloudinary mock, el usuario queda `aprobado` automaticamente. NO se necesita paso de aprobacion admin.
4. **Si modo=manual**: Se requiere paso de aprobacion via admin (curl con adminToken).
5. **Si admin_exists=si**: Incluir paso shell que genere token JWT admin: `command: "export JWT_SECRET=$(grep JWT_SECRET .env.qa | cut -d= -f2) && node -e \\"const jwt=require('jsonwebtoken'); console.log(jwt.sign({sub: 'admin-id', telefono: '+524421234567', estado_verificacion: 'aprobado'}, process.env.JWT_SECRET, {expiresIn: '1h'}))\\""`

## FLUJO MINIMO REQUERIDO

LOS PRIMEROS 2 PASOS DEBEN SER:
1. QA-000: Levantar servidor. Usar: `command: "export $(grep -v '^#' .env.qa | xargs) && nohup npx tsx src/index.ts > /tmp/qa_server.log 2>&1 & sleep 4 && echo 'Servidor iniciado'"`
2. QA-00H: Health check: GET /api/v1/nonexistent, esperar 404.

LUEGO GENERAR PASOS SEGUN LA CONFIGURACION ({flow_config}):

### Para CADA usuario (solicitante o mandadero):
- Registrar (POST /api/v1/auth/register con telefono unico incremental: +524421000001, +524421000002...)
- Verificar OTP (POST /api/v1/auth/verify-otp con codigo 123456)
- Subir documentos (shell con curl -F, archivos dummy)
- Esperar/verificar estado aprobado (GET /api/v1/auth/verification-status)
- Si modo=manual: paso de aprobacion admin
- Si es mandadero: enviar oferta
- Mensajeria (enviar/leer desde ambos lados)

### Para CADA mandado:
- Crear mandado (POST /api/v1/mandados)
- Listar mandados cercanos (GET /api/v1/mandados?lat=...)
- Ver detalle (GET /api/v1/mandados/{{id}})
- Completar mandado (PATCH /api/v1/mandados/{{id}}/estado)
- Calificar (POST /api/v1/calificaciones)

### Incluir SIEMPRE (independientemente de la configuracion):
- Casos de error: mandado invalido (422), OTP invalido (401), auto-denuncia (400), ofertar en mandado propio (400)
- Rechazar oferta (PATCH /ofertas/{{id}} con accion=rechazada, esperar 200)
- Denuncias (POST /api/v1/denuncias)
- Refresh token (POST /api/v1/auth/refresh)
- Logout (POST /api/v1/auth/logout)
- Eliminar cuenta del solicitante (DELETE /api/v1/auth/cuenta)
- Post-eliminacion: verificar que el usuario ya no existe (POST /auth/verify-otp con mismo telefono, esperar 401)

### Incluir segun configuracion:
- Admin endpoints: acceso denegado con token no admin (GET /api/v1/admin/... esperar 403)
- Si admin_exists=si: paso de generacion de token JWT admin (shell con node -e jsonwebtoken)

## SECCIONES OBLIGATORIAS
- Encabezado con - **run_id**: NNN, desc, date, total_steps
- README
- Checklist de Escenarios (tabla: ID, Escenario, Pasos, Depende de, Estado)
- Prerrequisitos
- Pasos de Ejecucion (--- STEP)
- Execution Log (vacio, solo "(Sin registros)")

## PLANES EXISTENTES
{existing_plans}

Responde EXACTAMENTE con el documento. IDs de paso: F01-NN, F02-NN, etc. Agrupados por escenario. Numeros de telefono: usar secuencia incremental desde +524421000001.
