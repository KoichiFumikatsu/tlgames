"""Cobertura de motores: Unity genérico vía XUnity.AutoTranslator y RPG Maker (terms de System.json)."""
import io
import json
import struct
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "tl"))

import unity_xunity  # noqa: E402
import translate_rpgmaker  # noqa: E402


def _exe(machine: int) -> bytes:
    """Cabecera PE mínima: MZ + e_lfanew → 'PE\\0\\0' + Machine."""
    head = bytearray(b"MZ" + b"\0" * 0x3E)
    struct.pack_into("<I", head, 0x3C, 0x40)
    return bytes(head) + b"PE\0\0" + struct.pack("<H", machine) + b"\0" * 20


def _juego_unity(tmp_path, machine=0x8664, il2cpp=False):
    game = tmp_path / "Juego"
    data = game / "Juego_Data"
    (data / "Managed").mkdir(parents=True)
    (data / "Managed" / "Assembly-CSharp.dll").write_bytes(b"MZ")
    (game / "Juego.exe").write_bytes(_exe(machine))
    (game / "UnityPlayer.dll").write_bytes(b"MZ")
    if il2cpp:
        (game / "GameAssembly.dll").write_bytes(b"MZ")
    # level0 con strings ASCII y UTF-16 entre basura binaria
    textos = [b"Press any key to start.", b"Do you want to save your progress?", b"unity_builtin_extra", b"guid:abc"]
    blob = b"\0\x01\x02".join(textos) + b"\0\0" + "New Game".encode("utf-16le") + b"\0\0" + "Are you sure you want to quit?".encode("utf-16le") + b"\0\0"
    (data / "level0").write_bytes(blob)
    (data / "resources.assets").write_bytes(b"\0Continue from last save.\0")
    return game


