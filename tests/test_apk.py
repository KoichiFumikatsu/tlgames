"""Port Android por inyección en el APK oficial: nombres x-, firma vieja fuera, .rpyc sin comprimir, Ren'Py 7 → .rpy;
subida y vinculación del APK en la web."""
import io
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "tl"))

import apk_patch  # noqa: E402


def _juego(tmp_path, renpy="8.3.7"):
    game = tmp_path / "Juego"
    tl = game / "game" / "tl" / "spanish"
    tl.mkdir(parents=True)
    (tl / "script.rpy").write_text('translate spanish strings:\n    old "Hi"\n    new "Hola"\n', encoding="utf-8")
    (tl / "script.rpyc").write_bytes(b"RENPY RPC2 spanish")
    (tl / "sub" ).mkdir(); (tl / "sub" / "extra.rpyc").write_bytes(b"x"); (tl / "sub" / "font.ttf").write_bytes(b"F")
    (tl / "script.rpy.bak").write_bytes(b"no")
    (game / "game" / "_force_spanish.rpy").write_text("init 1500 python: pass\n", encoding="utf-8")
    (game / "game" / "_force_spanish.rpyc").write_bytes(b"force")
    (game / "renpy").mkdir(); (game / "renpy" / "__init__.py").write_text(f"version_tuple = ({renpy.replace('.', ', ')}, vc_version)\n", encoding="utf-8")
    return game


