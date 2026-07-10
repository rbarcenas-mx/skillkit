#!/usr/bin/env python3
"""
speckit.prespec — Analyze a raw development idea using a locally-resolved model.

Modes:
  Without PRESPEC_REFINE → initial analysis (generates idea.md sections 1–6)
  With PRESPEC_REFINE=true → refinement with user decisions (sections 1–8)

Input (env vars):
  WORKDIR:            project directory
  IDEA_FILE:          path to idea file (optional)
  IDEA_TEXT:          direct idea text (optional)
  PRESPEC_REFINE:     "true" for refinement mode
  EXISTING_DOC_FILE:  path to file containing existing idea.md content (refine mode)
  EXISTING_DOC:       fallback: existing doc content as string (refine mode)
  USER_DECISIONS:     user decisions text (refine mode)

Output: JSON on stdout + writes/updates idea.md
"""

import json
import os
import re
import subprocess
import sys
import threading
import time

sys.stderr.reconfigure(line_buffering=True)

sys.path.insert(0, os.environ["SKILLKIT_HOME"])
from lib import resolve_model

API_URL = os.environ.get("OPENCODE_API_URL", "http://localhost:11434/v1")
API_KEY = os.environ.get("OPENCODE_API_KEY", "")
MODEL = resolve_model("prespec")
TIMEOUT = 900
PROGRESS_FILE = "/tmp/opencode/prespec_progress.json"


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def save_progress(phase: int, status: str):
    os.makedirs(os.path.dirname(PROGRESS_FILE), exist_ok=True)
    with open(PROGRESS_FILE, "w") as f:
        json.dump({
            "phase": phase,
            "status": status,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }, f)


def spinner(label: str, stop_event: threading.Event):
    chars = "/-\\|"
    i = 0
    while not stop_event.is_set():
        elapsed = int(time.time() - spinner_start)
        sys.stderr.write(f"\r  {chars[i % len(chars)]} {label} ({elapsed}s)   ")
        sys.stderr.flush()
        i += 1
        time.sleep(0.15)
    elapsed = int(time.time() - spinner_start)
    sys.stderr.write(f"\r  {label} ({elapsed}s)   \n")
    sys.stderr.flush()


spinner_start = 0.0


