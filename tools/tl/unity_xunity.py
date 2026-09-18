#!/usr/bin/env python3
"""
unity_xunity.py — Unity genérico de punta a punta con XUnity.AutoTranslator.

Para juegos Unity SIN sistema de traducción propio (el 95 %): instala BepInEx 5 +
XUnity.AutoTranslator dentro del juego, escribe la configuración (es ← en) y
pre-traduce los textos estáticos que se puedan sacar de los binarios (level*,
*.assets, resources) para que el jugador ya vea español sin depender de la red.
Lo que no se capturó estático lo traduce XUnity en tiempo de ejecución con el
endpoint configurado (por defecto GoogleTranslateV2, gratuito).

Uso:
  python unity_xunity.py <ruta_juego> [--provider deepl|openai|auto] [--lang es]
                         [--cache-dir DIR] [--endpoint NOMBRE] [--dry] [--no-pretranslate]

Salida en stdout (la lee el pipeline):
  [XUNITY] build=mono arch=x64 data=Game_Data
  [XUNITY] instalado bepinex=... xunity=...
  [PROGRESS] strings=120/600 pct=20
  [XUNITY] estaticos=600 traducidos=580 exportados=570 archivo=BepInEx/Translation/es/Text/_static.txt
"""
from __future__ import annotations

import argparse
import json
import os
import re
import struct
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(ROOT / "tools" / "unity"))
from _env import load_env  # noqa: E402

load_env(ROOT)

BEPINEX_VERSION = "5.4.23.3"
XUNITY_VERSION = "5.4.5"
RELEASES = {
    "bepinex_x64": f"https://github.com/BepInEx/BepInEx/releases/download/v{BEPINEX_VERSION}/BepInEx_win_x64_{BEPINEX_VERSION}.zip",
    "bepinex_x86": f"https://github.com/BepInEx/BepInEx/releases/download/v{BEPINEX_VERSION}/BepInEx_win_x86_{BEPINEX_VERSION}.zip",
    "xunity_mono": f"https://github.com/bbepis/XUnity.AutoTranslator/releases/download/v{XUNITY_VERSION}/XUnity.AutoTranslator-BepInEx-{XUNITY_VERSION}.zip",
}
CACHE_DIR_DEFAULT = Path(os.environ.get("UNITY_TL_CACHE", str(Path.home() / "apps" / "unity-tl")))
ENDPOINT_DEFAULT = "GoogleTranslateV2"
STATIC_FILE = "_static.txt"


# ── Detección del build ────────────────────────────────────────────────────────

def _pe_arch(exe: Path) -> str:
    """x64 / x86 leyendo la cabecera PE del ejecutable; 'x64' si no se puede leer."""
    try:
        with exe.open("rb") as fh:
            head = fh.read(0x40)
            if head[:2] != b"MZ":
                return "x64"
            off = struct.unpack_from("<I", head, 0x3C)[0]
            fh.seek(off)
            sig = fh.read(4)
            if sig != b"PE\0\0":
                return "x64"
            machine = struct.unpack("<H", fh.read(2))[0]
    except (OSError, struct.error):
        return "x64"
    return "x86" if machine == 0x14C else "x64"


def detectar_build(game_path: Path) -> dict:
    """{data_dir, exe, runtime: mono|il2cpp, arch: x64|x86} o {'error': ...}."""
    game_path = Path(game_path)
    datas = sorted(p for p in game_path.glob("*_Data") if p.is_dir())
    if not datas:
        return {"error": "sin carpeta *_Data"}
    data_dir = datas[0]
    nombre = data_dir.name[: -len("_Data")]
    exe = game_path / f"{nombre}.exe"
    if not exe.exists():
        exes = sorted(p for p in game_path.glob("*.exe") if p.name.lower() not in ("unitycrashhandler64.exe", "unitycrashhandler32.exe"))
        exe = exes[0] if exes else None
    il2cpp = (game_path / "GameAssembly.dll").exists() or (data_dir / "il2cpp_data").is_dir()
    mono = (data_dir / "Managed").is_dir()
    runtime = "il2cpp" if il2cpp else ("mono" if mono else "desconocido")
    arch = _pe_arch(exe) if exe else ("x64" if (game_path / "UnityPlayer.dll").exists() else "x64")
    return {"data_dir": str(data_dir), "exe": str(exe) if exe else "", "runtime": runtime, "arch": arch, "nombre": nombre}


# ── Descarga e instalación ─────────────────────────────────────────────────────

