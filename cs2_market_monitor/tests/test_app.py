"""Offline checks for dashboard data preparation."""

import csv
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app import analytics_support, available_paints, available_wears, format_fetch_time, listing_table, listing_url, select_history, show_paint_selector, supported_by_csfloat, weekly_marks, weekly_sales, weighted_trend
from scripts.catalog_repository import CatalogRepository


class AppTests(unittest.TestCase):
    def test_periods_with_existing_csv(self):
        path = Path(__file__).resolve().parents[1] / "data/fixtures/skeleton_p4_daily_sales_2026-10-20_2026-11-16.csv"
        with path.open(encoding="utf-8", newline="") as file:
            rows = [
                {"date": row["date"], "avg_price_usd": float(row["avg_price_usd"]), "sales_count": int(row["sales_count"])}
                for row in csv.DictReader(file)
            ]
        week = select_history(rows, "7 дней")
        self.assertEqual((len(week), week[0]["date"], week[-1]["date"]), (7, "2026-11-10", "2026-11-16"))
        self.assertEqual(sum(row["sales_count"] for row in week), 38)
        self.assertEqual(len(select_history(rows, "Весь период")), 28)
        self.assertEqual(len(select_history(rows, "Свои даты", (date(2026, 11, 15), date(2026, 11, 16)))), 2)

    def test_listing_price_and_phase(self):
        rows = [{"price": 47200, "item": {"paint_index": 421, "float_value": 0.017, "paint_seed": 676}}]
        self.assertEqual(listing_table(rows), [{"Цена, USD": 472.0, "Float": 0.017, "Pattern": 676, "Объявление": None}])
        rows[0]["item"]["paint_index"] = 420
        with self.assertRaises(ValueError):
            listing_table(rows)

    def test_weighted_trend_uses_days_before_selected_period(self):
        rows = [
            {"date": f"2026-11-{day:02d}", "avg_price_usd": 100.0 if day < 7 else 200.0, "sales_count": 1 if day < 7 else 4}
            for day in range(1, 9)
        ]
        self.assertEqual(weighted_trend(rows, rows[:1]), [None])
        self.assertAlmostEqual(weighted_trend(rows, rows[6:7])[0], 1400 / 10)
        self.assertAlmostEqual(weighted_trend(rows, rows[7:])[0], 2100 / 13)

    def test_weekly_sales_sums_partial_weeks(self):
        rows = [
            {"date": "2026-11-01", "sales_count": 2},
            {"date": "2026-11-02", "sales_count": 3},
            {"date": "2026-11-05", "sales_count": 4},
        ]
        self.assertEqual(weekly_sales(rows), [(date(2026, 10, 26), 2), (date(2026, 11, 2), 7)])

    def test_current_week_marked_separately(self):
        groups = [(date(2026, 11, 9), 30), (date(2026, 11, 16), 4)]
        labels, colors = weekly_marks(groups, date(2026, 11, 17))
        self.assertEqual(labels, ["", "Текущая неполная неделя"])
        self.assertNotEqual(colors[0], colors[1])

    def test_fetch_time_uses_local_offset(self):
        instant = datetime(2026, 11, 17, 11, 45, tzinfo=timezone.utc)
        local = instant.astimezone()
        offset = local.utcoffset()
        minutes = int(offset.total_seconds() // 60)
        sign = "+" if minutes >= 0 else "-"
        hours, remainder = divmod(abs(minutes), 60)
        suffix = f"UTC{sign}{hours}" + (f":{remainder:02d}" if remainder else "")
        self.assertEqual(format_fetch_time(instant), f"{local:%d.%m.%Y, %H:%M} ({suffix})")

    def test_listing_links_use_only_actual_ids(self):
        self.assertEqual(listing_url({"id": "123456"}), "https://csfloat.com/item/123456")
        self.assertIsNone(listing_url({}))
        self.assertIsNone(listing_url({"id": "../other"}))

    def test_full_catalog_maps_only_verified_variant(self):
        catalog = CatalogRepository(Path(__file__).resolve().parents[1] / "data/processed")
        weapon = next(row for row in catalog.weapons() if row["name"] == "Skeleton Knife")
        skin = next(row for row in catalog.skins_for_weapon(weapon["weapon_id"])
                    if row["name"] == "★ Skeleton Knife | Doppler")
        paints = catalog.paints_for_skin(skin["skin_id"])
        p4 = next(row for row in paints if row["paint_index"] == "421")
        p4_variants = [catalog.selected_variant(row["source_variant_id"])
                       for row in catalog.variants_for_paint(p4["source_skin_id"])]
        supported = [row for row in p4_variants if supported_by_csfloat(row)]
        self.assertEqual(len(supported), 1)
        self.assertEqual((supported[0]["wear"], supported[0]["edition"], supported[0]["phase"]),
                         ("Factory New", "Normal", "Phase 4"))
        self.assertTrue(supported[0]["image_url"])
        other_phase = next(row for row in paints if row["paint_index"] == "419")
        for row in catalog.variants_for_paint(other_phase["source_skin_id"]):
            self.assertFalse(supported_by_csfloat(catalog.selected_variant(row["source_variant_id"])))

    def test_wears_follow_cs2_order_and_only_present(self):
        rows = [{"wear_name": wear} for wear in
                ("Well-Worn", "Factory New", "Field-Tested", "Factory New", "Battle-Scarred")]
        self.assertEqual(available_wears(rows),
                         ["Factory New", "Field-Tested", "Well-Worn", "Battle-Scarred"])

    def test_paint_selector_only_when_choice_exists(self):
        catalog = CatalogRepository(Path(__file__).resolve().parents[1] / "data/processed")
        skins = [skin for weapon in catalog.weapons()
                 for skin in catalog.skins_for_weapon(weapon["weapon_id"])]
        single = next(skin for skin in skins if len(available_paints(catalog, skin["skin_id"])) == 1
                      and not available_paints(catalog, skin["skin_id"])[0]["phase"])
        one_paint = available_paints(catalog, single["skin_id"])
        self.assertFalse(show_paint_selector(one_paint))
        self.assertEqual(len(one_paint), 1)
        self.assertEqual(catalog.selected_variant(catalog.variants_for_paint(one_paint[0]["source_skin_id"])[0]["source_variant_id"])["paint_index"],
                         int(one_paint[0]["paint_index"]) if one_paint[0]["paint_index"] else None)
        doppler = next(skin for skin in skins if skin["name"] == "★ Skeleton Knife | Doppler")
        self.assertTrue(show_paint_selector(available_paints(catalog, doppler["skin_id"])))

    def test_query_mapping_for_three_catalog_variants(self):
        catalog = CatalogRepository(Path(__file__).resolve().parents[1] / "data/processed")
        cases = [
            ("skin-7ee0f56bd4a6_0", "★ Skeleton Knife | Doppler (Factory New)", 421, (True, True)),
            ("skin-6747a1a6fb43_2", "Desert Eagle | Cobalt Disruption (Field-Tested)", 231, (True, True)),
            ("skin-a0876f0e4bab_0", "★ Stiletto Knife | Damascus Steel (Factory New)", 857, (True, True)),
        ]
        for variant_id, name, paint, expected in cases:
            with self.subTest(variant_id=variant_id):
                variant = catalog.selected_variant(variant_id)
                self.assertEqual((variant["market_hash_name"], variant["paint_index"]), (name, paint))
                self.assertEqual(analytics_support(variant)[:2], expected)
        other_phase = catalog.selected_variant("skin-5a75fadc4005_0")
        self.assertEqual(analytics_support(other_phase)[:2], (True, False))


if __name__ == "__main__":
    unittest.main()