def _apk(tmp_path):
    apk = tmp_path / "Juego-android.apk"
    with zipfile.ZipFile(apk, "w") as z:
        z.writestr("AndroidManifest.xml", "m", compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("META-INF/MANIFEST.MF", "old"); z.writestr("META-INF/CERT.SF", "old"); z.writestr("META-INF/CERT.RSA", "old")
        z.writestr("META-INF/com/android/build/data.pb", "keep")
        z.writestr("assets/x-game/x-script.rpyc", "orig", compress_type=zipfile.ZIP_STORED)
        z.writestr("assets/x-game/x-tl/x-spanish/x-viejo.rpyc", "vieja traducción")
        z.writestr("assets/x-renpy/x-common/x-00start.rpyc", "common")
    return apk


def test_nombres_x_y_seleccion_de_archivos(tmp_path):
    game = _juego(tmp_path)
    assert apk_patch.version_renpy(game) == (8, 3, 7)
    rels = [str(r).replace("\\", "/") for _, r in apk_patch.archivos_tl(game, "spanish", compilados=True)]
    assert rels == ["tl/spanish/script.rpyc", "tl/spanish/sub/extra.rpyc", "tl/spanish/sub/font.ttf", "_force_spanish.rpyc"]
    rels7 = [str(r).replace("\\", "/") for _, r in apk_patch.archivos_tl(game, "spanish", compilados=False)]
    assert rels7 == ["tl/spanish/script.rpy", "tl/spanish/sub/font.ttf", "_force_spanish.rpy"]
    assert apk_patch.nombre_en_apk(Path("tl/spanish/sub/extra.rpyc")) == "assets/x-game/x-tl/x-spanish/x-sub/x-extra.rpyc"
    assert apk_patch.nombre_en_apk(Path("_force_spanish.rpyc")) == "assets/x-game/x-_force_spanish.rpyc"


def test_inyectar_quita_firma_y_traduccion_vieja_y_guarda_sin_comprimir(tmp_path):
    game, apk = _juego(tmp_path), _apk(tmp_path)
    out = tmp_path / "out.apk"
    r = apk_patch.inyectar(apk, out, apk_patch.archivos_tl(game, "spanish"), "spanish")
    assert r == {"copiadas": 4, "omitidas": 4, "agregadas": 4}
    with zipfile.ZipFile(out) as z:
        nombres = z.namelist()
        assert "META-INF/CERT.RSA" not in nombres and "META-INF/MANIFEST.MF" not in nombres and "META-INF/com/android/build/data.pb" in nombres
        assert "assets/x-game/x-tl/x-spanish/x-viejo.rpyc" not in nombres
        assert z.read("assets/x-game/x-tl/x-spanish/x-script.rpyc") == b"RENPY RPC2 spanish" and z.read("assets/x-game/x-_force_spanish.rpyc") == b"force"
        assert z.getinfo("assets/x-game/x-tl/x-spanish/x-script.rpyc").compress_type == zipfile.ZIP_STORED
        assert z.getinfo("AndroidManifest.xml").compress_type == zipfile.ZIP_DEFLATED and z.read("assets/x-game/x-script.rpyc") == b"orig"


def test_portar_compila_inyecta_y_firma(tmp_path, monkeypatch):
    game, apk = _juego(tmp_path), _apk(tmp_path)
    llamadas = []
    monkeypatch.setattr(apk_patch, "compilar", lambda sdk, g, timeout=900: llamadas.append("compile") or (0, "ok"))
    monkeypatch.setattr(apk_patch, "firmar", lambda p, log=print: llamadas.append(("firmar", p.name)))
    log = []
    r = apk_patch.portar(Path("renpy.sh"), game, apk, tmp_path / "salida" / "Juego-spanish.apk", "spanish", log=log.append)
    assert llamadas == ["compile", ("firmar", "Juego-spanish.apk")] and r["archivos"] == 4 and r["renpy"] == "8.3.7" and r["compilados"] is True and "aviso" not in r
    assert (tmp_path / "salida" / "Juego-spanish.apk").exists() and any("inyectados" in l for l in log)
    # Ren'Py 7: sin compilar, .rpy, con aviso
    game7 = _juego(tmp_path / "siete", renpy="7.4.11")
    llamadas.clear()
    r7 = apk_patch.portar(Path("renpy.sh"), game7, apk, tmp_path / "s7.apk", log=lambda m: None)
    assert llamadas == [("firmar", "s7.apk")] and r7["compilados"] is False and "Ren'Py 7.4.11" in r7["aviso"]
    with zipfile.ZipFile(tmp_path / "s7.apk") as z:
        assert "assets/x-game/x-tl/x-spanish/x-script.rpy" in z.namelist() and "assets/x-game/x-tl/x-spanish/x-script.rpyc" not in z.namelist()
    # sin traducción → error claro
    vacio = tmp_path / "Vacio"; (vacio / "game").mkdir(parents=True)
    with pytest.raises(RuntimeError, match="no hay traducción"):
        apk_patch.portar(Path("renpy.sh"), vacio, apk, tmp_path / "v.apk", log=lambda m: None)


def test_buscar_apk_y_firmar_usa_keystore_propio(tmp_path, monkeypatch):
    game = _juego(tmp_path)
    assert apk_patch.buscar_apk(game) is None
    (tmp_path / "Juego.apk").write_bytes(b"PK")
    assert apk_patch.buscar_apk(game) == tmp_path / "Juego.apk"
    monkeypatch.setattr(apk_patch, "ANDROID_DIR", tmp_path / "and"); monkeypatch.setattr(apk_patch, "SIGNER_JAR", tmp_path / "and" / "uber.jar")
    monkeypatch.setattr(apk_patch, "KEYSTORE", tmp_path / "and" / "k.jks"); monkeypatch.setattr(apk_patch, "KEYSTORE_PASS_FILE", tmp_path / "and" / "k.pass")
    monkeypatch.setattr(apk_patch, "BUILD_TOOLS", tmp_path / "and" / "bt")   # sin build-tools → cae a uber-apk-signer
    (tmp_path / "and").mkdir(); (tmp_path / "and" / "uber.jar").write_bytes(b"jar")
    cmds = []
    def run(cmd, **k):
        cmds.append(cmd)
        if cmd[0] == "keytool":
            (tmp_path / "and" / "k.jks").write_bytes(b"ks")
        return type("R", (), {"returncode": 0, "stdout": "signed successfully", "stderr": ""})()
    monkeypatch.setattr(apk_patch.subprocess, "run", run)
    apk_patch.firmar(tmp_path / "x.apk", log=lambda m: None)
    assert cmds[0][0] == "keytool" and cmds[1][:3] == ["java", "-jar", str(tmp_path / "and" / "uber.jar")] and "--allowResign" in cmds[1]
    clave = (tmp_path / "and" / "k.pass").read_text().strip()
    assert len(clave) >= 24 and cmds[1][cmds[1].index("--ksPass") + 1] == clave
    apk_patch.firmar(tmp_path / "x.apk", log=lambda m: None)
    assert [c[0] for c in cmds] == ["keytool", "java", "java"]     # el keystore se crea una sola vez


def test_web_sube_y_vincula_apk(server):
    apk = io.BytesIO()
    with zipfile.ZipFile(apk, "w") as z:
        z.writestr("AndroidManifest.xml", "m"); z.writestr("assets/x-game/x-script.rpyc", "o")
    datos = apk.getvalue()
    r = server.call("POST", "/upload", datos, headers={"Content-Type": "application/vnd.android.package-archive", "X-Nombre": "Juego-0.46-android.apk"})
    assert r.status == 201 and r.json()["apk"] == "Juego-0.46-android.apk"
    assert (server.entrada / "Juego-0.46-android.apk").read_bytes() == datos
    (server.entrada / "Juego").mkdir()
    d = server.call("GET", "/entrada").json()
    assert d["apks_sueltos"] == [{"nombre": "Juego-0.46-android.apk", "size": len(datos)}] and d["entrada"][0]["apk"] is False
    assert server.call("POST", "/entrada/apk", {"nombre": "Juego", "apk": "Juego-0.46-android.apk"}).status == 200
    d = server.call("GET", "/entrada").json()
    assert d["apks_sueltos"] == [] and d["entrada"][0]["apk"] is True and (server.entrada / "Juego.apk").exists()
    assert server.call("POST", "/entrada/apk", {"nombre": "Juego", "apk": "no.apk"}).status == 404
    assert server.call("POST", "/upload", b"no es apk", headers={"Content-Type": "application/vnd.android.package-archive", "X-Nombre": "x.apk"}).status == 400
    assert not list(server.entrada.glob(".upload-*"))
    (server.salida / "Juego-spanish.apk").write_bytes(b"PK"); (server.salida / ".Juego-spanish.part.apk").write_bytes(b"PK")
    s = server.call("GET", "/salida").json()["salida"]
    assert len(s) == 1 and s[0]["tipo"] == "android" and server.call("GET", "/salida/Juego-spanish.apk").headers.get("Content-Type") == "application/vnd.android.package-archive"


def test_firmar_con_build_tools(tmp_path, monkeypatch):
    bt = tmp_path / "bt"; bt.mkdir(); (bt / "zipalign").write_bytes(b"x"); (bt / "apksigner").write_bytes(b"x")
    monkeypatch.setattr(apk_patch, "BUILD_TOOLS", bt); monkeypatch.setattr(apk_patch, "ANDROID_DIR", tmp_path)
    monkeypatch.setattr(apk_patch, "KEYSTORE", tmp_path / "k.jks"); monkeypatch.setattr(apk_patch, "KEYSTORE_PASS_FILE", tmp_path / "k.pass")
    (tmp_path / "k.jks").write_bytes(b"ks")
    apk = tmp_path / "j.apk"; apk.write_bytes(b"PK")
    cmds = []
    def run(cmd, **k):
        cmds.append(cmd)
        if cmd[0].endswith("zipalign"):
            Path(cmd[-1]).write_bytes(b"PK-aligned")
        if cmd[0].endswith("apksigner"):
            (tmp_path / "j.apk.idsig").write_bytes(b"sig")
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
    monkeypatch.setattr(apk_patch.subprocess, "run", run)
    apk_patch.firmar(apk, log=lambda m: None)
    assert cmds[0][1:5] == ["-p", "-f", "4", str(apk)] and cmds[1][1] == "sign" and "--min-sdk-version" in cmds[1] and cmds[1][-1] == str(apk)
    assert apk.read_bytes() == b"PK-aligned" and not (tmp_path / "j.apk.idsig").exists() and not (tmp_path / "j.aligned.apk").exists()


def test_descarga_con_rango_para_reanudar(server):
    (server.salida / "Juego-spanish.zip").write_bytes(bytes(range(256)) * 4)   # 1024 bytes
    r = server.call("GET", "/salida/Juego-spanish.zip")
    assert r.status == 200 and r.headers.get("Accept-Ranges") == "bytes" and len(r.body) == 1024
    r = server.call("GET", "/salida/Juego-spanish.zip", headers={"Range": "bytes=1000-"})
    assert r.status == 206 and r.headers.get("Content-Range") == "bytes 1000-1023/1024" and r.body == (bytes(range(256)) * 4)[1000:]
    r = server.call("GET", "/salida/Juego-spanish.zip", headers={"Range": "bytes=0-9"})
    assert r.status == 206 and r.body == bytes(range(10)) and r.headers.get("Content-Length") == "10"
    r = server.call("GET", "/salida/Juego-spanish.zip", headers={"Range": "bytes=-4"})
    assert r.status == 206 and r.body == bytes([252, 253, 254, 255])
    assert server.call("GET", "/salida/Juego-spanish.zip", headers={"Range": "bytes=5000-"}).status == 416
