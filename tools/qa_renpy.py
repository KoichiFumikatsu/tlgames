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
# Cada modelo de Groq tiene su propio cupo diario (200K tokens/día): se rota cuando uno se agota. gpt-oss-120b va de
# último porque lo comparten el briefing y la traducción. Env GROQ_QA_MODELS="a,b,c" para cambiar el orden.
GROQ_MODELS = [m.strip() for m in os.environ.get("GROQ_QA_MODELS", "openai/gpt-oss-20b,qwen/qwen3.8-27b,openai/gpt-oss-120b").split(",") if m.strip()]
_groq_agotados: set = set()          # modelos sin cupo diario (se limpia al cambiar el día UTC)
_groq_agotados_dia = ""
# Respaldo de pago cuando todo Groq se agota (gpt-4.1-nano: US$0,10/1M entrada, 0,40 salida → un juego grande ≈ US$0,05)
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_QA_MODEL = os.environ.get("OPENAI_QA_MODEL", "gpt-4.1-nano")
OPENAI_QA_FALLBACK = os.environ.get("QA_OPENAI_FALLBACK", "1") not in ("0", "false", "no")
_openai_tokens = {"in": 0, "out": 0}

MODEL = OLLAMA_MODEL  # backward compat con codigo antiguo
BATCH_SIZE = 30  # pares por llamada al LLM (el pacing por tokens/min ya cuida el 8k TPM de Groq)
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
    candidatos = [(m.group(1).strip(), m.group(2), m.group(3), None) for m in pattern.finditer(content)]
    # Bloques de diálogo: '# who "src"' seguido de 'who "tgt"' (con o sin atributos/sufijo)
    lineas = content.splitlines()
    for i, l in enumerate(lineas):
        s = l.strip()
        if not s.startswith("#") or '"' not in s or i + 1 >= len(lineas):
            continue
        orig = _partir(s.lstrip("#").strip())
        j = i + 1
        while j < len(lineas) and not lineas[j].strip():
            j += 1
        if j >= len(lineas) or lineas[j].strip().startswith(("#", "old ", "new ", "translate ")):
            continue
        tr = _partir(lineas[j].strip())
        if not orig or not tr:
            continue
        candidatos.append((f"{Path(path).name}:{j + 1}", orig[1], tr[1], j + 1))
    for location, source, target, linea in candidatos:
        # Saltar no traducidos (target vacío o igual al source)
        clean_src = PROTECTED_RE.sub("", source).strip()
        clean_tgt = PROTECTED_RE.sub("", target).strip()
        if not clean_tgt or clean_tgt == clean_src:
            continue
        # Saltar pares de 1-2 palabras (nombres de stats, atributos): poco contexto para QA semántico
        if len(clean_src.split()) <= 2 and len(clean_tgt.split()) <= 2:
            continue
        pairs.append({"location": location, "source": source, "target": target, **({"linea": linea} if linea else {})})
    return pairs


_DIALOGO_RE = re.compile(r'^([^"]*?)\s*"((?:[^"\\]|\\.)*)"\s*([^"]*?)\s*$')


def _partir(s: str):
    m = _DIALOGO_RE.match(s)
    return (m.group(1).strip(), m.group(2), m.group(3).strip()) if m else None


def _build_user_content(pairs: list[dict], batch_idx: int) -> str:
    lines = []
    for i, p in enumerate(pairs, 1):
        n = batch_idx * BATCH_SIZE + i
        src = p["source"].replace("\n", "\\n")
        tgt = p["target"].replace("\n", "\\n")
        lines.append(f"[{n}] EN: {src!r} | ES: {tgt!r}")
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


def _modelos_groq() -> list[str]:
    """Modelos con cupo diario disponible (el cupo se reinicia a las 00:00 UTC)."""
    global _groq_agotados_dia
    hoy = time.strftime("%Y-%m-%d", time.gmtime())
    if hoy != _groq_agotados_dia:
        _groq_agotados.clear()
        _groq_agotados_dia = hoy
    orden = [GROQ_MODEL] + [m for m in GROQ_MODELS if m != GROQ_MODEL] if GROQ_MODEL not in GROQ_MODELS else GROQ_MODELS
    return [m for m in orden if m not in _groq_agotados]


def _chat(url: str, api_key: str, model: str, contenido: str, ua: str) -> tuple[list[str] | None, str, dict]:
    """Una llamada chat/completions. Devuelve (lineas|None, error, usage). Reintenta 429 por minuto con Retry-After;
    error 'per day' = cupo diario agotado (el caller rota de modelo)."""
    payload = {"model": model, "temperature": 0.1,
               "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": contenido}]}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}", "User-Agent": ua, "Accept": "application/json"})
    for intento in range(5):
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                result = json.loads(resp.read())
                text = result["choices"][0]["message"]["content"].strip()
                usage = result.get("usage") or {}
                if text == "OK":
                    return [], "", usage
                return [line for line in text.splitlines() if line.strip() and line.strip() != "OK"], "", usage
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:300] if e.fp else ""
            if e.code == 429 and "per day" in body.lower():
                return None, "per day", {}
            if e.code == 429 and intento < 4:
                espera = _retry_after(e.headers.get("Retry-After"), body, default=15.0 * (intento + 1))
                print(f"  {model} 429 — espero {espera:.0f}s", flush=True)
                time.sleep(espera)
                continue
            return None, f"HTTP {e.code}: {body}", {}
        except urllib.error.URLError as e:
            return None, f"no disponible: {e}", {}
        except Exception as e:
            return None, f"fallo: {e}", {}
    return None, "429 persistente", {}


