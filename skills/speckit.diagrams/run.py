#!/usr/bin/env python3
"""
speckit.diagrams — Generate Mermaid.js diagrams with local model.

Modes:
  DIAGRAMS_MODE=prepare  : Read artifacts, detect project type, generate manifest.
  DIAGRAMS_MODE=generate : Generate a specific diagram (category + instance).

Input:
  PREPARE:  DIAGRAMS_CONTEXT_FILE
  GENERATE: DIAGRAMS_CATEGORY, DIAGRAMS_INSTANCE, DIAGRAMS_MANIFEST_FILE

Output:
  JSON on stdout with results and token usage.
"""

import json
import os
import re
import subprocess
import sys

sys.stderr.reconfigure(line_buffering=True)
import threading
import time

sys.path.insert(0, os.environ["SKILLKIT_HOME"])
from lib import resolve_model

API_URL = os.environ.get("OPENCODE_API_URL", "http://localhost:11434/v1")
_chat_url = API_URL.rstrip('/')
if not _chat_url.endswith('/chat/completions'):
    _chat_url += '/chat/completions'
API_URL = _chat_url
API_KEY = os.environ.get("OPENCODE_API_KEY", "")
DEFAULT_MODEL = resolve_model("diagrams")
TIMEOUT = 600
MANIFEST_FILE = "/tmp/opencode/diagrams_manifest.json"
CHECKPOINTS_DIR = "/tmp/opencode/diagrams_checkpoints"
PROGRESS_FILE = "/tmp/opencode/diagrams_progress.json"


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def spinner_while_waiting(stop_event, label="Processing"):
    frames = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
    i = 0
    t0 = time.time()
    while not stop_event.is_set():
        elapsed = time.time() - t0
        sys.stderr.write(f'\r  {frames[i % len(frames)]} {label} ({elapsed:.0f}s)   ')
        sys.stderr.flush()
        i += 1
        time.sleep(0.15)
    elapsed = time.time() - t0
    sys.stderr.write(f'\r  {"\u2705"} {label} — completed in {elapsed:.1f}s   \n')
    sys.stderr.flush()


