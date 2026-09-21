"""Calidad Ren'Py: glosario por juego, guía de estilo en los prompts y corrección automática post-QA."""
import json
import sys
import urllib.parse
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "tl"))

import game_glossary  # noqa: E402
import qa_renpy  # noqa: E402
import style_es  # noqa: E402
import translate  # noqa: E402


SCRIPT = '''
define e = Character("Eris", color="#c8ffc8")
define a = Character(_("Alya"), what_prefix='"')
define m = Character("Mom")
define u = Character("???")
define n = Character(None, kind=nvl)
define mc = Character("[mc_name]")
define e2 = Character('Eris')
label start:
    e "Hi"
'''


def _juego(tmp_path):
    game = tmp_path / "Juego" / "game"
    (game / "tl" / "spanish").mkdir(parents=True)
    (game / "script.rpy").write_text(SCRIPT, encoding="utf-8")
    (game / "tl" / "spanish" / "script.rpy").write_text('define zz = Character("NoCuenta")', encoding="utf-8")
    return game


def test_glosario_del_juego_solo_nombres_reales(tmp_path):
    game = _juego(tmp_path)
    assert dict(game_glossary.extraer_nombres(game)) == {"Eris": 2, "Alya": 1}
    out = tmp_path / "Juego" / "tl-es-glossary.json"
    data = game_glossary.generar(game, out)
    assert data["characters"]["Eris"] == {"source": "Eris", "target": "Eris", "count": 2}
    assert json.loads(out.read_text(encoding="utf-8"))["_meta"]["auto"] is True


def test_translate_usa_el_glosario_del_juego(tmp_path, monkeypatch):
    game = _juego(tmp_path)
    out = tmp_path / "Juego" / "tl-es-glossary.json"
    game_glossary.generar(game, out)
    monkeypatch.delenv("TL_GLOSSARY", raising=False)
    assert translate.glossary_path() == translate.GLOSSARY_FILE
    monkeypatch.setenv("TL_GLOSSARY", str(out))
    assert translate.load_glossary() == {"Eris": "Eris", "Alya": "Alya"}
    protegido, targets = translate.protect_glossary("Alya and Eris walk", translate.load_glossary())
    assert protegido == "ZG000Z and ZG001Z walk" and translate.restore_glossary("ZG000Z y ZG001Z caminan", targets) == "Alya y Eris caminan"
    monkeypatch.setenv("TL_GLOSSARY", str(tmp_path / "no-existe.json"))
    assert translate.load_glossary() == {}


def test_estilo_en_los_prompts_y_deepl_informal(monkeypatch):
    for p in (translate.GEMINI_SYSTEM_PROMPT, translate.GEMINI_BATCH_SYSTEM_PROMPT):
        assert style_es.REGLAS_ESTILO in p and "Tuteo" in p and "ZT000Z" in p
    visto = {}

    class R:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return b'{"translations":[{"text":"Hola"}]}'
    monkeypatch.setattr(translate.urllib.request, "urlopen", lambda req, timeout=0: visto.update(body=req.data) or R())
    assert translate.deepl_translate("Hello", {}, "k:fx") == "Hola"
    assert dict(urllib.parse.parse_qsl(visto["body"].decode()))["formality"] == "prefer_less"


RPY = '''# game/script.rpy:10
translate spanish start_1:

    # e "The adventurer smiled."
    old "The adventurer smiled."
    new "La aventurero sonrió."

    # e "It makes sense, {i}Eris{/i}."
    old "It makes sense, {i}Eris{/i}."
    new "Hace sentido, {i}Eris{/i}."

    # e "Long line with tag"
    old "Long line with tag [name]"
    new "Línea larga con tag [name]"
'''