def _zip(entries: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in entries.items():
            z.writestr(name, content)
    return buf.getvalue()


def _cache(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / f"BepInEx_win_x64_{unity_xunity.BEPINEX_VERSION}.zip").write_bytes(_zip({
        "BepInEx/core/BepInEx.dll": "dll", "doorstop_config.ini": "[General]\nenabled=true\n", "winhttp.dll": "dll",
        "changelog.txt": "no se copia", "../evil.txt": "zip-slip",
    }))
    (cache / f"XUnity.AutoTranslator-BepInEx-{unity_xunity.XUNITY_VERSION}.zip").write_bytes(_zip({
        "BepInEx/plugins/XUnity.AutoTranslator/XUnity.AutoTranslator.Plugin.BepInEx.dll": "dll",
        "BepInEx/core/XUnity.Common.dll": "dll",
    }))
    return cache


def test_detectar_build_mono_x64_x86_e_il2cpp(tmp_path):
    b = unity_xunity.detectar_build(_juego_unity(tmp_path))
    assert (b["runtime"], b["arch"], b["nombre"]) == ("mono", "x64", "Juego") and b["data_dir"].endswith("Juego_Data")
    assert unity_xunity.detectar_build(_juego_unity(tmp_path / "b", machine=0x14C))["arch"] == "x86"
    assert unity_xunity.detectar_build(_juego_unity(tmp_path / "c", il2cpp=True))["runtime"] == "il2cpp"
    assert "error" in unity_xunity.detectar_build(tmp_path / "nada")


def test_extraer_estaticos_filtra_ruido(tmp_path):
    game = _juego_unity(tmp_path)
    textos = unity_xunity.extraer_estaticos(game / "Juego_Data")
    assert textos == ["Press any key to start.", "Do you want to save your progress?", "Are you sure you want to quit?", "Continue from last save."]


def test_run_instala_configura_y_pretraduce_sin_red(tmp_path, monkeypatch):
    game = _juego_unity(tmp_path)
    cache = _cache(tmp_path)
    monkeypatch.setattr(unity_xunity.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no debe descargar: está en cache")))
    lineas = []
    traductor = lambda textos: [t.replace("Press any key to start.", "Pulsa cualquier tecla para empezar.").replace("Continue from last save.", "Continue from last save.")
                                if t in ("Press any key to start.", "Continue from last save.") else "ES: " + t for t in textos]
    res = unity_xunity.run(game, provider="auto", lang="es", cache_dir=cache, endpoint="GoogleTranslateV2", traductor=traductor, log=lineas.append)
    assert (game / "winhttp.dll").exists() and (game / "BepInEx" / "plugins" / "XUnity.AutoTranslator" / "XUnity.AutoTranslator.Plugin.BepInEx.dll").exists()
    assert not (game / "changelog.txt").exists() and not (tmp_path / "evil.txt").exists()
    ini = (game / "BepInEx" / "config" / "AutoTranslatorConfig.ini").read_text(encoding="utf-8")
    assert "Language=es\nFromLanguage=en" in ini and "Endpoint=GoogleTranslateV2" in ini and "EnableTextMeshPro=True" in ini
    estatico = (game / "BepInEx" / "Translation" / "es" / "Text" / "_static.txt").read_text(encoding="utf-8")
    assert "Press any key to start.=Pulsa cualquier tecla para empezar." in estatico
    assert "Are you sure you want to quit?=ES: Are you sure you want to quit?" in estatico
    assert "Continue from last save." not in estatico        # sin cambio → no se exporta
    assert res["estaticos"] == {"estaticos": 4, "traducidos": 3, "exportados": 3, "archivo": str(game / "BepInEx" / "Translation" / "es" / "Text" / "_static.txt")}
    assert res["instalacion"]["bepinex"].startswith("BepInEx_win_x64") and lineas[0] == "[XUNITY] build=mono arch=x64 data=Juego_Data"
    assert lineas[-1] == "[XUNITY] estaticos=4 traducidos=3 exportados=3 archivo=BepInEx/Translation/es/Text/_static.txt".replace("/", str(Path("a/b"))[1])


def test_il2cpp_y_descarga_faltante(tmp_path, monkeypatch):
    game = _juego_unity(tmp_path, il2cpp=True)
    try:
        unity_xunity.run(game, cache_dir=tmp_path / "cache", traductor=lambda t: t)
        assert False
    except RuntimeError as e:
        assert "IL2CPP" in str(e) or "il2cpp" in str(e)
    # cache vacía → descarga (falsa) del zip
    game2 = _juego_unity(tmp_path / "dos")
    vacio = tmp_path / "vacio"
    pedidos = []

    class R:
        def __init__(self, url): self.url = url; self.leido = False
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self, n=-1):
            if self.leido: return b""
            self.leido = True
            return _zip({"BepInEx/core/x.dll": "dll"}) if "BepInEx_win" in self.url else _zip({"BepInEx/plugins/XUnity.AutoTranslator/p.dll": "dll"})
    monkeypatch.setattr(unity_xunity.urllib.request, "urlopen", lambda req, timeout=0: pedidos.append(req.full_url) or R(req.full_url))
    res = unity_xunity.run(game2, cache_dir=vacio, pretranslate=False, log=lambda s: None)
    assert [u.rsplit("/", 1)[-1] for u in pedidos] == [f"BepInEx_win_x64_{unity_xunity.BEPINEX_VERSION}.zip", f"XUnity.AutoTranslator-BepInEx-{unity_xunity.XUNITY_VERSION}.zip"]
    assert (vacio / f"BepInEx_win_x64_{unity_xunity.BEPINEX_VERSION}.zip").exists() and "estaticos" not in res
    assert unity_xunity.main([str(game2), "--dry", "--cache-dir", str(vacio)]) == 0


def test_rpgmaker_extrae_terms_de_system(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "System.json").write_text(json.dumps({
        "gameTitle": "My Game", "terms": {"basic": ["Level", "Lv", "HP"], "commands": ["Fight", None, "Escape"],
                                          "params": ["Max HP", "Attack"], "messages": {"actionFailure": "There was no effect on %1!", "alwaysDash": "Always Dash", "bgmVolume": "BGM"}},
    }), encoding="utf-8")
    (data / "Actors.json").write_text(json.dumps([None, {"id": 1, "name": "Harold", "nickname": "The Hero", "profile": "A brave young man."}]), encoding="utf-8")
    ext = translate_rpgmaker.extract_strings(data)
    rutas = {tuple(e["path"]): e["text"] for e in ext["System.json"]}
    assert rutas[("gameTitle",)] == "My Game" and rutas[("terms", "basic", 0)] == "Level" and rutas[("terms", "commands", 2)] == "Escape"
    assert rutas[("terms", "params", 0)] == "Max HP" and rutas[("terms", "messages", "actionFailure")] == "There was no effect on %1!"
    assert ("terms", "commands", 1) not in rutas
    assert {e["text"] for e in ext["Actors.json"]} >= {"Harold", "The Hero", "A brave young man."}