def run_ollama(system_prompt: str, user_msg: str, model: str,
               num_predict: int = 4096) -> tuple:
    payload = {
        "model": model,
        "stream": False,
        "options": {"num_predict": num_predict},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
    }
    payload_path = "/tmp/opencode/diagrams_payload.json"
    os.makedirs("/tmp/opencode", exist_ok=True)
    with open(payload_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    try:
        headers = ["-H", "Content-Type: application/json"]
        if API_KEY:
            os.makedirs("/tmp/opencode", exist_ok=True)
            with open("/tmp/opencode/skillkit_headers.conf", "w") as _hf:
                _hf.write(f"Authorization: Bearer {API_KEY}\n")
            headers += ["-K", "/tmp/opencode/skillkit_headers.conf"]
        result = subprocess.run(
            ["curl", "-s", "-X", "POST", API_URL,
             *headers, "-d", "@" + payload_path],
            capture_output=True, text=True, timeout=TIMEOUT,
        )
        if result.returncode != 0:
            return None, f"ERROR curl: {result.stderr}"
        if not result.stdout.strip():
            return None, "ERROR: empty response from model"
        resp = json.loads(result.stdout)
        content = resp.get("message", {}).get("content", "")
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
        usage = resp.get("usage", {})
        return content.strip(), usage
    except Exception as e:
        return None, f"ERROR: {e}"


def extract_json(text: str) -> dict:
    m = re.search(r"```json\s*\n(.*?)\n```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    m = re.search(r"```\s*\n(.*?)\n```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return {"error": "Could not extract JSON from model response"}


def save_progress(phase: str, total: int = 0, completed: int = 0,
                  current: str = "", status: str = "running") -> None:
    os.makedirs(os.path.dirname(PROGRESS_FILE), exist_ok=True)
    from datetime import datetime, timezone
    progress = {
        "phase": phase,
        "total": total,
        "completed": completed,
        "current": current,
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False)


# ──────────────────────────────────────────────
# PREPARE: detect project type and build manifest
# ──────────────────────────────────────────────

PREPARE_SYSTEM_PROMPT = r"""Eres un arquitecto de software senior. Analiza los artefactos de un proyecto y determina:

1. Tipo de proyecto (Mobile App, Web App, API/Microservicios, CLI/Herramienta, ML/Data Pipeline)
2. Las categorias de diagramas que aplican (segun el catalogo)
3. El numero de instancias por categoria

Reglas de deteccion de tipo de proyecto:

**Mobile App** (+2 pts): React Native, Flutter, Expo, SwiftUI, Jetpack Compose
**CLI/Herramienta** (+2 pts): CLI, command, tool, terminal, scripts, linea de comandos
**ML/Data Pipeline** (+2 pts): ML, machine learning, model training, pipeline, ETL, data lake, feature store
**API/Microservicios** (+2 pts): microservicios, microservices, message queue, event bus, event-driven, CQRS
**Web App** (+1 pt): React (sin React Native), Vue, Next, Remix, Svelte, Angular, SPA, SSR, HTML, CSS

Empate: gana mayor prioridad (1=Mobile, 2=CLI, 3=ML, 4=API, 5=Web). Sin match: Web App.

## Catalogo por tipo

### Mobile App
| Categoria | Instancias | Descripcion |
|-----------|-----------|-------------|
| screen-flow | 1 | Pantallas y navegacion |
| component-architecture | 1 | Componentes frontend + backend |
| sequence | N | Secuencias de interaccion |
| data-flow | N | Flujos de datos: global + por dominio |
| er-diagram | 1 | Modelo de datos completo |

### Web App
| Categoria | Instancias |
|-----------|-----------|
| layer-architecture | 1 |
| component-architecture | 1 |
| sequence | N |
| data-flow | N |
| er-diagram | 1 |

### API/Microservicios
| Categoria | Instancias |
|-----------|-----------|
| c4-container | 1 |
| component-architecture | N |
| sequence | N |
| data-flow | N |
| er-diagram | N |
| deployment | 1 |

### CLI/Herramienta
| Categoria | Instancias |
|-----------|-----------|
| component-architecture | 1 |
| data-flow | N |
| sequence | N |

### ML/Data Pipeline
| Categoria | Instancias |
|-----------|-----------|
| pipeline-etl | 1 |
| component-architecture | 1 |
| data-flow | N |
| er-diagram | 1 |

## Deteccion de instancias

### Para sequence:
- Analiza spec.md y contracts/. Agrupa endpoints por entidad/dominio.
- Por cada grupo con >1 endpoint que represente un flujo de negocio: un diagrama.
- Nombres sugeridos: auth, mandado-registro, oferta-aceptacion, mensajeria, calificacion, denuncia, verificacion

### Para data-flow:
- Siempre core-data-flow (overview global).
- Adicional por cada dominio/entidad con flujo significativo (mandado, oferta, mensaje, etc.)

### Para component-architecture (API/Microservicios):
- Uno por microservicio detectado.

### Nombrado de archivos:
- Fijos: {categoria}.md
- Multiples: {categoria}-{nombre}.md (ej: sequence-auth.md, data-flow-mandado.md, er-usuarios.md)

## Reglas de sintaxis Mermaid

- erDiagram para modelos de datos
- sequenceDiagram para secuencias
- flowchart LR/TD para flujos de datos y pantallas
- flowchart TB con subgraphs para arquitectura de componentes
- C4Context/C4Container para C4
- Use comillas dobles: A["Etiqueta (texto)"]
- Evite parentesis, dos puntos, ampersand, llaves sin escapar en etiquetas []

Responde EXACTAMENTE con este JSON (sin texto fuera del JSON):

{
  "project_type": "Mobile App",
  "feature": "feature-name",
  "summary": "descripcion corta del proyecto",
  "diagrams": [
    { "category": "screen-flow", "instance": "1", "filename": "screen-flow.md", "title": "Flujo de Pantallas" },
    { "category": "sequence", "instance": "auth", "filename": "sequence-auth.md", "title": "Secuencia de Autenticacion" },
    { "category": "sequence", "instance": "mandado", "filename": "sequence-mandado.md", "title": "Secuencia de Creacion de Mandado" }
  ]
}

- Usa nombres en espanol para todo.
- Sin placeholders.
- No omitas ningun diagrama que corresponda.
- Responde unicamente en espanol."""


def mode_prepare():
    context_path = os.environ.get("DIAGRAMS_CONTEXT_FILE", "/tmp/opencode/diagrams_context.json")
    try:
        with open(context_path, "r", encoding="utf-8") as f:
            ctx = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        result = {"status": "error", "error": f"Could not read context: {e}"}
        print(json.dumps(result))
        sys.exit(1)

    model = os.environ.get("DIAGRAMS_MODEL", DEFAULT_MODEL)
    feature = ctx.get("feature", "unknown")
    artifacts = ctx.get("artifacts", {})

    total_chars = sum(len(v) for v in artifacts.values())
    log(f" Feature: {feature}")
    log(f" Artifacts: {list(artifacts.keys())} ({total_chars} chars)")
    log(f" Model: {model}")

    user_msg_parts = [f"## Feature: {feature}\n"]
    for name, content in artifacts.items():
        if content:
            user_msg_parts.append(f"=== {name.upper()} ===\n{content}")
    user_msg = "\n\n".join(user_msg_parts)

    save_progress("prepare", status="running")

    log(" Preparing diagram manifest...")
    stop_spinner = threading.Event()
    spinner_thread = threading.Thread(
        target=spinner_while_waiting,
        args=(stop_spinner, f"{model} detecting diagrams")
    )
    spinner_thread.start()
    try:
        result, usage = run_ollama(PREPARE_SYSTEM_PROMPT, user_msg, model, num_predict=4096)
    finally:
        stop_spinner.set()
        spinner_thread.join()

    if result is None or result.startswith("ERROR"):
        log(f" ERROR: {result}")
        save_progress("prepare", status="failed")
        print(json.dumps({"status": "error", "error": result}))
        sys.exit(1)

    data = extract_json(result)
    if "error" in data or "diagrams" not in data:
        log(f" ERROR: {data.get('error', 'No diagram list found')}")
        save_progress("prepare", status="failed")
        print(json.dumps({"status": "error", "error": "Invalid model response"}, ensure_ascii=False))
        sys.exit(1)

    data["status"] = "ok"
    data["_tokens"] = {
        "prompt_eval_count": usage.get("prompt_eval_count", 0),
        "eval_count": usage.get("eval_count", 0),
    }

    os.makedirs(os.path.dirname(MANIFEST_FILE), exist_ok=True)
    with open(MANIFEST_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    diagram_count = len(data.get("diagrams", []))
    save_progress("prepare", total=diagram_count, completed=0, status="done")

    log(f" Project type: {data.get('project_type', '?')}")
    log(f" Diagrams in manifest: {diagram_count}")

    print(json.dumps(data, ensure_ascii=False, indent=2))


# ──────────────────────────────────────────────
# GENERATE: generate a single diagram
# ──────────────────────────────────────────────

GENERATE_SYSTEM_PROMPT_TEMPLATE = r"""Eres un arquitecto de software senior experto en Mermaid.js.

Contexto del proyecto:
{tipo_proyecto}
Feature: {feature}

## Diagrama a generar

Categoria: {category}
Instancia: {instance}
Titulo sugerido: {title}

## Artefactos del proyecto

{artefactos}

## Instrucciones de sintaxis Mermaid (segun categoria)

- erDiagram: {desc_er}
- sequenceDiagram: {desc_seq}
- flowchart LR/TD: {desc_flow}
- flowchart TB con subgraphs: {desc_components}
- C4Context/C4Container: {desc_c4}

### Escape de caracteres:
- Use comillas dobles en etiquetas con parentesis: A["Login (OTP)"]
- Para texto con dos puntos: A["Estado: Activo"]
- Evite parentesis (), dos puntos :, ampersand & y llaves {{}} sin escapar

### Guias de contenido por categoria:

{categoria_rules}

## Instrucciones finales

Responde EXACTAMENTE con este JSON (un solo objeto):

{{
  "filename": "{filename}",
  "content": "# {title}\\n\\n[//]: # (INICIO_DIAGRAMA)\\n\\n```mermaid\\n<tipo>\\n  <contenido>\\n```"
}}

- Diagrama COMPLETO, sin placeholders.
- Basate en entidades/conceptos reales de los artefactos proporcionados.
- Nombres en espanol.
- Escapa correctamente comillas dobles y saltos de linea en el JSON.
- Responde unicamente en espanol.
- No omitas nada del diagrama."""


CATEGORY_RULES = {
    "screen-flow": "flowchart TD: punto de entrada -> auth -> home/tabs -> pantallas core -> perfil. Navegacion condicional con etiquetas.",
    "layer-architecture": "flowchart TB con capas: Presentation, BFF/API, Business Logic, Data Access, Database.",
    "component-architecture": "flowchart TB con subgraphs: Frontend Components, Backend Services, External Services. Conectar con flechas etiquetadas.",
    "c4-container": "C4Container: sistema principal, servicios internos, bases de datos, servicios externos.",
    "sequence": "Flujo end-to-end: actor(es) -> frontend/app -> backend API -> DB -> servicios externos. Usa bloques alt/opt para caminos alternativos.",
    "data-flow": "flowchart LR con subgraphs: Mobile App, Backend API, PostgreSQL/PostGIS, External Services. Muestra todas las interconexiones.",
    "er-diagram": "erDiagram con todas las entidades del data-model.md. Columnas con tipos reales, constraints (PK, FK, UK). Relaciones con cardinalidad (||--o{, }|--||, etc.).",
    "deployment": "Diagrama de bloques: nodos de infraestructura, servicios, balanceadores, bases de datos.",
    "pipeline-etl": "flowchart LR: fuentes de datos -> ingestion -> transformacion -> carga -> consumo.",
}


def mode_generate():
    category = os.environ.get("DIAGRAMS_CATEGORY", "")
    instance = os.environ.get("DIAGRAMS_INSTANCE", "")
    manifest_path = os.environ.get("DIAGRAMS_MANIFEST_FILE", MANIFEST_FILE)
    context_path = os.environ.get("DIAGRAMS_CONTEXT_FILE", "/tmp/opencode/diagrams_context.json")

    try:
        with open(context_path, "r", encoding="utf-8") as f:
            ctx = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        result = {"status": "error", "error": f"Could not read context: {e}"}
        print(json.dumps(result))
        sys.exit(1)

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        result = {"status": "error", "error": f"Could not read manifest: {e}"}
        print(json.dumps(result))
        sys.exit(1)

    target = None
    for d in manifest.get("diagrams", []):
        if d["category"] == category and d.get("instance") == instance:
            target = d
            break

    if not target:
        result = {"status": "error", "error": f"Diagram not found in manifest: {category}/{instance}"}
        print(json.dumps(result))
        sys.exit(1)

    model = os.environ.get("DIAGRAMS_MODEL", DEFAULT_MODEL)
    feature = ctx.get("feature", manifest.get("feature", "unknown"))
    project_type = manifest.get("project_type", "unknown")
    filename = target.get("filename", f"{category}-{instance}.md")
    title = target.get("title", f"{category} - {instance}")

    artifacts = ctx.get("artifacts", {})
    artefactos_str = "\n\n".join(
        f"=== {name.upper()} ===\n{content}"
        for name, content in artifacts.items() if content
    )

    desc_er = "erDiagram con entidades, columnas y relaciones"
    desc_seq = "sequenceDiagram con actores y participantes"
    desc_flow = "flowchart LR o TD con nodos y flechas"
    desc_components = "flowchart TB con subgraphs"
    desc_c4 = "C4Container o C4Context"

    categoria_rules = CATEGORY_RULES.get(category, "Usa sintaxis Mermaid estandar apropiada para esta categoria.")

    system_prompt = GENERATE_SYSTEM_PROMPT_TEMPLATE.format(
        tipo_proyecto=project_type,
        feature=feature,
        category=category,
        instance=instance,
        title=title,
        artefactos=artefactos_str,
        desc_er=desc_er,
        desc_seq=desc_seq,
        desc_flow=desc_flow,
        desc_components=desc_components,
        desc_c4=desc_c4,
        categoria_rules=categoria_rules,
        filename=filename,
    )

    user_msg = f"Genera el diagrama {category} - {instance} ({title}) para el feature {feature}."

    save_progress("generate", current=f"{category}_{instance}", status="running")

    stop_spinner = threading.Event()
    spinner_thread = threading.Thread(
        target=spinner_while_waiting,
        args=(stop_spinner, f"{model} generating {filename}")
    )
    spinner_thread.start()
    try:
        result, usage = run_ollama(system_prompt, user_msg, model, num_predict=4096)
    finally:
        stop_spinner.set()
        spinner_thread.join()

    if result is None or result.startswith("ERROR"):
        log(f" ERROR generating {filename}: {result}")
        save_progress("generate", current=f"{category}_{instance}", status="failed")
        print(json.dumps({"status": "error", "error": result}))
        sys.exit(1)

    data = extract_json(result)
    if "error" in data:
        log(f" ERROR extracting JSON: {data['error']}")
        save_progress("generate", current=f"{category}_{instance}", status="failed")
        print(json.dumps({"status": "error", "error": "Invalid model response"}))
        sys.exit(1)

    data["status"] = "ok"
    data["_tokens"] = {
        "prompt_eval_count": usage.get("prompt_eval_count", 0),
        "eval_count": usage.get("eval_count", 0),
    }
    data["category"] = category
    data["instance"] = instance

    os.makedirs(CHECKPOINTS_DIR, exist_ok=True)
    checkpoint_file = os.path.join(CHECKPOINTS_DIR, f"{category}_{instance}.json")
    with open(checkpoint_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    save_progress("generate", current=f"{category}_{instance}", status="done")

    print(json.dumps(data, ensure_ascii=False, indent=2))


def main():
    mode = os.environ.get("DIAGRAMS_MODE", "prepare")
    if mode == "prepare":
        mode_prepare()
    elif mode == "generate":
        mode_generate()
    else:
        result = {"status": "error", "error": f"Unknown mode: {mode}. Use 'prepare' or 'generate'."}
        print(json.dumps(result))
        sys.exit(1)


if __name__ == "__main__":
    main()
