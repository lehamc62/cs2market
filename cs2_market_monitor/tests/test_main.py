"""Console output tests with no API access."""

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import main


class MainTests(unittest.TestCase):
    def test_summary_and_phase_check(self):
        history = [
            {"date": f"2026-11-{day:02d}", "avg_price_usd": 500.0 + day, "sales_count": day}
            for day in range(1, 12)
        ]
        listings = [
            {"price": cents, "item": {"paint_index": 421}}
            for cents in (47200, 47348, 47555)
        ]
        output = io.StringIO()
        with patch.object(main, "get_price_history", return_value=history), \
             patch.object(main, "get_current_listings", return_value=listings), \
             redirect_stdout(output):
            main.main()
        text = output.getvalue()
        self.assertIn("Дней с завершёнными продажами: 11", text)
        self.assertNotIn("2026-11-01:", text)
        self.assertIn("2026-11-11: $511.00, продаж: 11", text)
        self.assertIn("Текущих объявлений: 3", text)
        self.assertIn("Минимальная цена объявления: $472.00", text)
        self.assertIn("$475.55", text)

    def test_wrong_phase_is_rejected(self):
        with patch.object(main, "get_price_history", return_value=[]), \
             patch.object(main, "get_current_listings", return_value=[
                 {"price": 47200, "item": {"paint_index": 420}}
             ]), redirect_stdout(io.StringIO()):
            with self.assertRaises(ValueError):
                main.main()


if __name__ == "__main__":
    unittest.main()
