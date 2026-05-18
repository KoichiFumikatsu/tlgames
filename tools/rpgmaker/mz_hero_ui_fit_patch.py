#!/usr/bin/env python3
"""Patch Hero MZ UI strings that overflow narrow help windows."""

from __future__ import annotations

import argparse
import json
import re
import textwrap
from pathlib import Path
from typing import Any


DESCRIPTION_FILES = {"Items.json", "Weapons.json", "Armors.json", "Skills.json"}
MAX_HELP_LINE = 42
MAX_HELP_LINES = 2

NORMALIZE_REPLACEMENTS = {
    "Cancelararar": "Cancelar",
    "Cancelarar": "Cancelar",
    "Campamentoamentoamento": "Campamento",
    "Campamentoamento": "Campamento",
    "Apaga": "Apagado",
    "Retorno": "Volver",
}

DESCRIPTION_REPLACEMENTS = {
    "Un objeto que aumenta la simpatía en 10\n※Límite superior del nivel de simpatía 1": "Simpatía +10\nLímite: nivel de simpatía 1",
    "Un objeto que aumenta la simpatía en 10\n※Límite superior del nivel de simpatía 2": "Simpatía +10\nLímite: nivel de simpatía 2",
    "Un objeto que aumenta la simpatía en 100": "Simpatía +100",
    "10% de probabilidad de ver dentro de cofres, caminos\n ramificados, etc. (Se puede combinar con habilidades)": "Ver cofres/rutas: +10%\nCombina con habilidades.",
    "Probabilidad de huir al acercarse a un enemigo+10%\n(Se puede combinar con habilidades)": "Huida al acercarse: +10%\nCombina con habilidades.",
    "Probabilidad de huir al acercarse a un enemigo+20%\n(Puede combinarse con habilidades)": "Huida al acercarse: +20%\nCombina con habilidades.",
    "Probabilidad de huir al acercarse a un enemigo+30%\n(Puede combinarse con habilidades)": "Huida al acercarse: +30%\nCombina con habilidades.",
    "Aumenta un 60% la recuperación de MP al descansar en \"Campamento\"": "Recupera 60% de MP\nal descansar en Campamento.",
    "Incremento del 80% en recuperación de MP al descansar en \"Campamento\"": "Recupera 80% de MP\nal descansar en Campamento.",
    "Recuperación de MP al 100% al descansar con \"Campamento\"": "Recupera 100% de MP\nal descansar en Campamento.",
    "Enseña la habilidad \"Thunder I\" y desbloquea la rama de habilidades de relámpagos\n para Mago": "Enseña \"Thunder I\"\ny desbloquea la rama de rayos.",
    "Desbloquea la rama de habilidades de Regeneración en Maestría de Sanador": "Desbloquea Regeneración\nen Maestría de Sanador.",
    "Desbloquea la rama de habilidades de Crítico en Maestría de Guerrero": "Desbloquea Crítico\nen Maestría de Guerrero.",
    "Desbloquea la rama de habilidades Cascada en Maestría de Mago": "Desbloquea Cascada\nen Maestría de Mago.",
    "[Héroe] Espada de juguete que puede usar el Héroe.\n Aumenta en un 10% la experiencia ganada por todos los miembros del grupo.": "[Héroe] Espada de juguete.\nEXP del grupo +10%.",
    "[Héroe] Pulsera que puede usar el Héroe.\n Aumenta la tasa de embarazo en un 100% durante el sexo.": "[Héroe] Pulsera.\nEmbarazo +100% durante sexo.",
    "[Héroe] Pulsera que puede usar el Héroe.\n Aumenta la tasa de embarazo en un 50% durante el sexo.": "[Héroe] Pulsera.\nEmbarazo +50% durante sexo.",
    "[Héroe] Pulsera que puede usar el Héroe.\n Detiene la disminución del valor de excitación.": "[Héroe] Pulsera.\nEvita que baje la excitación.",
    "[Héroe] Pulsera que puede usar el Héroe.\n Anula la tasa de embarazo durante el sexo.": "[Héroe] Pulsera.\nAnula embarazo durante sexo.",
    "[Héroe] Casco de juguete que puede usar el Héroe.\n Aumenta en un 10% el oro obtenido.": "[Héroe] Casco de juguete.\nOro obtenido +10%.",
}

