"""
Port Android para Ren'Py sin recompilar el juego: se inyecta la traducción en el APK oficial.

Ren'Py guarda el juego dentro del APK en `assets/x-game/…`, con cada carpeta y archivo prefijado `x-`
(renpy/loader.py), y en Android esa carpeta es de solo lectura. Por eso:
  1. `renpy.sh <juego> compile` genera los .rpyc de game/tl/<lang>/ y de game/_force_<lang>.rpy.
  2. Se copia el APK entrada por entrada (sin la firma vieja en META-INF) y se agregan
     `assets/x-game/x-tl/x-<lang>/x-*.rpyc` y `assets/x-game/x-_force_<lang>.rpyc`, sin comprimir.
  3. Se alinea y firma con nuestra llave (uber-apk-signer + keystore propio, creado una vez con keytool).
El jugador debe desinstalar el APK original (cambia la firma), como en cualquier traducción fan.
Si el juego es Ren'Py 7 (Python 2) los .rpyc de nuestro SDK 8 no le sirven: se inyectan los .rpy y se avisa.

Uso: python apk_patch.py <ruta_juego_pc> <juego.apk> <salida.apk> [--lang spanish]
"""
from __future__ import annotations

import argparse
import os
import re
import secrets
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ANDROID_DIR = Path(os.environ.get("ANDROID_TL_DIR", str(Path.home() / "apps" / "android-tl")))
SIGNER_JAR = ANDROID_DIR / "uber-apk-signer.jar"
KEYSTORE = ANDROID_DIR / "tlgames.jks"
KEYSTORE_PASS_FILE = ANDROID_DIR / "keystore.pass"
ALIAS = "tlgames"
_FIRMA = re.compile(r"^META-INF/(MANIFEST\.MF|.+\.(SF|RSA|DSA|EC))$", re.IGNORECASE)


def version_renpy(game_path: Path) -> tuple[int, ...] | None:
    """Versión del Ren'Py que trae el juego (renpy/__init__.py o renpy/vc_version.py); None si no se sabe."""
    for rel in ("renpy/__init__.py", "renpy/vc_version.py"):
        p = game_path / rel
        if p.exists():
            m = re.search(r"version_tuple\s*=\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", p.read_text(encoding="utf-8", errors="replace"))
            if m:
                return tuple(int(x) for x in m.groups())
    return None


def compilar(sdk: Path, game_path: Path, timeout: int = 900) -> tuple[int, str]:
    env = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    r = subprocess.run([str(sdk), str(game_path), "compile"], capture_output=True, text=True, timeout=timeout,
                       cwd=str(game_path.parent), env=env)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def archivos_tl(game_path: Path, lang: str, compilados: bool = True) -> list[tuple[Path, Path]]:
    """[(ruta absoluta, ruta relativa a game/)] de la traducción: tl/<lang>/** (.rpyc o .rpy según `compilados`,
    más fuentes/imágenes que haya ahí) y _force_<lang>.rpy(c)."""
    game = game_path / "game"
    ext_script, ext_omitir = (".rpyc", ".rpy") if compilados else (".rpy", ".rpyc")
    out = []
    tl = game / "tl" / lang
    if tl.is_dir():
        for p in sorted(tl.rglob("*")):
            if p.is_file() and p.suffix.lower() != ext_omitir and p.suffix.lower() not in (".bak", ".json"):
                out.append((p, p.relative_to(game)))
    for nombre in (f"_force_{lang}{ext_script}",):
        p = game / nombre
        if p.exists():
            out.append((p, p.relative_to(game)))
    return out


def nombre_en_apk(rel: Path) -> str:
    return "assets/x-game/" + "/".join("x-" + parte for parte in rel.parts)


