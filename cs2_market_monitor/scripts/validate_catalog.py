"""Offline quality checks for catalog_etl.py CSV outputs.

Run from project root:
    python scripts/validate_catalog.py --input data/processed

No network / extra dependencies. Exit code 1 for broken references or duplicate IDs.
"""
import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path


def load_csv(path: Path) -> list[dict]:
    if not path.is_file():
        raise FileNotFoundError(f"Не найден {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def check_unique(rows: list[dict], key: str, name: str, errors: list[str]) -> None:
    vals = [r[key] for r in rows]
    duplicates = [v for v, qty in Counter(vals).items() if qty > 1]
    empty = sum(not v.strip() for v in vals)
    if duplicates:
        errors.append(f"{name}: дубли в {key}: {len(duplicates)} (примеры: {duplicates[:3]})")
    if empty:
        errors.append(f"{name}: пустое поле {key}: {empty} строк")


def check_references(rows: list[dict], key: str, allowed: set[str], name: str, errors: list[str]) -> None:
    missing = sorted({r[key] for r in rows if r[key] not in allowed})
    if missing:
        errors.append(f"{name}: отсутствующие FK {key}: {len(missing)} (примеры: {missing[:3]})")


def validate(folder: Path) -> int:
    weapons = load_csv(folder / "weapons.csv")
    skins = load_csv(folder / "skins.csv")
    paints = load_csv(folder / "skin_paints.csv")
    wears = load_csv(folder / "skin_wears.csv")
    variants = load_csv(folder / "source_variants.csv")

    errors: list[str] = []
    check_unique(weapons, "weapon_id", "weapons", errors)
    check_unique(skins, "skin_id", "skins", errors)
    check_unique(paints, "source_skin_id", "skin_paints", errors)
    check_unique(variants, "source_variant_id", "source_variants", errors)

    weapon_keys = {row["weapon_id"] for row in weapons}
    skin_keys = {row["skin_id"] for row in skins}
    paint_keys = {row["source_skin_id"] for row in paints}
    check_references(skins, "weapon_id", weapon_keys, "skins", errors)
    check_references(paints, "skin_id", skin_keys, "skin_paints", errors)
    check_references(wears, "source_skin_id", paint_keys, "skin_wears", errors)
    check_references(variants, "source_skin_id", paint_keys, "source_variants", errors)

    wear_keys = {(r["source_skin_id"], r["wear_id"]) for r in wears}
    if len(wear_keys) != len(wears):
        errors.append(f"skin_wears: дубли (source_skin_id, wear_id): {len(wears)-len(wear_keys)}")

    paint_index_by_id = {r["source_skin_id"]: r["paint_index"] for r in paints}
    mismatched_paint = [r for r in variants if
                       r["source_skin_id"] in paint_index_by_id and
                       r["paint_index"] != paint_index_by_id[r["source_skin_id"]]]
    if mismatched_paint:
        errors.append(f"source_variants: не совпадает paint_index с skin_paints: {len(mismatched_paint)}")

    unknown_wear = [r for r in variants if r["wear_id"] and
                    (r["source_skin_id"], r["wear_id"]) not in wear_keys]
    if unknown_wear:
        errors.append(f"source_variants: wear_id отсутствует в skin_wears: {len(unknown_wear)}")

    restricted = {r["source_skin_id"]: r for r in paints}
    bad_stattrak = [r for r in variants if r["stattrak"].lower() == "true" and
                    restricted.get(r["source_skin_id"], {}).get("stattrak_available") != "True"]
    bad_souvenir = [r for r in variants if r["souvenir"].lower() == "true" and
                    restricted.get(r["source_skin_id"], {}).get("souvenir_available") != "True"]
    if bad_stattrak:
        errors.append(f"source_variants: StatTrak там, где он недоступен в skins.json: {len(bad_stattrak)}")
    if bad_souvenir:
        errors.append(f"source_variants: Souvenir там, где он недоступен в skins.json: {len(bad_souvenir)}")

    # Market names may intentionally repeat across phases; count, never error.
    name_groups = defaultdict(set)
    for r in variants:
        if r["market_hash_name"]:
            name_groups[r["market_hash_name"]].add(r["source_skin_id"])
    shared_names = {name: refs for name, refs in name_groups.items() if len(refs) > 1}

    print("=== CS2 Catalog: проверка качества ===")
    for label, rows in [("weapons", weapons), ("skins", skins),
                        ("skin_paints", paints), ("skin_wears", wears),
                        ("source_variants", variants)]:
        print(f"{label}: {len(rows)}")
    print(f"Пустых paint_index: {sum(not r['paint_index'] for r in paints)}")
    print(f"market_hash_name, используемых несколькими skin_paints: {len(shared_names)}")
    if shared_names:
        print("  Пример (это НЕ обязательно ошибка):", next(iter(shared_names)))

    matching_skin_ids = {r["skin_id"] for r in skins if r["name"] == "★ Skeleton Knife | Doppler"}
    p4 = [p for p in paints if p["skin_id"] in matching_skin_ids and p["paint_index"] == "421"]
    if len(p4) != 1:
        errors.append(f"Skeleton Doppler P4: ожидалась 1 раскраска, найдено {len(p4)}")
    else:
        p4_id = p4[0]["source_skin_id"]
        p4_wears = sorted({r["wear_name"] for r in wears if r["source_skin_id"] == p4_id})
        p4_variants = [r for r in variants if r["source_skin_id"] == p4_id]
        print(f"Skeleton Doppler P4: {p4_id}")
        print(f"  Состояния: {', '.join(p4_wears)}")
        print(f"  Вариантов в source_variants: {len(p4_variants)}")
        print(f"  market_hash_name: {sorted(set(r['market_hash_name'] for r in p4_variants))}")
        if p4_wears != ["Factory New", "Minimal Wear"]:
            errors.append(f"Skeleton Doppler P4: неожиданные состояния {p4_wears}")

    if errors:
        print("\nОШИБКИ КАЧЕСТВА:")
        for msg in errors:
            print(" -", msg)
        return 1
    print("\nOK: уникальность ключей и связи проверены. Каталог можно использовать как источник для UI.")
    print("Важно: проверки не подтверждают полноту исходного каталога и корректность рыночных сопоставлений.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка связей и качества CSV каталога CS2")
    parser.add_argument("--input", type=Path, default=Path("data/processed"))
    return validate(parser.parse_args().input)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, KeyError, OSError) as exc:
        raise SystemExit(f"Ошибка проверки: {exc}") from exc
