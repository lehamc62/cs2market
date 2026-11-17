"""Offline smoke tests: run `python -m unittest -v test_catalog_repository.py`."""
import csv
import tempfile
import unittest
from pathlib import Path
from catalog_repository import CatalogRepository, CatalogError


class CatalogRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        data = {
            "weapons.csv": [
                {"weapon_id": "525", "name": "Skeleton Knife", "category": "Knives"}
            ],
            "skins.csv": [
                {"skin_id": "skin_1", "weapon_id": "525", "name": "★ Skeleton Knife | Doppler", "finish_name": "Doppler"}
            ],
            "skin_paints.csv": [
                {"source_skin_id": "skin-p4", "skin_id": "skin_1", "paint_index": "421", "phase": "Phase 4"},
                {"source_skin_id": "skin-p2", "skin_id": "skin_1", "paint_index": "419", "phase": "Phase 2"},
            ],
            "source_variants.csv": [
                {"source_variant_id": "v-p4-fn", "source_skin_id": "skin-p4", "market_hash_name": "★ Skeleton Knife | Doppler (Factory New)", "wear_name": "Factory New", "stattrak": "False", "souvenir": "False", "paint_index": "421"},
                {"source_variant_id": "v-p2-fn", "source_skin_id": "skin-p2", "market_hash_name": "★ Skeleton Knife | Doppler (Factory New)", "wear_name": "Factory New", "stattrak": "False", "souvenir": "False", "paint_index": "419"},
            ],
        }
        for fname, rows in data.items():
            with (root / fname).open("w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
        self.catalog = CatalogRepository(root)

    def tearDown(self):
        self.temp.cleanup()

    def test_navigation(self):
        weapons = self.catalog.weapons()
        self.assertEqual(weapons[0]["name"], "Skeleton Knife")
        skins = self.catalog.skins_for_weapon(525)
        self.assertEqual(len(skins), 1)
        paints = self.catalog.paints_for_skin(skins[0]["skin_id"])
        self.assertEqual(len(paints), 2)
        variants = self.catalog.variants_for_paint("skin-p4")
        self.assertEqual(len(variants), 1)

    def test_phase_is_not_lost_when_market_name_matches(self):
        selected = self.catalog.selected_variant("v-p4-fn")
        self.assertEqual(selected["paint_index"], 421)
        self.assertEqual(selected["phase"], "Phase 4")
        self.assertTrue(selected["market_name_is_ambiguous"])
        self.assertEqual(selected["edition"], "Normal")

    def test_unknown_variant(self):
        with self.assertRaises(CatalogError):
            self.catalog.selected_variant("missing")


if __name__ == "__main__":
    unittest.main()
