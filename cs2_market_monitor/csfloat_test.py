
import os
import csv
from datetime import date
from urllib.parse import quote

import requests
import truststore

truststore.inject_into_ssl()

API_KEY = os.getenv("CSFLOAT_API_KEY")

if not API_KEY:
    raise RuntimeError("Не задан CSFLOAT_API_KEY")

ITEM_NAME = "★ Skeleton Knife | Doppler (Factory New)"
PAINT_INDEX = 421

DATE_FROM = date(2026, 10, 20)
DATE_TO = date(2026, 11, 17)

encoded_name = quote(ITEM_NAME, safe="")

url = (
    f"https://csfloat.com/api/v1/history/"
    f"{encoded_name}/graph"
)

response = requests.get(
    url,
    headers={"Authorization": API_KEY},
    params={"paint_index": PAINT_INDEX},
    timeout=30,
)

print("HTTP status:", response.status_code)

if response.status_code != 200:
    print("Ответ сервера:", response.text[:500])
    raise SystemExit(1)

payload = response.json()

if isinstance(payload, list):
    history = payload
elif isinstance(payload, dict):
    history = payload.get("data", [])
else:
    raise ValueError("Неизвестный формат ответа API")

if not isinstance(history, list):
    print("Формат ответа:", str(payload)[:1000])
    raise SystemExit(1)

rows = []

for entry in history:
    day = entry.get("day")
    avg_price = entry.get("avg_price")

    if not day or avg_price is None:
        continue

    current_date = date.fromisoformat(day[:10])

    if not DATE_FROM <= current_date <= DATE_TO:
        continue

    count = entry.get("count", entry.get("volume", 0))

    rows.append({
        "date": day[:10],
        "avg_price_usd": round(float(avg_price) / 100, 2),
        "sales_count": count,
    })

rows.sort(key=lambda x: x["date"])

print(f"Получено дней с продажами: {len(rows)}")
print("-" * 55)

for row in rows:
    print(
        f"{row['date']} | "
        f"${row['avg_price_usd']:.2f} | "
        f"Продаж: {row['sales_count']}"
    )

if rows:
    filename = "csfloat_skeleton_p4_history.csv"

    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "date",
                "avg_price_usd",
                "sales_count",
            ]
        )
        writer.writeheader()
        writer.writerows(rows)

    print("-" * 55)
    print("История сохранена:", filename)
else:
    print("Нет данных за выбранный диапазон.")
    print("Пример ответа API:", str(payload)[:1000])
