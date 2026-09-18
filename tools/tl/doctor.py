"""
Doctor del pipeline: cuando una falla no está en el catálogo, Groq (gratis, gpt-oss-120b) lee el fragmento del log
y el catálogo y devuelve un diagnóstico ESTRUCTURADO en español: causa probable, si coincide con una receta
existente, qué hacer, y una receta propuesta (firma regex + textos) para aprobar desde el dashboard.

Límite duro: el doctor no toca archivos. Solo si señala una receta existente cuya acción es segura, el pipeline la
aplica como si la hubiera encontrado el catálogo.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

GROQ_API = "https://api.groq.com/openai/v1/chat/completions"
MODEL = os.environ.get("GROQ_MODEL_DOCTOR", "openai/gpt-oss-120b")

SYSTEM = (
    "Eres el doctor de un pipeline de traducción de videojuegos (Ren'Py, Unity con XUnity.AutoTranslator, RPG Maker MV/MZ) "
    "que corre en un servidor Linux (Python 3.12, venv, DeepL/Groq/OpenAI como traductores, SDK de Ren'Py, unrpyc, BepInEx). "
    "Te llega el error y las últimas líneas del log de un trabajo, más el catálogo de recetas conocidas. "
    "Responde SOLO un objeto JSON con estas claves:\n"
    '{"causa": "explicación breve en español de qué falló y por qué", '
    '"receta_id": "id del catálogo si el error coincide claramente con una receta, si no null", '
    '"que_hacer": "pasos concretos y cortos para el operador, en español", '
    '"confianza": 0.0-1.0, '
    '"receta_propuesta": {"id": "snake_case", "patron": "regex corta que identifique este error en el log", "causa": "...", "que_hacer": "..."} o null}\n'
    "No propongas comandos destructivos. No inventes rutas ni versiones. Si no sabes, dilo en 'causa' con confianza baja."
)


def _parsear(content: str) -> dict:
    c = content.strip()
    c = re.sub(r"^```(?:json)?\s*|\s*```$", "", c)
    try:
        return json.loads(c)
    except json.JSONDecodeError:
        i, j = c.find("{"), c.rfind("}")
        if i < 0 or j < i:
            raise
        return json.loads(c[i:j + 1])


def diagnosticar(error: str, log: str, catalogo: list[dict], engine: str = "", api_key: str | None = None, fetch=None) -> dict:
    """Devuelve {causa, receta_id, que_hacer, confianza, receta_propuesta, modelo} o {"error": ...} si Groq no está."""
    key = api_key or os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        return {"error": "sin GROQ_API_KEY"}
    resumen_catalogo = "\n".join(f"- {r['id']}: {r['causa']}" for r in catalogo)
    user = (f"Motor: {engine or 'desconocido'}\nError: {error[:500]}\n\nÚltimas líneas del log:\n{log[-3500:]}\n\n"
            f"Catálogo de recetas conocidas:\n{resumen_catalogo}")
    body = json.dumps({"model": MODEL, "temperature": 0.1, "max_tokens": 800,
                       "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]}).encode()
    try:
        if fetch:
            content = fetch(body)
        else:
            req = urllib.request.Request(GROQ_API, data=body, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                                                       "User-Agent": "tlgames-doctor/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                content = json.loads(r.read())["choices"][0]["message"]["content"]
        d = _parsear(content)
    except urllib.error.HTTPError as e:
        return {"error": f"Groq HTTP {e.code}"}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e)[:120]}"}
    ids = {r["id"] for r in catalogo}
    receta_id = d.get("receta_id") if d.get("receta_id") in ids else None
    prop = d.get("receta_propuesta") if isinstance(d.get("receta_propuesta"), dict) else None
    if prop:
        try:
            re.compile(str(prop.get("patron", "")))
        except re.error:
            prop = None
    return {"causa": str(d.get("causa", ""))[:600], "receta_id": receta_id, "que_hacer": str(d.get("que_hacer", ""))[:800],
            "confianza": max(0.0, min(1.0, float(d.get("confianza") or 0))), "receta_propuesta": prop, "modelo": MODEL}