def descargar(url: str, destino: Path, log=print) -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists() and destino.stat().st_size > 0:
        return destino
    log(f"[XUNITY] descargando {url.rsplit('/', 1)[-1]}")
    req = urllib.request.Request(url, headers={"User-Agent": "tlgames/1.0"})
    tmp = destino.with_suffix(".part")
    with urllib.request.urlopen(req, timeout=120) as resp, tmp.open("wb") as out:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
    tmp.replace(destino)
    return destino


def paquetes(build: dict, cache_dir: Path, log=print) -> dict:
    """Zips necesarios (descargados a cache_dir si faltan)."""
    if build["runtime"] != "mono":
        raise RuntimeError(f"runtime {build['runtime']}: XUnity automático sólo cubre builds Mono (IL2CPP necesita BepInEx 6, manual)")
    bep_key = "bepinex_x86" if build["arch"] == "x86" else "bepinex_x64"
    return {
        "bepinex": descargar(RELEASES[bep_key], cache_dir / RELEASES[bep_key].rsplit("/", 1)[-1], log),
        "xunity": descargar(RELEASES["xunity_mono"], cache_dir / RELEASES["xunity_mono"].rsplit("/", 1)[-1], log),
    }


_OMITIR = {"changelog.txt"}


def _extraer_zip(zip_path: Path, game_path: Path) -> int:
    """Extrae el zip en la raíz del juego (rutas seguras). Devuelve archivos escritos."""
    n = 0
    raiz = game_path.resolve()
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            if info.is_dir() or info.filename.lower() in _OMITIR:
                continue
            destino = (game_path / info.filename).resolve()
            if raiz != destino and raiz not in destino.parents:
                continue   # zip-slip
            destino.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, destino.open("wb") as dst:
                dst.write(src.read())
            n += 1
    return n


def config_ini(lang: str, endpoint: str) -> str:
    return (
        "[Service]\n"
        f"Endpoint={endpoint}\n"
        "FallbackEndpoint=\n"
        "\n[General]\n"
        f"Language={lang}\n"
        "FromLanguage=en\n"
        "\n[Files]\n"
        "Directory=Translation\\{Lang}\\Text\n"
        "OutputFile=Translation\\{Lang}\\Text\\_AutoGeneratedTranslations.txt\n"
        "\n[TextFrameworks]\n"
        "EnableUGUI=True\n"
        "EnableNGUI=True\n"
        "EnableTextMeshPro=True\n"
        "EnableTextMesh=True\n"
        "EnableIMGUI=False\n"
        "\n[Behaviour]\n"
        "MaxCharactersPerTranslation=1000\n"
        "IgnoreWhitespaceInDialogue=True\n"
        "MinDialogueChars=20\n"
        "ForceSplitTextAfterCharacters=0\n"
        "CopyToClipboard=False\n"
        "EnableTranslationScoping=False\n"
        "\n[Authentication]\n"
        "\n[Debug]\n"
        "EnableConsole=False\n"
    )


def instalar(game_path: Path, build: dict, cache_dir: Path, lang: str, endpoint: str, log=print) -> dict:
    zips = paquetes(build, cache_dir, log)
    n1 = _extraer_zip(zips["bepinex"], game_path)
    n2 = _extraer_zip(zips["xunity"], game_path)
    cfg = game_path / "BepInEx" / "config" / "AutoTranslatorConfig.ini"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(config_ini(lang, endpoint), encoding="utf-8")
    (game_path / "BepInEx" / "Translation" / lang / "Text").mkdir(parents=True, exist_ok=True)
    log(f"[XUNITY] instalado bepinex={zips['bepinex'].name} ({n1} archivos) xunity={zips['xunity'].name} ({n2} archivos) config={cfg.relative_to(game_path)}")
    return {"bepinex": zips["bepinex"].name, "xunity": zips["xunity"].name, "config": str(cfg)}


# ── Textos estáticos ───────────────────────────────────────────────────────────

def extraer_estaticos(data_dir: Path, min_len: int = 6, min_words: int = 2) -> list[str]:
    """Strings candidatos (EN, únicos, en orden de aparición) de level*/assets/resources."""
    import extract_static_strings as ess
    vistos, out = set(), []
    for fp in ess.iter_target_files(Path(data_dir)):
        data = fp.read_bytes()
        for it in (ess.extract_ascii(data, min_len), ess.extract_utf16le(data, min_len)):
            for _off, texto, _enc in it:
                texto = ess.normalize(texto)
                if not texto or texto in vistos:
                    continue
                vistos.add(texto)
                if ess.looks_translatable(texto, min_words):
                    out.append(texto)
    return out


