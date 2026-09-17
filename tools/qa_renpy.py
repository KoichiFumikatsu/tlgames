#!/usr/bin/env python3
"""
QA semántico para archivos de traducción Ren'Py (.rpy).
Llama a Ollama localmente para detectar errores que el lint estructural no cubre.

Uso:
    python3 tools/qa_renpy.py game/tl/spanish/script.rpy
    python3 tools/qa_renpy.py game/tl/spanish/          # directorio completo
    python3 tools/qa_renpy.py game/tl/spanish/script.rpy --report logs/qa_report.md
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# Cargar .env si esta disponible (igual que el resto de scripts del repo)
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent / "tl"))
    from _env import load_env as _load_env
    _load_env(Path(__file__).resolve().parent.parent)
except Exception:
    pass

OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "llama3.2:3b"

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-20b"  # free tier; los llama-3.x ya no existen en la cuenta (2026-09-17)

MODEL = OLLAMA_MODEL  # backward compat con codigo antiguo
BATCH_SIZE = 40  # pares por llamada al LLM
BACKEND = "auto"  # 'auto' | 'groq' | 'ollama'
GROQ_RATE_LIMIT_DELAY = 2.0  # segundos entre requests para respetar 30/min

# Tags y variables que no se traducen — se ignoran en la evaluación de género
PROTECTED_RE = re.compile(r"\{[^{}]+\}|\[[^\[\]]+\]|\|[A-Za-z0-9_]+\|")

SYSTEM_PROMPT = """Eres un editor de traducciones EN→ES para videojuegos (español latinoamericano, tuteo).
Revisas pares source (EN) / target (ES). SOLO reporta errores REALES y CLAROS.

REGLAS ESTRICTAS:
- Palabras sueltas bien traducidas: NO las reportes (ej. "Clever" → "Astuto" es correcto).
- Nombres propios de personaje: NUNCA se traducen, reportar si aparecen traducidos.
- Si la traducción es razonable aunque no sea perfecta: NO reportar.
- Reporta SOLO si hay un error evidente que un editor humano corregiría sin dudar.

Errores a reportar:
1. GÉNERO: concordancia incorrecta (ej. "el aventurera", "ellos fue")
2. CALCO: calco del inglés antinatural (ej. "hacer sentido", "tener un buen tiempo")
3. TUTEO: mezcla de tuteo/ustedeo (ej. "¿Cómo estás? Por favor usted me acompañe")
4. NOMBRE: nombre de personaje traducido cuando debería preservarse
5. LITERAL: frase literalmente traducida que resulta incomprensible en español

Ejemplos de lo que NO debes reportar:
- "Honest" → "Honesto" — correcto, no reportar
- "Shady" → "Sombrío" — aceptable, no reportar
- "Most known for being:" → "Más conocido por ser:" — correcto, no reportar

Formato de respuesta para CADA error encontrado (exactamente así):
[N] TIPO: texto con error → sugerencia

