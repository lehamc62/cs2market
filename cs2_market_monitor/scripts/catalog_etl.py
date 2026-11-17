"""Prototype catalog ETL for ByMykel/CSGO-API.

No network, database, or extra dependencies. Preserves provenance and
separates base skins, paint/phase entries, and available wear options.
"""

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path


def read_json_array(path: Path) -> list[dict]:
    try:
        with path.open(encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Файл {path.name} содержит невалидный или обрезанный JSON "
            f"(строка {exc.lineno}, столбец {exc.colno}). "
            "Скачай полный файл и повтори запуск."
        ) from exc
    if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
        raise ValueError(f"В {path.name} ожидался JSON-массив объектов")
    return data


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def stable_key(weapon_id: int, name: str) -> str:
    digest = hashlib.sha256(f"{weapon_id}\0{name}".encode("utf-8")).hexdigest()[:16]
    return f"skin_{digest}"


def make_catalog(skins: list[dict]):
    weapons = {}
    weapon_aliases = defaultdict(set)
    bases = {}
    paints = {}
    wear_options = {}
    missing_paint = []

    for line, record in enumerate(skins, start=1):
        weapon = record.get("weapon")
        if not isinstance(weapon, dict):
            raise ValueError(f"skin #{line}: отсутствует объект weapon")
        weapon_id = int(weapon["weapon_id"])
        weapon_name = weapon["name"]
        weapon_code = weapon["id"]
        name = record["name"]
        source_id = record["id"]

        previous = weapons.get(weapon_id)
        if previous and previous["name"] != weapon_name:
            raise ValueError(f"weapon_id={weapon_id}: разные имена оружия")
        weapons[weapon_id] = {"weapon_id": weapon_id, "name": weapon_name,
                              "category": (record.get("category") or {}).get("name", "")}
        weapon_aliases[weapon_id].add(weapon_code)

        base_id = stable_key(weapon_id, name)
        bases.setdefault(base_id, {
            "skin_id": base_id, "weapon_id": weapon_id, "name": name,
            "finish_name": (record.get("pattern") or {}).get("name", ""),
        })
        if source_id in paints:
            raise ValueError(f"Повтор source_skin_id: {source_id}")
        raw_paint = record.get("paint_index")
        if raw_paint is None:
            missing_paint.append(source_id)
        paints[source_id] = {
            "source_skin_id": source_id, "skin_id": base_id,
            "paint_index": raw_paint if raw_paint is not None else "",
            "phase": record.get("phase") or "",
            "min_float": record.get("min_float", ""),
            "max_float": record.get("max_float", ""),
            "stattrak_available": bool(record.get("stattrak")),
            "souvenir_available": bool(record.get("souvenir")),
            "rarity_name": (record.get("rarity") or {}).get("name", ""),
            "image_url": record.get("image", ""),
        }
        for wear in record.get("wears") or []:
            key = (source_id, wear["id"])
            wear_options[key] = {
                "source_skin_id": source_id,
                "wear_id": wear["id"],
                "wear_name": wear["name"],
            }

    weapon_rows = [dict(row, source_weapon_ids="|".join(sorted(weapon_aliases[num])))
                   for num, row in weapons.items()]
    return (weapon_rows, list(bases.values()), list(paints.values()),
            list(wear_options.values()), missing_paint)


def make_source_variants(rows: list[dict], known_paints: set[str]):
    variants = []
    unknown_skin_ids = set()
    seen_ids = set()
    for line, record in enumerate(rows, start=1):
        item_id = record.get("id")
        source_skin_id = record.get("skin_id")
        if not item_id or not source_skin_id:
            raise ValueError(f"skins_not_grouped #{line}: отсутствует id или skin_id")
        if item_id in seen_ids:
            raise ValueError(f"Повтор id в skins_not_grouped: {item_id}")
        seen_ids.add(item_id)
        if source_skin_id not in known_paints:
            unknown_skin_ids.add(source_skin_id)
        variants.append({
            "source_variant_id": item_id,
            "source_skin_id": source_skin_id,
            "market_hash_name": record.get("market_hash_name") or "",
            "wear_id": (record.get("wear") or {}).get("id", ""),
            "wear_name": (record.get("wear") or {}).get("name", ""),
            "stattrak": bool(record.get("stattrak")),
            "souvenir": bool(record.get("souvenir")),
            "paint_index": record.get("paint_index") or "",
        })
    return variants, unknown_skin_ids


def main():
    parser = argparse.ArgumentParser(description="Первый ETL каталога CS2 (без БД)")
    parser.add_argument("--skins", type=Path, required=True,
                        help="Путь к полному skins.json")
    parser.add_argument("--not-grouped", type=Path,
                        help="Путь к полному skins_not_grouped.json (необязательно)")
    parser.add_argument("--output", type=Path, default=Path("data/processed"))
    args = parser.parse_args()

    # Сначала валидируем оба исходника, затем пишем результаты.
    # При обрезанном JSON не создаём частично обновлённый каталог.
    raw_skins = read_json_array(args.skins)
    weapons, skins, paints, wears, missing_paint = make_catalog(raw_skins)
    variants = None
    if args.not_grouped:
        raw_variants = read_json_array(args.not_grouped)
        variants, unknown = make_source_variants(raw_variants,
                                                {p["source_skin_id"] for p in paints})
        if unknown:
            raise ValueError(f"{len(unknown)} ссылок skin_id отсутствуют в skins.json; "
                             "проверь версию файлов")

    output = args.output
    write_csv(output / "weapons.csv",
              ["weapon_id", "name", "category", "source_weapon_ids"], weapons)
    write_csv(output / "skins.csv",
              ["skin_id", "weapon_id", "name", "finish_name"], skins)
    write_csv(output / "skin_paints.csv",
              ["source_skin_id", "skin_id", "paint_index", "phase",
               "min_float", "max_float", "stattrak_available", "souvenir_available",
               "rarity_name", "image_url"], paints)
    write_csv(output / "skin_wears.csv",
              ["source_skin_id", "wear_id", "wear_name"], wears)
    if variants is not None:
        write_csv(output / "source_variants.csv",
                  ["source_variant_id", "source_skin_id", "market_hash_name",
                   "wear_id", "wear_name", "stattrak", "souvenir", "paint_index"],
                  variants)

    print(f"skins.json: {len(raw_skins)} записей")
    print(f"weapons: {len(weapons)}; skins: {len(skins)}; "
          f"skin_paints: {len(paints)}; skin_wears: {len(wears)}")
    print(f"paint_index отсутствует у {len(missing_paint)} записей "
          "(не заполняем вымышленными значениями)")

    p4 = [p for p in paints if p["paint_index"] == "421" and
          any(s["skin_id"] == p["skin_id"] and
              s["name"] == "★ Skeleton Knife | Doppler" for s in skins)]
    print("Skeleton Doppler P4:", p4[0]["source_skin_id"] if p4 else "не найден")
    if variants is not None:
        print(f"skins_not_grouped.json: {len(variants)} вариантов")

    print(f"Готово: {output.resolve()}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, TypeError) as exc:
        raise SystemExit(f"Ошибка ETL: {exc}") from exc