def test_parse_y_correcciones_seguras(tmp_path):
    rpy = tmp_path / "script.rpy"
    rpy.write_text(RPY, encoding="utf-8")
    pairs = qa_renpy.parse_rpy(rpy)
    assert [p["target"] for p in pairs][:2] == ["La aventurero sonrió.", "Hace sentido, {i}Eris{/i}."]
    issues = [
        '[1] GÉNERO: "La aventurero" → "El aventurero"',
        "[2] CALCO: Hace sentido -> Tiene sentido",
        "[2] NOMBRE: {i}Eris{/i} → Eris",            # rompe tags → se descarta
        '[3] LITERAL: "[name]" → "[nombre]"',          # toca variable → se descarta
        "[9] CALCO: x → y",                           # índice fuera de rango
        "esto no es un issue",
        "[1] TUTEO: no está → no está",               # malo == bueno
        "[1] LITERAL: 'sonrió' → 'son-rió'",           # cosmético (guiones) → se descarta
    ]
    props = qa_renpy.proponer_correcciones(pairs, issues)
    assert [(p["n"], p["nuevo"]) for p in props] == [(1, "El aventurero sonrió."), (2, "Tiene sentido, {i}Eris{/i}.")]
    assert qa_renpy.aplicar_correcciones(rpy, props) == 2
    texto = rpy.read_text(encoding="utf-8")
    assert 'new "El aventurero sonrió."' in texto and 'new "Tiene sentido, {i}Eris{/i}."' in texto and 'new "Línea larga con tag [name]"' in texto
    assert 'old "The adventurer smiled."' in texto
    assert all(p["aplicada"] for p in props)


def test_qa_file_con_fix_y_reporte(tmp_path, monkeypatch):
    rpy = tmp_path / "script.rpy"
    rpy.write_text(RPY, encoding="utf-8")
    monkeypatch.setattr(qa_renpy, "_qa_dispatch", lambda pairs, i: ['[1] GÉNERO: "La aventurero" → "El aventurero"', "[2] LITERAL: algo raro → mejor"])
    r = qa_renpy.qa_file(rpy, fix=False)
    assert r["fixed"] == 0 and len(r["fixes"]) == 1 and 'new "La aventurero sonrió."' in rpy.read_text(encoding="utf-8")
    r = qa_renpy.qa_file(rpy, fix=True)
    assert r["fixed"] == 1 and r["fixes"][0]["aplicada"] is True and 'new "El aventurero sonrió."' in rpy.read_text(encoding="utf-8")
    informe = qa_renpy.render_report([r])
    assert "Issues: 2  |  Corregidos automáticamente: 1" in informe and "El aventurero\"  ✔ corregido" in informe
    assert "- [2] LITERAL: algo raro → mejor\n" in informe


def test_groq_retry_after_y_cupo_por_minuto(monkeypatch):
    assert qa_renpy._retry_after("7", "", 15.0) == 7.0
    assert qa_renpy._retry_after(None, "Rate limit reached... Please try again in 12.5s. Visit...", 15.0) == 13.5
    assert qa_renpy._retry_after(None, "Please try again in 1m2.3s", 15.0) == 61.0 or qa_renpy._retry_after(None, "try again in 1.5m", 15.0) == 91.0
    assert qa_renpy._retry_after(None, "", 15.0) == 15.0
    dormido = []
    monkeypatch.setattr(qa_renpy.time, "sleep", lambda s: dormido.append(s))
    qa_renpy._groq_ventana.clear()
    qa_renpy._groq_esperar_cupo(4000); qa_renpy._groq_esperar_cupo(2500)
    assert dormido == []
    reloj = [qa_renpy._groq_ventana[0][0]]
    monkeypatch.setattr(qa_renpy.time, "time", lambda: reloj[0] + (61 if dormido else 1))
    qa_renpy._groq_esperar_cupo(2000)          # 6500 + 2000 > 7000 → duerme hasta que expire la ventana
    assert len(dormido) == 1 and 58 < dormido[0] <= 60 and len(qa_renpy._groq_ventana) == 1
    qa_renpy._groq_ventana.clear()