def groq_qa(pairs: list[dict], batch_idx: int) -> list[str]:
    """Lote de QA: modelos de Groq en rotación (cada uno con su cupo diario) y, si todos se agotan, OpenAI nano."""
    global _groq_last_call_ts
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    contenido = _build_user_content(pairs, batch_idx)
    if api_key:
        for model in _modelos_groq():
            elapsed = time.time() - _groq_last_call_ts
            if elapsed < GROQ_RATE_LIMIT_DELAY:
                time.sleep(GROQ_RATE_LIMIT_DELAY - elapsed)
            _groq_last_call_ts = time.time()
            _groq_esperar_cupo(_tokens_estimados(SYSTEM_PROMPT + contenido))
            lineas, error, _ = _chat(GROQ_URL, api_key, model, contenido, "tlgames-qa/1.0 (+https://localhost:8765/qa)")
            if lineas is not None:
                return lineas
            if error == "per day" or error == "429 persistente":
                _groq_agotados.add(model)
                print(f"  {model}: cupo diario agotado → siguiente modelo", flush=True)
                continue
            return [f"[ERROR] Groq {model} {error}"]
    key_openai = os.environ.get("OPENAI_API_KEY", "").strip()
    if OPENAI_QA_FALLBACK and key_openai:
        lineas, error, usage = _chat(OPENAI_URL, key_openai, OPENAI_QA_MODEL, contenido, "tlgames-qa/1.0")
        if lineas is not None:
            _openai_tokens["in"] += int(usage.get("prompt_tokens", 0)); _openai_tokens["out"] += int(usage.get("completion_tokens", 0))
            return lineas
        return [f"[ERROR] OpenAI {OPENAI_QA_MODEL} {error}"]
    if not api_key:
        return ["[ERROR] GROQ_API_KEY no configurada en .env"]
    return ["[ERROR] Groq HTTP 429: cupo diario agotado en todos los modelos (tokens per day) y sin respaldo OpenAI"]


def gasto_openai_qa() -> dict:
    usd = _openai_tokens["in"] / 1e6 * 0.10 + _openai_tokens["out"] / 1e6 * 0.40
    return {"in": _openai_tokens["in"], "out": _openai_tokens["out"], "usd": round(usd, 4)}


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
                    "target": target, "nuevo": nuevo, "raw": raw, **({"linea": p["linea"]} if p.get("linea") else {})})
    return out


def aplicar_correcciones(path: Path, propuestas: list[dict]) -> int:
    """Reescribe los `new "..."` corregidos en el .rpy. Devuelve cuántos aplicó."""
    if not propuestas:
        return 0
    content = path.read_text(encoding="utf-8-sig", errors="replace")
    aplicadas = 0
    lineas = None
    for c in propuestas:
        if c.get("linea"):   # diálogo: se reemplaza el texto de esa línea conservando prefijo/sufijo
            lineas = content.splitlines(keepends=True) if lineas is None else lineas
            idx = c["linea"] - 1
            p = _partir(lineas[idx].strip()) if 0 <= idx < len(lineas) else None
            n = 0
            if p and p[1] == c["target"]:
                indent = lineas[idx][: len(lineas[idx]) - len(lineas[idx].lstrip())]
                lineas[idx] = f'{indent}{p[0] + " " if p[0] else ""}"{c["nuevo"]}"{" " + p[2] if p[2] else ""}\n'
                n = 1
            content = "".join(lineas) if n else content
            aplicadas += n
            c["aplicada"] = bool(n)
            continue
        bloque = re.compile(r'(old\s+"' + re.escape(c["source"]) + r'"\s*\n\s+new\s+")' + re.escape(c["target"]) + r'"')
        content, n = bloque.subn(lambda m, nuevo=c["nuevo"]: m.group(1) + nuevo + '"', content, count=1)
        if n:
            lineas = None
        aplicadas += n
        c["aplicada"] = bool(n)
    if aplicadas:
        path.write_text(content, encoding="utf-8")
    return aplicadas


class CupoAgotado(Exception):
    """Cupo diario de Groq (200K tokens/día por modelo) agotado: el QA se corta y queda parcial, sin bloquear el paquete."""


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
        if any("per day" in f.lower() or "429 persistente" in f for f in found if f.startswith("[ERROR]")):
            issues.extend(x for x in found if not x.startswith("[ERROR]"))
            fixes = proponer_correcciones(pairs, issues)
            fixed = aplicar_correcciones(path, fixes) if fix else 0
            r = {"file": str(path), "translated": translated, "issues": issues, "batches": batches, "fixes": fixes, "fixed": fixed,
                 "parcial": f"cupo diario de Groq agotado en el lote {i + 1}/{batches}"}
            raise CupoAgotado(r)
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
    for n, rpy in enumerate(rpy_files):
        print(f"\n[{rpy.name}]")
        try:
            results.append(qa_file(rpy, fix=fix))
        except CupoAgotado as e:
            parcial = e.args[0]
            parcial["parcial"] += f"; {len(rpy_files) - n - 1} archivo(s) sin revisar"
            results.append(parcial)
            print("  " + parcial["parcial"])
            break
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
