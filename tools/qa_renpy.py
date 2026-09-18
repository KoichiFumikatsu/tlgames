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
BATCH_SIZE = 20  # pares por llamada al LLM (Groq free: 8k tokens/min → lotes chicos)
BACKEND = "auto"  # 'auto' | 'groq' | 'ollama'
GROQ_RATE_LIMIT_DELAY = 2.0  # segundos entre requests para respetar 30/min
GROQ_TOKENS_POR_MINUTO = 7000  # margen bajo el límite real (8000 TPM en openai/gpt-oss-20b, 2026-09-17)
_groq_ventana: list = []   # (timestamp, tokens estimados) de los últimos 60 s


def _tokens_estimados(texto: str) -> int:
    return len(texto) // 3 + 400   # ~3 chars/token en ES/EN + system prompt + respuesta


def _groq_esperar_cupo(tokens: int):
    """Duerme lo justo para no pasar GROQ_TOKENS_POR_MINUTO en la ventana móvil de 60 s."""
    while True:
        ahora = time.time()
        _groq_ventana[:] = [(t, n) for t, n in _groq_ventana if ahora - t < 60]
        usados = sum(n for _, n in _groq_ventana)
        if usados + tokens <= GROQ_TOKENS_POR_MINUTO or not _groq_ventana:
            _groq_ventana.append((ahora, tokens))
            return
        time.sleep(max(0.5, 60 - (ahora - _groq_ventana[0][0]) + 0.2))

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

    contenido = _build_user_content(pairs, batch_idx)
    _groq_esperar_cupo(_tokens_estimados(SYSTEM_PROMPT + contenido))
    payload = {
        "model": GROQ_MODEL,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": contenido},
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
    # 429 (tokens/min): respetar Retry-After y reintentar hasta 4 veces
    for intento in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read())
                text = result["choices"][0]["message"]["content"].strip()
                if text == "OK":
                    return []
                return [line for line in text.splitlines() if line.strip() and line.strip() != "OK"]
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:300] if e.fp else ""
            if e.code == 429 and intento < 4:
                espera = _retry_after(e.headers.get("Retry-After"), body, default=15.0 * (intento + 1))
                print(f"  Groq 429 — espero {espera:.0f}s", flush=True)
                time.sleep(espera)
                continue
            return [f"[ERROR] Groq HTTP {e.code}: {body}"]
        except urllib.error.URLError as e:
            return [f"[ERROR] Groq no disponible: {e}"]
        except Exception as e:
            return [f"[ERROR] Llamada Groq fallida: {e}"]
    return ["[ERROR] Groq 429 persistente"]


_RETRY_MSG_RE = re.compile(r"try again in ([\d.]+)(m|s|ms)")


def _retry_after(header: str | None, body: str, default: float) -> float:
    """Segundos a esperar según Retry-After o el texto 'Please try again in 12.3s' de Groq."""
    if header:
        try:
            return min(120.0, max(1.0, float(header)))
        except ValueError:
            pass
    m = _RETRY_MSG_RE.search(body or "")
    if m:
        n, u = float(m.group(1)), m.group(2)
        seg = n * 60 if u == "m" else (n / 1000 if u == "ms" else n)
        return min(120.0, max(1.0, seg + 1))
    return default


def _qa_dispatch(pairs: list[dict], batch_idx: int) -> list[str]:
    """Selecciona backend segun BACKEND. 'auto' = groq si hay key, sino ollama."""
    backend = BACKEND
    if backend == "auto":
        backend = "groq" if os.environ.get("GROQ_API_KEY", "").strip() else "ollama"
    if backend == "groq":
        return groq_qa(pairs, batch_idx)
    return ollama_qa(pairs, batch_idx)


_ISSUE_RE = re.compile(r"^\s*\[(\d+)\]\s*([A-ZÁÉÍÓÚÑ]+)\s*:\s*(.+?)\s*(?:→|->)\s*(.+?)\s*$")
_TAG_RE = re.compile(r"\{[^{}]+\}|\[[^\[\]]+\]|\|[A-Za-z0-9_]+\|")


def _limpiar_fragmento(s: str) -> str:
    s = s.strip()
    while len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'`«»“”":
        s = s[1:-1].strip()
    return s


def parse_issue(line: str) -> dict | None:
    """'[N] TIPO: malo → bueno' → {"n","tipo","malo","bueno"}; None si no tiene ese formato."""
    m = _ISSUE_RE.match(line)
    if not m:
        return None
    malo, bueno = _limpiar_fragmento(m.group(3)), _limpiar_fragmento(m.group(4))
    if not malo or not bueno or malo == bueno:
        return None
    return {"n": int(m.group(1)), "tipo": m.group(2), "malo": malo, "bueno": bueno}


