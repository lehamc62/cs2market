"""Print a small read-only CSFloat market snapshot."""

from csfloat_client import PAINT_INDEX, get_current_listings, get_price_history


def main() -> None:
    history = get_price_history()
    listings = get_current_listings()

    print(f"Дней с завершёнными продажами: {len(history)}")
    if history:
        print("Последние 10 дней продаж (дневная средняя):")
        for row in history[-10:]:
            print(f"  {row['date']}: ${row['avg_price_usd']:.2f}, продаж: {row['sales_count']}")
    else:
        print("История продаж пуста.")

    print(f"Текущих объявлений: {len(listings)}")
    if not listings:
        print("Объявлений нет.")
    else:
        prices = []
        for index, listing in enumerate(listings):
            item = listing.get("item")
            if not isinstance(item, dict):
                raise ValueError(f"get_current_listings: запись {index}, поле item, тип {type(item).__name__}: ожидается объект")
            phase = item.get("paint_index")
            if phase != PAINT_INDEX:
                raise ValueError(f"get_current_listings: запись {index}, поле item.paint_index, тип {type(phase).__name__}: ожидалось 421")
            cents = listing.get("price")
            if not isinstance(cents, int) or isinstance(cents, bool) or cents < 0:
                raise ValueError(f"get_current_listings: запись {index}, поле price, тип {type(cents).__name__}: ожидается неотрицательное целое число центов")
            prices.append(cents / 100)
        print(f"Минимальная цена объявления: ${min(prices):.2f}")
        print("Первые 10 цен объявлений:")
        for price in prices[:10]:
            print(f"  ${price:.2f}")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as exc:
        print(f"Ошибка: {exc}")
        raise SystemExit(1) from None

# See PyCharm help at https://www.jetbrains.com/help/pycharm/