def traductor_por_defecto(provider: str, budget: float | None = None):
    """Devuelve f(list[str]) -> list[str] con DeepL (pool) → OpenAI, cache compartida con Unity JSON."""
    import translate_unity_json as tuj
    pool = [v for k, v in sorted(os.environ.items()) if k.startswith("DEEPL_API_KEY") and v]
    tuj._DEEPL_POOL = pool
    key_openai = os.environ.get("OPENAI_API_KEY", "")
    budget = budget if budget is not None else float(os.environ.get("OPENAI_BUDGET_USD", "1.50"))
    cache_path = ROOT / "tools" / "tl" / ".cache" / "unity_static.json"
    cache = tuj._load_cache(cache_path)
    estado = {"deepl": provider in ("deepl", "auto") and bool(pool)}
    if not estado["deepl"] and not key_openai:
        raise RuntimeError("sin DEEPL_API_KEY ni OPENAI_API_KEY")

    def f(textos: list[str]) -> list[str]:
        out = []
        for i, t in enumerate(textos):
            tr, estado["deepl"] = tuj.translate_one(t, cache, estado["deepl"], "", key_openai, tuj.OPENAI_MODEL, budget)
            out.append(tr)
            if (i + 1) % 25 == 0:
                tuj._save_cache(cache_path, cache)
                print(f"[PROGRESS] strings={i + 1}/{len(textos)} pct={int((i + 1) * 100 / len(textos))}", flush=True)
        tuj._save_cache(cache_path, cache)
        return out
    return f


def pretraducir(game_path: Path, data_dir: Path, lang: str, traductor, work_dir: Path | None = None, log=print) -> dict:
    """Extrae estáticos → traduce → BepInEx/Translation/<lang>/Text/_static.txt (formato XUnity)."""
    import export_xunity_static_translations as exp
    work_dir = work_dir or (game_path / "_tl_work")
    work_dir.mkdir(parents=True, exist_ok=True)
    fuentes = extraer_estaticos(data_dir)
    log(f"[XUNITY] estaticos={len(fuentes)}")
    if not fuentes:
        return {"estaticos": 0, "traducidos": 0, "exportados": 0, "archivo": ""}
    traducciones = traductor(fuentes)
    corpus = work_dir / "static_strings_corpus.jsonl"
    with corpus.open("w", encoding="utf-8", newline="\n") as fh:
        for i, (s, t) in enumerate(zip(fuentes, traducciones)):
            fh.write(json.dumps({"index": i, "source": s, "target": t or ""}, ensure_ascii=False) + "\n")
    salida = game_path / "BepInEx" / "Translation" / lang / "Text" / STATIC_FILE
    reporte = work_dir / "static_export_report.json"
    exp.export(corpus, salida, reporte, max_len=1000)
    exportados = sum(1 for l in salida.read_text(encoding="utf-8").splitlines() if l and not l.startswith("#"))
    traducidos = sum(1 for s, t in zip(fuentes, traducciones) if t and t != s)
    log(f"[XUNITY] estaticos={len(fuentes)} traducidos={traducidos} exportados={exportados} archivo={salida.relative_to(game_path)}")
    return {"estaticos": len(fuentes), "traducidos": traducidos, "exportados": exportados, "archivo": str(salida)}


# ── CLI ────────────────────────────────────────────────────────────────────────

def run(game_path: Path, provider: str = "auto", lang: str = "es", cache_dir: Path = CACHE_DIR_DEFAULT,
        endpoint: str = ENDPOINT_DEFAULT, pretranslate: bool = True, dry: bool = False, traductor=None, log=print) -> dict:
    build = detectar_build(game_path)
    if "error" in build:
        raise RuntimeError(build["error"])
    log(f"[XUNITY] build={build['runtime']} arch={build['arch']} data={Path(build['data_dir']).name}")
    if dry:
        return {"build": build, "dry": True}
    inst = instalar(game_path, build, cache_dir, lang, endpoint, log)
    res = {"build": build, "instalacion": inst}
    if pretranslate:
        res["estaticos"] = pretraducir(game_path, Path(build["data_dir"]), lang, traductor or traductor_por_defecto(provider), log=log)
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("game_path")
    ap.add_argument("--provider", choices=["auto", "deepl", "openai"], default="auto")
    ap.add_argument("--lang", default="es")
    ap.add_argument("--cache-dir", default=str(CACHE_DIR_DEFAULT))
    ap.add_argument("--endpoint", default=ENDPOINT_DEFAULT, help="endpoint de XUnity para lo no pre-traducido ('' = ninguno)")
    ap.add_argument("--no-pretranslate", action="store_true")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    try:
        run(Path(a.game_path), a.provider, a.lang, Path(a.cache_dir), a.endpoint, not a.no_pretranslate, a.dry)
    except RuntimeError as e:
        print(f"[ABORT] {e}", flush=True)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