def test_normalizar_saltos_quita_el_punto_que_mete_deepl():
    import lib_rpy
    f = lib_rpy.normalizar_saltos
    assert f("Contacting App Store\\nPlease Wait...", "Contactar con App Store\\n. Por favor, espera...") == "Contactar con App Store\\nPor favor, espera..."
    assert f("\\nMade with Ren'Py", "\\n. Creado con Ren'Py") == "\\nCreado con Ren'Py"
    assert f("A: x.\\nB: y\\n\\nC: z", "A: x.\\n B: y\\n\\n. C: z") == "A: x.\\nB: y\\n\\nC: z"
    assert f("Line one \\n two", "Línea uno \\n dos") == "Línea uno \\n dos"     # el source ya tenía espacios: se respetan
    assert f("sin saltos", "sin saltos. ") == "sin saltos. "


def test_groq_como_provider_de_traduccion(monkeypatch, tmp_path):
    visto = {}

    class R:
        def __init__(self, body): self.body = body
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return self.body
    def urlopen(req, timeout=0):
        visto["url"] = req.full_url; visto["body"] = json.loads(req.data)
        return R(json.dumps({"choices": [{"message": {"content": "```json\n{\"items\": [\"Hola ZT000Z\", \"Adiós\"]}\n```"}}], "usage": {"prompt_tokens": 50, "completion_tokens": 10}}).encode())
    monkeypatch.setattr(translate.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(translate, "_BACKEND", "groq")
    monkeypatch.setattr(translate, "GROQ_USAGE_FILE", tmp_path / "groq_usage.json")
    monkeypatch.setattr(translate.time, "sleep", lambda s: None)
    translate._groq_ventana.clear()
    cache = {}
    out = translate.openai_translate_batch(["Hello ZT000Z", "Bye"], cache, "gsk_x", "openai/gpt-oss-120b")
    assert out == ["Hola ZT000Z", "Adiós"] and visto["url"] == translate.GROQ_API
    assert "response_format" not in visto["body"] and '{"items": [...]}' in visto["body"]["messages"][0]["content"]
    assert cache["openai|openai/gpt-oss-120b|Bye"] == "Adiós"
    uso = json.loads((tmp_path / "groq_usage.json").read_text())
    assert uso["tokens"] == 60 and uso["requests"] == 1
    # cupo diario reservado agotado → GroqExhausted sin llamar a la API
    monkeypatch.setattr(translate, "GROQ_TOKENS_POR_DIA", 100)
    visto.clear()
    with pytest.raises(translate.GroqExhausted):
        translate.openai_translate_batch(["Something new"], {}, "gsk_x", "openai/gpt-oss-120b")
    assert not visto
    monkeypatch.setattr(translate, "GROQ_TOKENS_POR_DIA", 150000)
    # 429 diario → GroqExhausted (el caller imprime [ABORT] y el pipeline pasa a OpenAI)
    import urllib.error, io, email
    def urlopen429(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", email.message_from_string("Retry-After: 3"), io.BytesIO(b'{"error":{"message":"Rate limit reached ... requests per day (RPD): Limit 1000"}}'))
    monkeypatch.setattr(translate.urllib.request, "urlopen", urlopen429)
    with pytest.raises(translate.GroqExhausted):
        translate.openai_translate_batch(["Other"], {}, "gsk_x", "openai/gpt-oss-120b")


def test_cadena_de_providers(monkeypatch):
    import pipeline_server as ps
    for k, v in {"DEEPL_API_KEY": "d", "GROQ_API_KEY": "g", "OPENAI_API_KEY": "o"}.items():
        monkeypatch.setenv(k, v)
    assert ps._cadena_providers("deepl") == ["deepl", "groq", "openai"]
    assert ps._cadena_providers("openai") == ["groq", "openai"]      # DeepL sin cupo → Groq gratis antes que OpenAI
    monkeypatch.delenv("GROQ_API_KEY")
    assert ps._cadena_providers("deepl") == ["deepl", "openai"] and ps._cadena_providers("groq") == ["openai"]
    monkeypatch.delenv("OPENAI_API_KEY"); monkeypatch.delenv("DEEPL_API_KEY")
    assert ps._cadena_providers("deepl") == ["deepl"]


def test_qa_se_corta_limpio_si_groq_agota_el_cupo_diario(tmp_path, monkeypatch):
    for n in ("a", "b", "c"):
        (tmp_path / f"{n}.rpy").write_text(RPY, encoding="utf-8")
    llamadas = []
    def dispatch(pairs, i):
        llamadas.append(i)
        if len(llamadas) >= 2:
            return ["[ERROR] Groq HTTP 429: rate limit reached ... tokens per day (TPD): Limit 200000"]
        return ['[1] GÉNERO: "La aventurero" → "El aventurero"']
    monkeypatch.setattr(qa_renpy, "_qa_dispatch", dispatch)
    monkeypatch.setattr(qa_renpy, "BATCH_SIZE", 2)
    res = qa_renpy.qa_directory(tmp_path, fix=True)
    assert len(res) == 1 and res[0]["fixed"] == 1 and res[0]["parcial"] == "cupo diario de Groq agotado en el lote 2/2; 2 archivo(s) sin revisar"
    assert not any(i.startswith("[ERROR]") for i in res[0]["issues"]) and len(llamadas) == 2
    with pytest.raises(qa_renpy.CupoAgotado):
        qa_renpy.qa_file(tmp_path / "c.rpy")


def test_qa_rota_modelos_groq_y_cae_a_openai(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g"); monkeypatch.setenv("OPENAI_API_KEY", "o")
    monkeypatch.setattr(qa_renpy, "GROQ_MODELS", ["m1", "m2"]); monkeypatch.setattr(qa_renpy, "GROQ_MODEL", "m1")
    monkeypatch.setattr(qa_renpy, "OPENAI_QA_FALLBACK", True)
    qa_renpy._groq_agotados.clear(); qa_renpy._groq_ventana.clear(); qa_renpy._openai_tokens.update({"in": 0, "out": 0})
    monkeypatch.setattr(qa_renpy.time, "sleep", lambda s: None)
    llamadas = []
    def chat(url, key, model, contenido, ua):
        llamadas.append((url.split("/")[2], model))
        if model == "m1": return None, "per day", {}
        if model == "m2": return ["[1] CALCO: a → b"], "", {}
        return ["[2] GÉNERO: c → d"], "", {"prompt_tokens": 1000, "completion_tokens": 100}
    monkeypatch.setattr(qa_renpy, "_chat", chat)
    pares = [{"location": "x", "source": "Hello there friend", "target": "Hola ahí amigo"}]
    assert qa_renpy.groq_qa(pares, 0) == ["[1] CALCO: a → b"] and llamadas == [("api.groq.com", "m1"), ("api.groq.com", "m2")]
    assert qa_renpy.groq_qa(pares, 1) == ["[1] CALCO: a → b"] and llamadas[-1] == ("api.groq.com", "m2")   # m1 ya no se intenta
    qa_renpy._groq_agotados.add("m2")
    assert qa_renpy.groq_qa(pares, 2) == ["[2] GÉNERO: c → d"] and llamadas[-1] == ("api.openai.com", "gpt-4.1-nano")
    assert qa_renpy.gasto_openai_qa() == {"in": 1000, "out": 100, "usd": 0.0001}
    monkeypatch.setattr(qa_renpy, "OPENAI_QA_FALLBACK", False)
    assert qa_renpy.groq_qa(pares, 3)[0].startswith("[ERROR] Groq HTTP 429: cupo diario agotado")
    assert "(x)" not in qa_renpy._build_user_content(pares, 0)      # sin ubicación: menos tokens por par
    qa_renpy._groq_agotados.clear()