def run_ollama(system_prompt: str, user_msg: str, num_predict: int = 4096) -> str:
    global spinner_start
    payload = {
        "model": MODEL,
        "stream": False,
        "options": {"num_predict": num_predict},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
    }
    payload_path = "/tmp/opencode/prespec_payload.json"
    os.makedirs("/tmp/opencode", exist_ok=True)
    with open(payload_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    spinner_start = time.time()
    stop = threading.Event()
    t = threading.Thread(target=spinner, args=(f"Waiting for {MODEL}...", stop))
    t.start()

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
        stop.set()
        t.join()

        if result.returncode != 0:
            return f"ERROR curl: {result.stderr}"
        if not result.stdout.strip():
            return "ERROR: empty response from model"
        resp = json.loads(result.stdout)
        content = resp.get("message", {}).get("content", "")
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
        return content.strip()
    except subprocess.TimeoutExpired:
        stop.set()
        t.join()
        return "ERROR: timeout — model took too long to respond"
    except Exception as e:
        stop.set()
        t.join()
        return f"ERROR: {e}"


INITIAL_PROMPT = """Eres un analista senior de producto y arquitecto de software con experiencia en startups y productos técnicos. Tu tarea es analizar una idea de desarrollo en bruto y producir un documento de pre-especificacion riguroso.

Analiza la idea proporcionada y responde EXACTAMENTE con las siguientes secciones en orden, sin omitir ninguna:

# Pre-Especificacion: [titulo corto que describe el proyecto]

## 1. Resumen de la Idea
Parafrasea la idea en 2-3 frases para confirmar comprension. Identifica el problema que resuelve y para quien.

## 2. Ambiguedades Detectadas
Lista cada ambiguedad como un item numerado. Una ambiguedad es un termino, requisito o concepto que puede interpretarse de multiples formas. Para cada una:
- Describe la ambiguedad
- Explica las posibles interpretaciones (al menos 2)
- Explica el impacto si no se aclara

## 3. Contradicciones Logicas
Identifica pares de requisitos o conceptos que sean mutuamente excluyentes o generen conflictos de diseno. Si no hay contradicciones evidentes, escribe explicitamente "No se detectaron contradicciones logicas evidentes" y explica por que.

## 4. Piezas Faltantes del Alcance
Lista los aspectos del sistema que NO estan mencionados pero son necesarios. Evalua al menos:
- Autenticacion y autorizacion
- Persistencia y modelo de datos
- Integraciones externas
- Manejo de errores y casos borde
- Infraestructura y despliegue
- Seguridad
- Rendimiento y escalabilidad
- UX y flujos de usuario

## 5. Preguntas Hiper-Criticas para el MVP
Genera EXACTAMENTE 3 o 4 preguntas. Cada pregunta debe:
- Ser especifica al contexto de ESTA idea (no generica)
- Forzar una decision dificil de alcance
- Incluir el contexto de por que es critica
- Presentar opciones concretas (A, B, C) con sus implicaciones reales
- Incluir una recomendacion justificada

## 6. Pre-Especificacion Base del MVP
- **Objetivo principal**: Una frase que describe que resuelve el producto y para quien
- **Usuarios objetivo**: Descripcion del usuario primario con sus necesidades clave
- **Funcionalidades nucleo del MVP** (maximo 5): Solo lo imprescindible para validar el producto
- **Explicitamente FUERA del MVP**: Lo que se construira despues, no ahora
- **Stack tecnico asumido**: Tecnologias deducidas de la idea o recomendadas para el contexto
- **Top 3 riesgos**: Los riesgos mas probables con su impacto estimado
- **Criterios de exito del MVP**: Metricas o hitos que indican que el MVP fue exitoso

Responde unicamente en espanol. No incluyas texto de razonamiento interno, solo el documento final."""


REFINE_PROMPT = """Eres un analista senior de producto. Tu tarea es REFINAR el siguiente documento de pre-especificacion incorporando las decisiones del usuario.

DOCUMENTO EXISTENTE:
{existing_doc}

DECISIONES DEL USUARIO:
{user_decisions}

Genera el documento completo actualizado con las siguientes secciones:
1. Resumen de la Idea (ajusta si las decisiones cambian el alcance)
2. Ambiguedades Detectadas (marca las decididas con "Decision tomada: [opcion]" al final de cada item)
3. Contradicciones Logicas
4. Piezas Faltantes del Alcance (incorpora las decisiones como items especificos)
5. Preguntas Hiper-Criticas para el MVP (puedes mantenerlas como historico o eliminarlas)
6. Pre-Especificacion Base del MVP (actualiza funcionalidades, fuera-del-MVP, riesgos y criterios segun las decisiones)
7. Flujo de Usuario (Happy Path) — describe paso a paso para cada rol identificado
8. Modelo de Datos Basico — lista las entidades principales con sus campos y tipos de datos

Responde unicamente en espanol con el documento completo actualizado."""


def main():
    workdir = os.environ.get("WORKDIR", os.getcwd())
    refine_mode = os.environ.get("PRESPEC_REFINE", "false") == "true"

    if refine_mode:
        # === REFINEMENT MODE ===
        save_progress(2, "starting")

        existing_doc_file = os.environ.get("EXISTING_DOC_FILE", "")
        existing_doc = os.environ.get("EXISTING_DOC", "")
        user_decisions = os.environ.get("USER_DECISIONS", "")

        if existing_doc_file and os.path.exists(existing_doc_file):
            with open(existing_doc_file, "r", encoding="utf-8") as f:
                existing_doc = f.read().strip()
        elif not existing_doc:
            print(json.dumps({"status": "error", "message": "Refine mode needs EXISTING_DOC_FILE or EXISTING_DOC"}))
            sys.exit(1)

        if not user_decisions:
            print(json.dumps({"status": "error", "message": "Refine mode needs USER_DECISIONS"}))
            sys.exit(1)

        log(f"  Mode: refinement")
        log(f"  Existing doc: {len(existing_doc)} chars")
        log(f"  Decisions:    {len(user_decisions)} chars")

        system_prompt = REFINE_PROMPT.format(
            existing_doc=existing_doc, user_decisions=user_decisions)
        user_msg = f"User decisions:\n\n{user_decisions}\n\nExisting document:\n\n{existing_doc}"

        log(f"  Sending to {MODEL} (refinement)...")
        save_progress(2, "running")
        content = run_ollama(system_prompt, user_msg, num_predict=8192)
    else:
        # === INITIAL ANALYSIS MODE ===
        save_progress(1, "starting")

        idea_file = os.environ.get("IDEA_FILE", "")
        idea_text = os.environ.get("IDEA_TEXT", "")

        if idea_file and os.path.exists(idea_file):
            with open(idea_file, "r", encoding="utf-8") as f:
                idea_content = f.read().strip()
            log(f"  Idea loaded from file: {idea_file} ({len(idea_content)} chars)")
        elif os.path.exists(os.path.join(workdir, "idea.txt")):
            with open(os.path.join(workdir, "idea.txt"), "r", encoding="utf-8") as f:
                idea_content = f.read().strip()
            log(f"  Idea loaded from idea.txt ({len(idea_content)} chars)")
        elif idea_text:
            idea_content = idea_text.strip()
            log(f"  Idea loaded from direct text ({len(idea_content)} chars)")
        else:
            print(json.dumps({"status": "error", "message": "No idea source found. Set IDEA_FILE, IDEA_TEXT, or create idea.txt."}))
            sys.exit(1)

        if not idea_content:
            print(json.dumps({"status": "error", "message": "Idea content is empty."}))
            sys.exit(1)

        log(f"  Mode: initial analysis")
        log(f"  Sending to {MODEL} (analysis)...")
        save_progress(1, "running")
        content = run_ollama(INITIAL_PROMPT, f"## Idea to Analyze\n\n{idea_content}", num_predict=8192)

    if content.startswith("ERROR"):
        save_progress(1 if not refine_mode else 2, "failed")
        print(json.dumps({"status": "error", "message": content}))
        sys.exit(1)

    log(f"  Response received: {len(content)} chars")

    output_path = os.path.join(workdir, "idea.md")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    # Extract hyper-critical questions (section 5)
    questions = []
    q_match = re.search(
        r"## 5\.\s*Preguntas Hiper-Cr[ií]ticas.*?(?=## 6\.|\Z)",
        content, re.DOTALL | re.IGNORECASE)
    if q_match:
        q_text = q_match.group(0)
        questions = [q.strip() for q in re.findall(
            r"\d+\.\s*\*\*.*?\*\*[\s\S]*?(?=\d+\.\s*\*\*|\Z)", q_text)
            if q.strip()]

    # Counts
    sec2 = content.split("## 2.")[1].split("## 3.")[0] if "## 2." in content and "## 3." in content else ""
    ambiguities = len(re.findall(r"^\d+\.\s", sec2))

    sec4 = content.split("## 4.")[1].split("## 5.")[0] if "## 4." in content and "## 5." in content else ""
    missing = len(re.findall(r"^- ", sec4))

    result = {
        "status": "ok",
        "mode": "refine" if refine_mode else "initial",
        "output_file": "idea.md",
        "chars": len(content),
        "ambiguities": max(0, ambiguities),
        "missing_pieces": max(0, missing),
        "questions_count": len(questions),
        "questions": questions,
    }
    save_progress(2 if refine_mode else 1, "done")
    log(f"  idea.md saved ({len(content)} chars, {len(questions)} questions)")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