def inyectar(apk_in: Path, apk_out: Path, entradas: list[tuple[Path, Path]], lang: str) -> dict:
    """Copia el APK sin firma vieja ni traducción previa de <lang>, y agrega las entradas sin comprimir."""
    prefijo_tl = f"assets/x-game/x-tl/x-{lang}/"
    nuevas = {nombre_en_apk(rel): src for src, rel in entradas}
    copiadas = omitidas = 0
    apk_out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(apk_in) as zin, zipfile.ZipFile(apk_out, "w") as zout:
        for info in zin.infolist():
            if _FIRMA.match(info.filename) or info.filename.startswith(prefijo_tl) or info.filename in nuevas:
                omitidas += 1
                continue
            with zin.open(info) as src, zout.open(info, "w") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
            copiadas += 1
        for nombre, src in nuevas.items():
            info = zipfile.ZipInfo(nombre, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED   # Ren'Py lee los assets sin descomprimir
            with src.open("rb") as fh, zout.open(info, "w") as dst:
                shutil.copyfileobj(fh, dst, 1 << 20)
    return {"copiadas": copiadas, "omitidas": omitidas, "agregadas": len(nuevas)}


def clave_keystore() -> str:
    if KEYSTORE_PASS_FILE.exists():
        return KEYSTORE_PASS_FILE.read_text(encoding="utf-8").strip()
    ANDROID_DIR.mkdir(parents=True, exist_ok=True)
    clave = secrets.token_urlsafe(24)
    KEYSTORE_PASS_FILE.write_text(clave, encoding="utf-8")
    os.chmod(KEYSTORE_PASS_FILE, 0o600)
    return clave


def asegurar_keystore(log=print) -> Path:
    """Llave propia, una sola vez: con ella las actualizaciones instalan encima de la traducción anterior."""
    if KEYSTORE.exists():
        return KEYSTORE
    clave = clave_keystore()
    r = subprocess.run(["keytool", "-genkeypair", "-keystore", str(KEYSTORE), "-alias", ALIAS, "-keyalg", "RSA", "-keysize", "2048",
                        "-validity", "10000", "-storepass", clave, "-keypass", clave, "-dname", "CN=TL Games, O=TL Games"],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError("keytool falló: " + (r.stderr or r.stdout)[-300:])
    os.chmod(KEYSTORE, 0o600)
    log(f"[APK] keystore creado en {KEYSTORE}")
    return KEYSTORE


def firmar(apk: Path, log=print) -> None:
    if not SIGNER_JAR.exists():
        raise RuntimeError(f"falta {SIGNER_JAR} (uber-apk-signer)")
    ks = asegurar_keystore(log)
    clave = clave_keystore()
    r = subprocess.run(["java", "-jar", str(SIGNER_JAR), "--apks", str(apk), "--ks", str(ks), "--ksAlias", ALIAS, "--ksPass", clave,
                        "--ksKeyPass", clave, "--allowResign", "--overwrite"], capture_output=True, text=True, timeout=900)
    salida = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0 or "signed" not in salida.lower():
        raise RuntimeError("firma falló: " + salida[-400:])
    log("[APK] alineado y firmado")


def portar(sdk: Path, game_path: Path, apk_in: Path, apk_out: Path, lang: str = "spanish", log=print) -> dict:
    ver = version_renpy(game_path)
    compilados = ver is None or ver[0] >= 8
    aviso = None
    if compilados:
        rc, salida = compilar(sdk, game_path)
        if rc != 0:
            raise RuntimeError("renpy compile falló: " + salida[-300:])
    else:
        aviso = f"el juego es Ren'Py {'.'.join(map(str, ver))}: se inyectan .rpy sin compilar (nuestro SDK 8 no genera .rpyc compatibles); probar en el dispositivo"
        log("[APK] " + aviso)
    entradas = archivos_tl(game_path, lang, compilados)
    if not entradas:
        raise RuntimeError(f"no hay traducción en game/tl/{lang}")
    res = inyectar(apk_in, apk_out, entradas, lang)
    log(f"[APK] {res['agregadas']} archivos de traducción inyectados ({res['copiadas']} originales copiados)")
    firmar(apk_out, log)
    out = {"apk": str(apk_out), "size_mb": round(apk_out.stat().st_size / 1048576, 1), "archivos": res["agregadas"],
           "renpy": ".".join(map(str, ver)) if ver else "", "compilados": compilados}
    if aviso:
        out["aviso"] = aviso
    log(f"[APK] listo: {apk_out.name} · {out['size_mb']} MB")
    return out


def buscar_apk(game_path: Path) -> Path | None:
    """APK oficial subido para este juego: entrada/<juego>.apk (o cualquier .apk dentro de la carpeta)."""
    candidatos = [game_path.with_suffix(".apk"), game_path.parent / f"{game_path.name}.apk"]
    for c in candidatos:
        if c.is_file():
            return c
    if game_path.is_dir():
        sueltos = sorted(p for p in game_path.glob("*.apk") if p.is_file())
        if sueltos:
            return sueltos[0]
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("game_path"); ap.add_argument("apk"); ap.add_argument("salida")
    ap.add_argument("--lang", default="spanish")
    ap.add_argument("--sdk", default=os.environ.get("RENPY_SDK", ""))
    a = ap.parse_args(argv)
    sdk = Path(a.sdk)
    if sdk.is_dir():
        sdk = sdk / "renpy.sh"
    try:
        portar(sdk, Path(a.game_path), Path(a.apk), Path(a.salida), a.lang)
    except RuntimeError as e:
        print(f"[ABORT] {e}")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
