"""Read-only CS2 catalog repository for CSVs built by scripts/catalog_etl.py.

Does not call the network, access CSFloat API, or make market-identification guesses.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from typing import Any


class CatalogError(ValueError):
    """Invalid or incomplete local catalog."""


def _load_csv(folder: Path, filename: str, required_fields: set[str]) -> list[dict[str, str]]:
    path = folder / filename
    if not path.is_file():
        raise CatalogError(f"Файл каталога не найден: {path}")
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames or not required_fields.issubset(reader.fieldnames):
                raise CatalogError(f"{filename}: отсутствуют необходимые столбцы: "
                                   f"{sorted(required_fields - set(reader.fieldnames or []))}")
            rows = list(reader)
    except UnicodeError as exc:
        raise CatalogError(f"{filename}: ошибка кодировки") from exc
    if not rows:
        raise CatalogError(f"{filename}: пустой каталог")
    return rows


def _index_unique(rows: list[dict[str, str]], field: str, filename: str) -> dict[str, dict[str, str]]:
    result = {}
    for row in rows:
        key = row.get(field)
        if not key:
            raise CatalogError(f"{filename}: отсутствует {field}")
        if key in result:
            raise CatalogError(f"{filename}: повтор ключа {field}={key}")
        result[key] = row
    return result


def _edition(row: dict[str, str]) -> str:
    if row.get("stattrak", "").lower() == "true":
        return "StatTrak"
    if row.get("souvenir", "").lower() == "true":
        return "Souvenir"
    return "Normal"


class CatalogRepository:
    """Navigate weapon → skin → paint/phase → marketable wear/edition variant."""

    def __init__(self, processed_dir: str | Path):
        folder = Path(processed_dir)
        self._weapons = _load_csv(folder, "weapons.csv", {"weapon_id", "name", "category"})
        self._skins = _load_csv(folder, "skins.csv", {"skin_id", "weapon_id", "name", "finish_name"})
        self._paints = _load_csv(folder, "skin_paints.csv", {"source_skin_id", "skin_id", "paint_index", "phase"})
        self._variants = _load_csv(folder, "source_variants.csv", {
            "source_variant_id", "source_skin_id", "market_hash_name", "wear_name", "stattrak", "souvenir", "paint_index"
        })

        self._weapon_by_id = _index_unique(self._weapons, "weapon_id", "weapons.csv")
        self._skin_by_id = _index_unique(self._skins, "skin_id", "skins.csv")
        self._paint_by_id = _index_unique(self._paints, "source_skin_id", "skin_paints.csv")
        self._variant_by_id = _index_unique(self._variants, "source_variant_id", "source_variants.csv")

        self._skins_by_weapon: dict[str, list[dict[str, str]]] = defaultdict(list)
        self._paints_by_skin: dict[str, list[dict[str, str]]] = defaultdict(list)
        self._variants_by_paint: dict[str, list[dict[str, str]]] = defaultdict(list)
        self._paints_by_market_name: dict[str, set[str]] = defaultdict(set)

        for skin in self._skins:
            if skin["weapon_id"] not in self._weapon_by_id:
                raise CatalogError(f"skins.csv: неизвестный weapon_id={skin['weapon_id']}")
            self._skins_by_weapon[skin["weapon_id"]].append(skin)
        for paint in self._paints:
            if paint["skin_id"] not in self._skin_by_id:
                raise CatalogError(f"skin_paints.csv: неизвестный skin_id={paint['skin_id']}")
            self._paints_by_skin[paint["skin_id"]].append(paint)
        for variant in self._variants:
            paint_id = variant["source_skin_id"]
            paint = self._paint_by_id.get(paint_id)
            if paint is None:
                raise CatalogError(f"source_variants.csv: неизвестный source_skin_id={paint_id}")
            if paint["paint_index"] != variant["paint_index"]:
                raise CatalogError(f"source_variants.csv: различается paint_index ({variant['source_variant_id']})")
            self._variants_by_paint[paint_id].append(variant)
            self._paints_by_market_name[variant["market_hash_name"]].add(paint_id)

    def weapons(self) -> list[dict[str, str]]:
        return sorted(self._weapons, key=lambda x: (x["category"], x["name"]))

    def skins_for_weapon(self, weapon_id: str | int) -> list[dict[str, str]]:
        return sorted(self._skins_by_weapon.get(str(weapon_id), []), key=lambda x: x["finish_name"] or x["name"])

    def paints_for_skin(self, skin_id: str) -> list[dict[str, str]]:
        return sorted(self._paints_by_skin.get(skin_id, []), key=lambda x: (x["phase"], x["paint_index"]))

    def variants_for_paint(self, source_skin_id: str) -> list[dict[str, str]]:
        return sorted(self._variants_by_paint.get(source_skin_id, []),
                      key=lambda x: (x["wear_name"], _edition(x)))

    def selected_variant(self, source_variant_id: str) -> dict[str, Any]:
        """Return metadata for a user's exact selection, WITHOUT constructing API query args.

        API adapters must independently verify source-specific filter semantics for
        paint_index, wear and Normal / StatTrak / Souvenir before requesting prices.
        """
        variant = self._variant_by_id.get(source_variant_id)
        if variant is None:
            raise CatalogError(f"Неизвестный source_variant_id={source_variant_id}")
        paint = self._paint_by_id[variant["source_skin_id"]]
        skin = self._skin_by_id[paint["skin_id"]]
        weapon = self._weapon_by_id[skin["weapon_id"]]
        name = variant["market_hash_name"]
        matching_paints = self._paints_by_market_name[name]
        return {
            "source_variant_id": source_variant_id,
            "source_skin_id": paint["source_skin_id"],
            "skin_id": skin["skin_id"],
            "weapon_id": weapon["weapon_id"],
            "weapon_name": weapon["name"],
            "skin_name": skin["name"],
            "phase": paint["phase"] or None,
            "paint_index": int(paint["paint_index"]) if paint["paint_index"] else None,
            "wear": variant["wear_name"],
            "edition": _edition(variant),
            "market_hash_name": name,
            "market_name_is_ambiguous": len(matching_paints) > 1,
            "image_url": paint.get("image_url") or None,
            "min_float": paint.get("min_float") or None,
            "max_float": paint.get("max_float") or None,
            "rarity_name": paint.get("rarity_name") or None,
        }