COMPACT_REPLACEMENTS = {
    "El diario de un aventurero que explora el ": "Diario de exploración: ",
    "El diario de un aventurero que explora la ": "Diario de exploración: ",
    "El diario de un aventurero que explora ": "Diario de exploración: ",
    "El diario de un aventurero explorando el ": "Diario de exploración: ",
    "El diario de un aventurero explorando la ": "Diario de exploración: ",
    "El diario de un aventurero explorando ": "Diario de exploración: ",
    ". Contiene información útil.": ". Info útil.",
    "Contiene información útil.": "Info útil.",
    "Se puede combinar con habilidades": "Combina con habilidades",
    "se puede combinar con habilidades": "combina con habilidades",
    "Puede combinarse con habilidades": "Combina con habilidades",
    "puede acumularse con habilidades": "acumula con habilidades",
    "Se puede apilar con objetos": "Acumula con objetos",
    "Se puede acumular hasta dos veces": "Acumula hasta 2 veces",
    "Puede apilarse hasta dos veces": "Acumula hasta 2 veces",
    "Probabilidad de": "Prob.",
    "probabilidad de": "prob.",
    "Aumenta la probabilidad de": "Aumenta prob. de",
    "Tasa de éxito al explorar": "Éxito al explorar",
    "Defensa Mágica": "Def. Mágica",
    "defensa mágica": "def. mágica",
    "ataque mágico": "atk. mágico",
    "todos los miembros del grupo": "todo el grupo",
}


def normalize_text(value: str) -> tuple[str, int]:
    output = value
    changes = 0
    for source, target in NORMALIZE_REPLACEMENTS.items():
        if source in output:
            output = output.replace(source, target)
            changes += 1
    return output, changes


def compact_text(value: str) -> str:
    output = value.strip()
    for source, target in COMPACT_REPLACEMENTS.items():
        output = output.replace(source, target)
    output = re.sub(r"\s+\n\s+", "\n", output)
    output = re.sub(r"[ \t]{2,}", " ", output)
    output = output.replace(" .", ".")
    return output.strip()


def wrap_two_lines(value: str, max_line: int) -> str:
    lines = []
    for part in value.split("\n"):
        stripped = part.strip()
        if not stripped:
            continue
        lines.extend(textwrap.wrap(stripped, width=max_line, break_long_words=False, break_on_hyphens=False) or [stripped])

    if len(lines) <= MAX_HELP_LINES and all(len(line) <= max_line for line in lines):
        return "\n".join(lines)

    joined = " ".join(lines)
    lines = textwrap.wrap(joined, width=max_line, break_long_words=False, break_on_hyphens=False)
    if len(lines) <= MAX_HELP_LINES:
        return "\n".join(lines)

    first = lines[0]
    second = " ".join(lines[1:])
    if len(second) > max_line:
        second = second[: max_line - 1].rstrip() + "…"
    return first + "\n" + second


def fit_description(value: str, max_line: int) -> tuple[str, bool]:
    normalized = value.replace("\\n", "\n")
    normalized, _ = normalize_text(normalized)
    if normalized in DESCRIPTION_REPLACEMENTS:
        fitted = DESCRIPTION_REPLACEMENTS[normalized]
    else:
        fitted = compact_text(normalized)
        fitted = wrap_two_lines(fitted, max_line)
    return fitted, fitted != value


def patch_database_file(path: Path, max_line: int) -> tuple[Any, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    report: dict[str, Any] = {"normalized_strings": 0, "descriptions": []}

    def walk(value: Any) -> Any:
        if isinstance(value, str):
            patched, changes = normalize_text(value)
            report["normalized_strings"] += changes
            return patched
        if isinstance(value, list):
            return [walk(item) for item in value]
        if isinstance(value, dict):
            return {key: walk(item) for key, item in value.items()}
        return value

    data = walk(data)

    if path.name in DESCRIPTION_FILES and isinstance(data, list):
        for entry in data:
            if not isinstance(entry, dict):
                continue
            description = entry.get("description")
            if not isinstance(description, str) or not description:
                continue
            fitted, changed = fit_description(description, max_line)
            if changed:
                entry["description"] = fitted
                report["descriptions"].append(
                    {
                        "id": entry.get("id"),
                        "name": entry.get("name"),
                        "before": description,
                        "after": fitted,
                    }
                )

    return data, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Patch Hero MZ UI text overflow")
    parser.add_argument("game_root", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--max-line", type=int, default=MAX_HELP_LINE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    changed_files: list[dict[str, Any]] = []
    for path in sorted((args.game_root / "data").glob("*.json")):
        patched, file_report = patch_database_file(path, args.max_line)
        description_changes = len(file_report["descriptions"])
        normalized_changes = file_report["normalized_strings"]
        if not description_changes and not normalized_changes:
            continue
        changed_files.append({"file": path.name, **file_report})
        if not args.dry_run:
            path.write_text(json.dumps(patched, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    report = {
        "game_root": str(args.game_root),
        "max_line": args.max_line,
        "dry_run": args.dry_run,
        "changed_files": changed_files,
        "total_files": len(changed_files),
        "total_normalized_strings": sum(item["normalized_strings"] for item in changed_files),
        "total_descriptions": sum(len(item["descriptions"]) for item in changed_files),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"changed_files={report['total_files']}")
    print(f"normalized_strings={report['total_normalized_strings']}")
    print(f"descriptions={report['total_descriptions']}")
    print(f"report={args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())