"""Read-only requests for Skeleton Knife Doppler FN Phase 4 on CSFloat."""

import os
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

import requests
import truststore


ITEM_NAME = "★ Skeleton Knife | Doppler (Factory New)"
PAINT_INDEX = 421
BASE_URL = "https://csfloat.com/api/v1"
TIMEOUT_SECONDS = 30


def _get_json(url: str, params: dict[str, object]) -> object:
    api_key = os.getenv("CSFLOAT_API_KEY")
    if not api_key:
        raise RuntimeError("Не задана переменная окружения CSFLOAT_API_KEY")

    truststore.inject_into_ssl()
    try:
        response = requests.get(
            url,
            headers={"Authorization": api_key},
            params=params,
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()
    except requests.Timeout:
        raise RuntimeError("CSFloat API: превышено время ожидания") from None
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "неизвестен"
        raise RuntimeError(f"CSFloat API: ошибка HTTP {status}") from None
    except requests.RequestException:
        raise RuntimeError("CSFloat API: ошибка соединения") from None
    except ValueError:
        raise ValueError("CSFloat API: ответ не является JSON") from None


def _extract_records(payload: object, kind: str) -> list[dict]:
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict) and "data" in payload:
        records = payload["data"]
    else:
        raise ValueError(f"CSFloat API: неожиданный формат {kind}")
    if not isinstance(records, list):
        raise ValueError(f"CSFloat API: неожиданный формат {kind}")
    for index, row in enumerate(records):
        if not isinstance(row, dict):
            raise ValueError(f"{kind}: запись {index}, тип {type(row).__name__}: ожидается объект")
    return records


def _parse_price_history(payload: object) -> list[dict]:
    """Normalize daily averages using fields observed in the existing script."""
    records = _extract_records(payload, "истории продаж")
    result = []
    for index, row in enumerate(records):
        day = row.get("day")
        price = row.get("avg_price")
        count_field = "count" if "count" in row else "volume"
        count = row.get(count_field)
        if not isinstance(day, str) or not day:
            raise ValueError(f"get_price_history: запись {index}, поле day, тип {type(day).__name__}: отсутствует или не строка")
        if isinstance(price, bool) or not isinstance(price, (int, float, str)):
            raise ValueError(f"get_price_history: запись {index}, поле avg_price, тип {type(price).__name__}: ожидается числовое значение в центах")
        try:
            cents = Decimal(str(price))
        except InvalidOperation:
            raise ValueError(f"get_price_history: запись {index}, поле avg_price, тип {type(price).__name__}: не число") from None
        if not cents.is_finite() or cents < 0:
            raise ValueError(f"get_price_history: запись {index}, поле avg_price, тип {type(price).__name__}: цена не конечна или отрицательна")
        if isinstance(count, bool) or not isinstance(count, (int, float, str)):
            raise ValueError(f"get_price_history: запись {index}, поле {count_field}, тип {type(count).__name__}: отсутствует или не число")
        try:
            parsed_count = Decimal(str(count))
        except InvalidOperation:
            raise ValueError(f"get_price_history: запись {index}, поле {count_field}, тип {type(count).__name__}: не число") from None
        if not parsed_count.is_finite() or parsed_count < 0 or parsed_count != parsed_count.to_integral_value():
            raise ValueError(f"get_price_history: запись {index}, поле {count_field}, тип {type(count).__name__}: требуется неотрицательное целое число")
        try:
            parsed_day = date.fromisoformat(day[:10])
        except ValueError:
            raise ValueError(f"get_price_history: запись {index}, поле day, тип str: некорректная дата") from None
        result.append({
            "date": parsed_day.isoformat(),
            "avg_price_usd": float(cents / 100),
            "sales_count": int(parsed_count),
        })
    result.sort(key=lambda row: row["date"])
    return result


def get_price_history(market_hash_name: str = ITEM_NAME, paint_index: int | None = PAINT_INDEX) -> list[dict]:
    """Fetch completed sales, grouped as daily averages by CSFloat."""
    encoded_name = quote(market_hash_name, safe="")
    params = {"paint_index": paint_index} if paint_index is not None else {}
    payload = _get_json(
        f"{BASE_URL}/history/{encoded_name}/graph",
        params,
    )
    return _parse_price_history(payload)


def get_current_listings(market_hash_name: str = ITEM_NAME, paint_index: int | None = PAINT_INDEX) -> list[dict]:
    """Fetch current buy-now listings; Phase 4 filtering is sent to CSFloat."""
    payload = _get_json(
        f"{BASE_URL}/listings",
        {
            "market_hash_name": market_hash_name,
            **({"paint_index": paint_index} if paint_index is not None else {}),
            "category": 1,
            "sort_by": "lowest_price",
            "type": "buy_now",
            "limit": 20,
        },
    )
    return _extract_records(payload, "объявлений")
