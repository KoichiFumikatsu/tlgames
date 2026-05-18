#!/usr/bin/env python3
"""Patch Hero MZ residual English UI strings missed by the first extractor."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


REPLACEMENTS = {
    "Town of Frontier Castle": "Ciudad del Castillo",
    "Frontier Castle": "Castillo de la Frontera",
    "Frontier Village": "Aldea Frontera",
    "Nearby Forest": "Bosque cercano",
    "Grasslands": "Praderas",
    "Grassland": "Pradera",
    "Beast Forest": "Bosque de Bestias",
    "Spring Cave": "Cueva de Primavera",
    "Deepest Part of Spring Cave": "Fondo de la Cueva de Primavera",
    "Prison Tower": "Torre de la Prisión",
    "Wind Shrine": "Santuario del Viento",
    "Demon Lord's Castle": "Castillo del Rey Demonio",
    "Demon Lord\\'s Castle": "Castillo del Rey Demonio",
    "Temple of Peace": "Templo de la Paz",
    "Battle Labyrinth": "Laberinto de Batalla",
    "Trap Labyrinth": "Laberinto de Trampas",
    "Arena": "Arena",
    "Lady's Mansion": "Mansión de la dama",
    "Lady\\'s Mansion": "Mansión de la dama",
    "Frontier Castle's Maid": "Sirvienta del castillo",
    "Move to 「Town of Frontier Castle」": "Mover a «Ciudad del Castillo»",
    "Move to 「Frontier Castle」": "Mover a «Castillo de la Frontera»",
    "Go to Town of Frontier Castle": "Ir a la Ciudad del Castillo",
    "Go to the Frontier Castle": "Ir al Castillo de la Frontera",
    "Go to the Lady's Mansion": "Ir a la Mansión de la dama",
    "Go to the Lady\\'s Mansion": "Ir a la Mansión de la dama",
    "Return to Town of Frontier Castle": "Volver a la Ciudad del Castillo",
    "Do not return yet": "No volver todavía",
    "Proceed without opening": "Avanzar sin abrir",
    "Do not explore": "No explorar",
    "Open Menu Screen": "Abrir menú",
    "Go to Camp Menu": "Ir al menú de campamento",
    "Touch an ally – Action Point -1": "Tocar a una aliada - PA -1",
    "Gather glowing mushrooms": "Recolectar hongos brillantes",
    "Gather mushrooms": "Recolectar hongos",
    "Gather Malachite Ore": "Recolectar malaquita",
    "Gather Orichalcum Ore": "Recolectar oricalco",
    "Gather Adamantite Ore": "Recolectar adamantita",
    "Gather Mithril Ore": "Recolectar mitril",
    "Gather Sapphire": "Recolectar zafiro",
    "Gather Emerald": "Recolectar esmeralda",
    "Gather Diamond": "Recolectar diamante",
    "Gather herbs": "Recolectar hierbas",
    "Gather honey": "Recolectar miel",
    "Gather Ruby": "Recolectar rubí",
    "Open (disarm)": "Abrir (desarmar)",
    "Open en(s[204] || s[206])": "Abrir si(s[204] || s[206])",
    "Go back": "Regresar",
    "Not yet": "Aún no",
    "Don't Open": "No abrir",
    "Read it now": "Leer ahora",
    "Don't read it now": "No leer ahora",
    "Search": "Buscar",
    "Quit": "Salir",
    "Cancel": "Cancelar",
    "Camp": "Campamento",
    "Menu": "Menú",
    "Touch if(v[113]!=0)": "Tocar si(v[113]!=0)",
    "You encountered a traveling merchant!": "¡Te encontraste con un mercader ambulante!",
    "Recovered stamina while camping!": "¡Recuperaste energía al acampar!",
    "Returned to the normal path": "Volviste al camino normal",
    "Gathering materials...": "Recolectando materiales...",
    "Gathering materials......": "Recolectando materiales......",
    "Gathering materials.........": "Recolectando materiales.........",
    "Couldn't escape!": "¡No pudiste escapar!",
    "Enemy appeared!": "¡Apareció un enemigo!",
    "In progress...": "En progreso...",
    "Clear Bonus": "Bonificación por completar",
    "Successfully escaped!": "¡Escapaste con éxito!",
    "Moved on without opening": "Avanzaste sin abrirlo",
    "[Miss]": "[Fallo]",
    "[Hit]": "[Acierto]",
    "[Jackpot]": "[Premio mayor]",
    "You were spotted by the enemy!": "¡El enemigo te vio!",
    "First Clear Bonus": "Bonificación de primera victoria",
    "Drawn by the sound, enemies approached!": "¡Atraídos por el sonido, se acercaron enemigos!",
    "[Skill Activated] Discovered exploration point!": "[Habilidad activada] ¡Punto de exploración descubierto!",
    "[Skill Activated] Rarity increased!": "[Habilidad activada] ¡Rareza aumentada!",
    "Proceeded without incident": "Avanzaste sin incidentes",
    "Found \\V[126]G!": "¡Encontraste \\V[126] G!",
    "Arrived at firewood gathering spot": "Llegaste al punto de recolección de leña",
    "Obtained \\V[126] pieces of firewood!": "¡Obtuviste \\V[126] piezas de leña!",
    "Found a mushroom cluster!": "¡Encontraste un grupo de hongos!",
    "Gathered \\V[139] mushroom(s)!": "¡Recolectaste \\V[139] hongo(s)!",
    "Found a glowing mushroom cluster!": "¡Encontraste hongos brillantes!",
    "Gathered \\V[139] glowing mushroom(s)!": "¡Recolectaste \\V[139] hongo(s) brillante(s)!",
    "Progressed smoothly": "Avanzaste sin problemas",
    "A powerful enemy approaches...": "Se acerca un enemigo poderoso...",
    "There's a hot spring nearby": "Hay una fuente termal cerca",
    "Recovered stamina at the hot spring!": "¡Recuperaste energía en la fuente termal!",
    "Hurred onward": "Seguiste adelante con prisa",
    "Hurried onward": "Seguiste adelante con prisa",
    "Found a hot spring!": "¡Encontraste una fuente termal!",
    "Clear Bonus! Opened a bronze chest": "¡Bonificación! Cofre de bronce abierto",
    "Found a patch of herbs!": "¡Encontraste hierbas!",
    "Gathered \\V[139] herb(s)!": "¡Recolectaste \\V[139] hierba(s)!",
    "Found a bronze key chest!": "¡Encontraste un cofre con llave de bronce!",
    "Found a bronze trap chest!": "¡Encontraste un cofre trampa de bronce!",
    "Found a silver key chest!": "¡Encontraste un cofre con llave de plata!",
    "Found a silver trap chest!": "¡Encontraste un cofre trampa de plata!",
    "Found a gold key chest!": "¡Encontraste un cofre con llave de oro!",
    "Found a gold trap chest!": "¡Encontraste un cofre trampa de oro!",
    "Successfully disarmed the trap and opened it!": "¡Desactivaste la trampa y lo abriste!",
    "Failed to disarm the trap!": "¡No pudiste desactivar la trampa!",
    "It's an arousal gas!": "¡Es gas excitante!",
    "It exploded!": "¡Explotó!",
    "200 damage to the whole party!": "¡200 de daño a todo el grupo!",
    "Found a treasure chest!": "¡Encontraste un cofre del tesoro!",
    "Opened the treasure chest!": "¡Abriste el cofre del tesoro!",
    "Gave up on the treasure chest...": "Dejaste el cofre del tesoro...",
    "Found a treasure chest, but surrounded by enemies": "Encontraste un cofre, pero está rodeado de enemigos",
    "Obtained two potions!": "¡Obtuviste dos pociones!",
    "Obtained \\V[128]G!": "¡Obtuviste \\V[128] G!",
    "Obtained \\V[129]G!": "¡Obtuviste \\V[129] G!",
    "Obtained Copper Key!": "¡Obtuviste una llave de cobre!",
    "Obtained Silver Key!": "¡Obtuviste una llave de plata!",
    "Obtained Gold Key!": "¡Obtuviste una llave de oro!",
    "Obtained Universal Key!": "¡Obtuviste una llave universal!",
    "Obtained Unlock Tool!": "¡Obtuviste una herramienta de apertura!",
    "Would you like to read it now?": "¿Quieres leerlo ahora?",
    "Triggered a grass trap!!": "¡¡Activaste una trampa de hierba!!",
    "Triggered a tentacle trap!!": "¡¡Activaste una trampa de tentáculos!!",
    "Found a beehive!": "¡Encontraste una colmena!",
    "Gathered \\V[139] honey!": "¡Recolectaste \\V[139] de miel!",
    "Found a spring!": "¡Encontraste un manantial!",
    "Collected \\V[139] spring water!": "¡Recolectaste \\V[139] de agua de manantial!",
    "An alarm sounded!": "¡Sonó una alarma!",
    "It's a mimic!": "¡Es un mimic!",
    "A fork in the path": "Una bifurcación en el camino",
    "Chose the bright path": "Elegiste el camino iluminado",
    "Chose the dim path": "Elegiste el camino oscuro",
    "Ambushed by enemies!": "¡Emboscada enemiga!",
    "A wind starts blowing...": "Empieza a soplar el viento...",
    "...It's a trapdoor!!": "...¡¡Es una trampilla!!",
    "Aphrodisiac Gas sprayed out!!": "¡¡Salió gas afrodisíaco!!",
    "Found a Malachite ore vein!": "¡Encontraste una veta de malaquita!",
    "Gathered \\V[139] Malachite!": "¡Recolectaste \\V[139] de malaquita!",
    "Found a Sapphire vein!": "¡Encontraste una veta de zafiro!",
    "Gathered \\V[139] Sapphire(s)!": "¡Recolectaste \\V[139] zafiro(s)!",
    "Found a Mithril vein!": "¡Encontraste una veta de mitril!",
    "Gathered \\V[139] Mithril!": "¡Recolectaste \\V[139] de mitril!",
    "Found an Emerald vein!": "¡Encontraste una veta de esmeralda!",
    "Gathered \\V[139] Emerald(s)!": "¡Recolectaste \\V[139] esmeralda(s)!",
    "Found an Orichalcum vein!": "¡Encontraste una veta de oricalco!",
    "Gathered \\V[139] Orichalcum!": "¡Recolectaste \\V[139] de oricalco!",
    "Found a Ruby vein!": "¡Encontraste una veta de rubí!",
    "Gathered \\V[139] Ruby(s)!": "¡Recolectaste \\V[139] rubí(es)!",
    "Found an Adamantite vein!": "¡Encontraste una veta de adamantita!",
    "Gathered \\V[139] Adamantite!": "¡Recolectaste \\V[139] de adamantita!",
    "Found a Diamond vein!": "¡Encontraste una veta de diamante!",
    "Gathered \\V[139] Diamond(s)!": "¡Recolectaste \\V[139] diamante(s)!",
    "Delivering...": "Entregando...",
    "Delivering......": "Entregando......",
    "Delivering.........": "Entregando.........",
    "Delivery complete.": "Entrega completada.",
    "No items available for delivery.": "No hay objetos disponibles para entregar.",
    "Adventurer\\'s Note": "Nota de aventurero",
    "Adventurer's Note": "Nota de aventurero",
    "Defeat the slime in the Grasslands": "Derrota al slime en las praderas",
    "Hold a strategy meeting with Mage at the inn at night": "Reúnete con la maga en la posada por la noche",
    "Come back to the guild at night": "Vuelve al gremio por la noche",
    "Come back to the guild tomorrow": "Vuelve mañana al gremio",
    "Head to the guild in the northeast of the castle town": "Ve al gremio al noreste de la ciudad",
    "Defeat the wolf in the Beast Forest": "Derrota al lobo en el Bosque de Bestias",
    "Meet the adventurer at the village inn during the day": "Reúnete con el aventurero en la posada de día",
    "Greet the village chief in the frontier village": "Saluda al jefe de la Aldea Frontera",
    "Hurry and meet the queen": "Date prisa y reúnete con la reina",
    "Bring spring water to the maid at the lady's mansion": "Lleva agua de manantial a la sirvienta de la mansión",
    "Bring spring water to the maid at the lady\\'s mansion": "Lleva agua de manantial a la sirvienta de la mansión",
    "Talk to the spirit at the deepest part of the Spring Cave": "Habla con el espíritu en el fondo de la Cueva de Primavera",
    "Collect spring water from the deepest part of Spring Cave": "Recoge agua en el fondo de la Cueva de Primavera",
    "Go to the guild to meet the recruited frontliner": "Ve al gremio para conocer a la vanguardia reclutada",
    "Visit the guild tomorrow": "Visita el gremio mañana",
    "Head to the lady's mansion en route to 「Frontier Castle」": "Ve a la mansión de la dama camino al Castillo",
    "Head to the lady\\'s mansion en route to 「Frontier Castle」": "Ve a la mansión de la dama camino al Castillo",
    "Take on a quest at the guild": "Acepta una misión en el gremio",
    "Go meet the queen": "Ve a reunirte con la reina",
    "Meet the princess in the castle": "Reúnete con la princesa en el castillo",
    "Rescue the princess imprisoned in the Prison Tower": "Rescata a la princesa en la Torre de la Prisión",
    "Defeat the Demon Lord in the Demon Lord's Castle": "Derrota al Rey Demonio en su castillo",
    "Defeat the Demon Lord in the Demon Lord\\'s Castle": "Derrota al Rey Demonio en su castillo",
    "Meet the Wind Shrine Maiden at the Wind Shrine": "Reúnete con la sacerdotisa del Santuario del Viento",
    "Meet the Goddess at the Temple of Peace": "Reúnete con la diosa en el Templo de la Paz",
    "What happens if you stay at the inn in the castle town...?": "¿Qué pasará si te alojas en la posada de la ciudad...?",
    "What happens if you reach 100 Tolerance...?": "¿Qué pasará si alcanzas 100 de tolerancia...?",
}

ITEM_SOURCE_RE = re.compile(r"^\[[^\]]+\]\s+.+")
WORD_CHARS = "A-Za-zÁÉÍÓÚÜÑáéíóúüñ"
WHOLE_TOKEN_REPLACEMENTS = {"Cancel", "Camp", "Menu", "Search", "Quit", "Special"}
SPANISH_NORMALIZATIONS = {
    "Cancelararar": "Cancelar",
    "Cancelarar": "Cancelar",
    "Campamentoamentoamento": "Campamento",
    "Campamentoamento": "Campamento",
}


def clean_item_target(value: str) -> str:
    return value.strip().strip("¡!").strip()


def load_item_replacements(game_root: Path) -> dict[str, str]:
    corpus_path = game_root / "_tl_work" / "hero_mz_corpus.translated.jsonl"
    if not corpus_path.exists():
        return {}

    replacements: dict[str, str] = {}
    with corpus_path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            source = str(record.get("source", "")).strip()
            target = clean_item_target(str(record.get("target", "")))
            if not source or not target or source == target:
                continue
            if ITEM_SOURCE_RE.match(source) and not target.startswith("["):
                replacements[source] = target
    return replacements


def patch_string(value: str, dynamic_replacements: dict[str, str]) -> tuple[str, int]:
    changed = 0
    output = value
    for source, target in SPANISH_NORMALIZATIONS.items():
        if source in output:
            output = output.replace(source, target)
            changed += 1
    replacements = {**REPLACEMENTS, **dynamic_replacements}
    for source, target in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
        if source in WHOLE_TOKEN_REPLACEMENTS:
            continue
        if source in output:
            output = output.replace(source, target)
            changed += 1
    for source in WHOLE_TOKEN_REPLACEMENTS:
        target = replacements.get(source)
        if not target:
            continue
        pattern = re.compile(rf"(?<![{WORD_CHARS}]){re.escape(source)}(?![{WORD_CHARS}])")
        output, count = pattern.subn(target, output)
        changed += count
    if "Obtained " in output:
        output = output.replace("Obtained ", "Obtuviste ")
        changed += 1
    if "Cleared " in output:
        output = output.replace("Cleared ", "Completado ")
        changed += 1
    if "Found " in output:
        output = output.replace("Found ", "Encontrado ")
        changed += 1
    if "Gathered " in output:
        output = output.replace("Gathered ", "Recolectado ")
        changed += 1
    for source, target in SPANISH_NORMALIZATIONS.items():
        if source in output:
            output = output.replace(source, target)
            changed += 1
    return output, changed


def walk(value: Any, dynamic_replacements: dict[str, str]) -> tuple[Any, int]:
    if isinstance(value, str):
        return patch_string(value, dynamic_replacements)
    if isinstance(value, list):
        total = 0
        output = []
        for item in value:
            patched, changed = walk(item, dynamic_replacements)
            output.append(patched)
            total += changed
        return output, total
    if isinstance(value, dict):
        total = 0
        output = {}
        for key, item in value.items():
            patched, changed = walk(item, dynamic_replacements)
            output[key] = patched
            total += changed
        return output, total
    return value, 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Patch residual English Hero UI strings")
    parser.add_argument("game_root", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    changed_files: list[dict] = []
    total_replacements = 0
    dynamic_replacements = load_item_replacements(args.game_root)
    for path in sorted((args.game_root / "data").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        patched, replacements = walk(data, dynamic_replacements)
        if replacements:
            path.write_text(json.dumps(patched, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            changed_files.append({"file": path.name, "replacements": replacements})
            total_replacements += replacements

    report = {
        "game_root": str(args.game_root),
        "dynamic_replacements": len(dynamic_replacements),
        "changed_files": changed_files,
        "total_replacements": total_replacements,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"changed_files={len(changed_files)}")
    print(f"total_replacements={total_replacements}")
    print(f"report={args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())