Si no encuentras errores claros, responde SOLO: OK"""


def parse_rpy(path: Path) -> list[dict]:
    """Extrae pares old/new con su ubicación del archivo .rpy."""
    content = path.read_text(encoding="utf-8-sig", errors="replace")
    pairs = []
    # Captura bloques: # comentario \n    old "..." \n    new "..."
    pattern = re.compile(
        r'#\s*([^\n]+)\n\s+old\s+"((?:[^"\\]|\\.)*)"\s*\n\s+new\s+"((?:[^"\\]|\\.)*)"',
        re.DOTALL,
    )
    for m in pattern.finditer(content):
        location = m.group(1).strip()
        source = m.group(2)
        target = m.group(3)
        # Saltar no traducidos (target vacío o igual al source)
        clean_src = PROTECTED_RE.sub("", source).strip()
        clean_tgt = PROTECTED_RE.sub("", target).strip()
        if not clean_tgt or clean_tgt == clean_src:
            continue
        # Saltar pares de 1-2 palabras (nombres de stats, atributos): poco contexto para QA semántico
        if len(clean_src.split()) <= 2 and len(clean_tgt.split()) <= 2:
            continue
        pairs.append({"location": location, "source": source, "target": target})
    return pairs


def _build_user_content(pairs: list[dict], batch_idx: int) -> str:
    lines = []
    for i, p in enumerate(pairs, 1):
        n = batch_idx * BATCH_SIZE + i
        src = p["source"].replace("\n", "\\n")
        tgt = p["target"].replace("\n", "\\n")
        lines.append(f"[{n}] EN: {src!r} | ES: {tgt!r}  ({p['location']})")
    return "Revisa estas traducciones:\n" + "\n".join(lines)


def ollama_qa(pairs: list[dict], batch_idx: int) -> list[str]:
    """Envía un lote a Ollama local. Lento en CPU, se satura facil."""
    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_content(pairs, batch_idx)},
        ],
    }
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
            text = result["message"]["content"].strip()
            if text == "OK":
                return []
            return [line for line in text.splitlines() if line.strip() and line.strip() != "OK"]
    except urllib.error.URLError as e:
        return [f"[ERROR] Ollama no disponible: {e}"]
    except Exception as e:
        return [f"[ERROR] Llamada Ollama fallida: {e}"]


_groq_last_call_ts = 0.0


def groq_qa(pairs: list[dict], batch_idx: int) -> list[str]:
    """Envía un lote a Groq API (OpenAI-compatible). Free tier 30 req/min."""
    global _groq_last_call_ts
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        return ["[ERROR] GROQ_API_KEY no configurada en .env"]

    # Rate limit: 30 req/min = 1 cada 2s. Espera si necesario.
    elapsed = time.time() - _groq_last_call_ts
    if elapsed < GROQ_RATE_LIMIT_DELAY:
        time.sleep(GROQ_RATE_LIMIT_DELAY - elapsed)
    _groq_last_call_ts = time.time()

    payload = {
        "model": GROQ_MODEL,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_content(pairs, batch_idx)},
        ],
    }
    req = urllib.request.Request(
        GROQ_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            # Cloudflare frente a Groq bloquea User-Agent "Python-urllib/X.Y" con error 1010
            "User-Agent": "tlgames-qa/1.0 (+https://localhost:8765/qa)",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
            text = result["choices"][0]["message"]["content"].strip()
            if text == "OK":
                return []
            return [line for line in text.splitlines() if line.strip() and line.strip() != "OK"]
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300] if e.fp else ""
        if e.code == 429:
            # Rate limit hit — esperar y reintentar 1 vez
            time.sleep(5)
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    result = json.loads(resp.read())
                    text = result["choices"][0]["message"]["content"].strip()
                    return [] if text == "OK" else [
                        l for l in text.splitlines() if l.strip() and l.strip() != "OK"
                    ]
            except Exception as e2:
                return [f"[ERROR] Groq 429 reintento fallo: {e2}"]
        return [f"[ERROR] Groq HTTP {e.code}: {body}"]
    except urllib.error.URLError as e:
        return [f"[ERROR] Groq no disponible: {e}"]
    except Exception as e:
        return [f"[ERROR] Llamada Groq fallida: {e}"]


def _qa_dispatch(pairs: list[dict], batch_idx: int) -> list[str]:
    """Selecciona backend segun BACKEND. 'auto' = groq si hay key, sino ollama."""
    backend = BACKEND
    if backend == "auto":
        backend = "groq" if os.environ.get("GROQ_API_KEY", "").strip() else "ollama"
    if backend == "groq":
        return groq_qa(pairs, batch_idx)
    return ollama_qa(pairs, batch_idx)


def qa_file(path: Path) -> dict:
    """QA completo de un archivo .rpy. Retorna dict con resultados."""
    pairs = parse_rpy(path)
    translated = len(pairs)
    if translated == 0:
        return {"file": str(path), "translated": 0, "issues": [], "batches": 0}

    issues = []
    batches = (translated + BATCH_SIZE - 1) // BATCH_SIZE
    for i in range(batches):
        chunk = pairs[i * BATCH_SIZE : (i + 1) * BATCH_SIZE]
        print(f"  lote {i+1}/{batches} ({len(chunk)} pares)...", end=" ", flush=True)
        found = _qa_dispatch(chunk, i)
        issues.extend(found)
        print(f"{len(found)} issues")

    return {"file": str(path), "translated": translated, "issues": issues, "batches": batches}


def qa_directory(directory: Path) -> list[dict]:
    """QA de todos los .rpy en un directorio."""
    results = []
    rpy_files = sorted(directory.glob("**/*.rpy"))
    for rpy in rpy_files:
        print(f"\n[{rpy.name}]")
        results.append(qa_file(rpy))
    return results


def render_report(results: list[dict], target_path: Path | None = None) -> str:
    """Genera reporte markdown."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    total_translated = sum(r["translated"] for r in results)
    total_issues = sum(len(r["issues"]) for r in results)

    lines = [
        f"# QA Semántico — Ren'Py",
        f"Generado: {now}  |  Archivos: {len(results)}  |  Pares revisados: {total_translated}  |  Issues: {total_issues}",
        "",
    ]

    for r in results:
        file_issues = r["issues"]
        status = "OK" if not file_issues else f"{len(file_issues)} issues"
        lines.append(f"## {Path(r['file']).name} — {r['translated']} pares — {status}")
        if file_issues:
            lines.append("")
            for issue in file_issues:
                lines.append(f"- {issue}")
        lines.append("")

    report = "\n".join(lines)

    if target_path:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(report, encoding="utf-8")
        print(f"\nReporte guardado: {target_path}")

    return report


def main() -> int:
    global OLLAMA_MODEL, GROQ_MODEL, BACKEND  # noqa: PLW0603
    parser = argparse.ArgumentParser(description="QA semantico de traducciones Ren'Py (Groq o Ollama).")
    parser.add_argument("target", type=Path, help="Archivo .rpy o directorio con archivos .rpy")
    parser.add_argument("--report", type=Path, default=None, help="Guardar reporte en esta ruta (.md)")
    parser.add_argument("--backend", choices=["auto", "groq", "ollama"], default="auto",
                        help="Backend del LLM (default: auto = groq si hay GROQ_API_KEY, sino ollama)")
    parser.add_argument("--ollama-model", default=OLLAMA_MODEL,
                        help=f"Modelo Ollama (default: {OLLAMA_MODEL})")
    parser.add_argument("--groq-model", default=GROQ_MODEL,
                        help=f"Modelo Groq (default: {GROQ_MODEL})")
    args = parser.parse_args()
    OLLAMA_MODEL = args.ollama_model
    GROQ_MODEL = args.groq_model
    BACKEND = args.backend
    chosen = BACKEND
    if chosen == "auto":
        chosen = "groq" if os.environ.get("GROQ_API_KEY", "").strip() else "ollama"
    print(f"# Backend: {chosen} ({GROQ_MODEL if chosen=='groq' else OLLAMA_MODEL})", file=sys.stderr)

    if args.target.is_dir():
        results = qa_directory(args.target)
    elif args.target.suffix == ".rpy":
        results = [qa_file(args.target)]
    else:
        print(f"Error: {args.target} no es un .rpy ni un directorio", file=sys.stderr)
        return 1

    report = render_report(results, args.report)
    print("\n" + report)

    total_issues = sum(len(r["issues"]) for r in results)
    return 1 if total_issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
