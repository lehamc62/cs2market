"""Offline checks: every HTTP call is replaced by a mock."""

import os
import unittest
from unittest.mock import Mock, patch
from urllib.parse import quote

import requests

import csfloat_client as client


class ClientTests(unittest.TestCase):
    def test_history_parsing_and_request(self):
        response = Mock()
        response.json.return_value = {"data": [
            {"day": "2026-11-16T00:00:00Z", "avg_price": 50050, "count": 4},
            {"day": "2026-11-15", "avg_price": 51070, "volume": 8},
        ]}
        with patch.dict(os.environ, {"CSFLOAT_API_KEY": "test-only"}), \
             patch.object(client.truststore, "inject_into_ssl"), \
             patch.object(client.requests, "get", return_value=response) as get:
            rows = client.get_price_history()

        self.assertEqual(rows, [
            {"date": "2026-11-15", "avg_price_usd": 510.7, "sales_count": 8},
            {"date": "2026-11-16", "avg_price_usd": 500.5, "sales_count": 4},
        ])
        get.assert_called_once_with(
            f"{client.BASE_URL}/history/{quote(client.ITEM_NAME, safe='')}/graph",
            headers={"Authorization": "test-only"},
            params={"paint_index": 421},
            timeout=30,
        )
        response.raise_for_status.assert_called_once()

    def test_listings_request_and_empty_data(self):
        response = Mock()
        response.json.return_value = {"data": []}
        with patch.dict(os.environ, {"CSFLOAT_API_KEY": "test-only"}), \
             patch.object(client.truststore, "inject_into_ssl"), \
             patch.object(client.requests, "get", return_value=response) as get:
            self.assertEqual(client.get_current_listings(), [])

        get.assert_called_once_with(
            f"{client.BASE_URL}/listings",
            headers={"Authorization": "test-only"},
            params={
                "market_hash_name": client.ITEM_NAME,
                "paint_index": 421,
                "category": 1,
                "sort_by": "lowest_price",
                "type": "buy_now",
                "limit": 20,
            },
            timeout=30,
        )

    def test_unexpected_payloads(self):
        for payload in ({}, {"data": {}}, {"data": [1]}):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    client._extract_records(payload, "теста")
        with self.assertRaises(ValueError):
            client._parse_price_history({"data": [{"day": "2026-11-16", "avg_price": 50050}]})
        self.assertEqual(
            client._parse_price_history({"data": [{"day": "2026-11-16", "avg_price": 50050.5, "count": "4"}]}),
            [{"date": "2026-11-16", "avg_price_usd": 500.505, "sales_count": 4}],
        )
        with self.assertRaisesRegex(ValueError, "get_price_history: запись 0, поле avg_price, тип str: не число"):
            client._parse_price_history({"data": [{"day": "2026-11-16", "avg_price": "bad", "count": 4}]})
        self.assertEqual(client._parse_price_history({"data": []}), [])

    def test_http_error_does_not_disclose_response(self):
        response = Mock()
        response.status_code = 403
        response.raise_for_status.side_effect = requests.HTTPError(response=response)
        with patch.dict(os.environ, {"CSFLOAT_API_KEY": "test-only"}), \
             patch.object(client.truststore, "inject_into_ssl"), \
             patch.object(client.requests, "get", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "HTTP 403") as error:
                client.get_price_history()
        self.assertNotIn("test-only", str(error.exception))

    def test_missing_key_makes_no_request(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(client.requests, "get") as get:
            with self.assertRaises(RuntimeError):
                client.get_price_history()
        get.assert_not_called()

    def test_variant_parameters_are_sent_without_extra_filters(self):
        response = Mock()
        response.json.return_value = {"data": []}
        with patch.dict(os.environ, {"CSFLOAT_API_KEY": "test-only"}), \
             patch.object(client.truststore, "inject_into_ssl"), \
             patch.object(client.requests, "get", return_value=response) as get:
            client.get_price_history("Desert Eagle | Cobalt Disruption (Field-Tested)", 231)
            client.get_current_listings("★ Stiletto Knife | Damascus Steel (Factory New)", 857)
        self.assertEqual(get.call_args_list[0].kwargs["params"], {"paint_index": 231})
        self.assertIn(quote("Desert Eagle | Cobalt Disruption (Field-Tested)", safe=""), get.call_args_list[0].args[0])
        self.assertEqual(get.call_args_list[1].kwargs["params"]["paint_index"], 857)
        self.assertEqual(get.call_args_list[1].kwargs["params"]["market_hash_name"],
                         "★ Stiletto Knife | Damascus Steel (Factory New)")


if __name__ == "__main__":
    unittest.main()