def proponer_correcciones(pairs: list[dict], issues: list[str]) -> list[dict]:
    """Convierte los issues del LLM en reemplazos seguros sobre el target del par N:
    el fragmento malo aparece exactamente una vez, y el resultado conserva tags/variables y \\n."""
    out = []
    for raw in issues:
        it = parse_issue(raw)
        if not it or not 1 <= it["n"] <= len(pairs):
            continue
        p = pairs[it["n"] - 1]
        target = p["target"]
        malo, bueno = it["malo"], it["bueno"]
        if target.count(malo) != 1:
            continue
        if re.sub(r"[\s\-]", "", malo.lower()) == re.sub(r"[\s\-]", "", bueno.lower()):
            continue   # cambio cosmético (guiones/espacios): el modelo chico se inventa "in-jugable"
        if '"' in bueno.replace('\\"', ""):
            continue   # comilla sin escapar rompería el .rpy
        nuevo = target.replace(malo, bueno)
        if nuevo == target or _TAG_RE.findall(nuevo) != _TAG_RE.findall(target) or nuevo.count("\\n") != target.count("\\n"):
            continue
        out.append({"n": it["n"], "tipo": it["tipo"], "location": p["location"], "source": p["source"],
                    "target": target, "nuevo": nuevo, "raw": raw})
    return out


def aplicar_correcciones(path: Path, propuestas: list[dict]) -> int:
    """Reescribe los `new "..."` corregidos en el .rpy. Devuelve cuántos aplicó."""
    if not propuestas:
        return 0
    content = path.read_text(encoding="utf-8-sig", errors="replace")
    aplicadas = 0
    for c in propuestas:
        bloque = re.compile(r'(old\s+"' + re.escape(c["source"]) + r'"\s*\n\s+new\s+")' + re.escape(c["target"]) + r'"')
        content, n = bloque.subn(lambda m, nuevo=c["nuevo"]: m.group(1) + nuevo + '"', content, count=1)
        aplicadas += n
        c["aplicada"] = bool(n)
    if aplicadas:
        path.write_text(content, encoding="utf-8")
    return aplicadas


def qa_file(path: Path, fix: bool = False) -> dict:
    """QA completo de un archivo .rpy. Retorna dict con resultados.
    Con fix=True aplica al archivo las sugerencias seguras del LLM (ver proponer_correcciones)."""
    pairs = parse_rpy(path)
    translated = len(pairs)
    if translated == 0:
        return {"file": str(path), "translated": 0, "issues": [], "batches": 0, "fixes": [], "fixed": 0}

    issues = []
    batches = (translated + BATCH_SIZE - 1) // BATCH_SIZE
    for i in range(batches):
        chunk = pairs[i * BATCH_SIZE : (i + 1) * BATCH_SIZE]
        print(f"  lote {i+1}/{batches} ({len(chunk)} pares)...", end=" ", flush=True)
        found = _qa_dispatch(chunk, i)
        issues.extend(found)
        print(f"{len(found)} issues")

    fixes = proponer_correcciones(pairs, issues)
    fixed = aplicar_correcciones(path, fixes) if fix else 0
    if fixes:
        print(f"  correcciones: {len(fixes)} propuestas, {fixed} aplicadas")
    return {"file": str(path), "translated": translated, "issues": issues, "batches": batches, "fixes": fixes, "fixed": fixed}


def qa_directory(directory: Path, fix: bool = False) -> list[dict]:
    """QA de todos los .rpy en un directorio."""
    results = []
    rpy_files = sorted(directory.glob("**/*.rpy"))
    for rpy in rpy_files:
        print(f"\n[{rpy.name}]")
        results.append(qa_file(rpy, fix=fix))
    return results


def render_report(results: list[dict], target_path: Path | None = None) -> str:
    """Genera reporte markdown."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    total_translated = sum(r["translated"] for r in results)
    total_issues = sum(len(r["issues"]) for r in results)
    total_fixed = sum(r.get("fixed", 0) for r in results)

    lines = [
        f"# QA Semántico — Ren'Py",
        f"Generado: {now}  |  Archivos: {len(results)}  |  Pares revisados: {total_translated}  |  Issues: {total_issues}"
        + (f"  |  Corregidos automáticamente: {total_fixed}" if total_fixed else ""),
        "",
    ]

    for r in results:
        file_issues = r["issues"]
        status = "OK" if not file_issues else f"{len(file_issues)} issues"
        lines.append(f"## {Path(r['file']).name} — {r['translated']} pares — {status}")
        if file_issues:
            lines.append("")
            corregidos = {f["raw"] for f in r.get("fixes", []) if f.get("aplicada")}
            for issue in file_issues:
                lines.append(f"- {issue}" + ("  ✔ corregido" if issue in corregidos else ""))
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
