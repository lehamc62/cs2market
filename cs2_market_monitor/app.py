"""Local CS2 market dashboard. Start with: streamlit run app.py"""

from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import plotly.graph_objects as go
import streamlit as st

from csfloat_client import ITEM_NAME, PAINT_INDEX, get_current_listings, get_price_history
from scripts.catalog_repository import CatalogError, CatalogRepository


st.set_page_config(page_title="CS2 Market Monitor", page_icon="📈", layout="wide")

CATALOG_DIR = Path(__file__).resolve().parent / "data" / "processed"
WEAR_ORDER = ("Factory New", "Minimal Wear", "Field-Tested", "Well-Worn", "Battle-Scarred")


@st.cache_data(ttl=3600, show_spinner=False)
def load_history(variant_id: str, market_hash_name: str, paint_index: int | None) -> tuple[list[dict], datetime]:
    return get_price_history(market_hash_name, paint_index), datetime.now().astimezone()


@st.cache_data(ttl=300, show_spinner=False)
def load_listings(variant_id: str, market_hash_name: str, paint_index: int | None) -> tuple[list[dict], datetime]:
    return get_current_listings(market_hash_name, paint_index), datetime.now().astimezone()


def select_history(rows: list[dict], choice: str, custom: tuple[date, date] | None = None) -> list[dict]:
    if not rows:
        return []
    latest = max(date.fromisoformat(row["date"]) for row in rows)
    days = {"7 дней": 7, "30 дней": 30, "90 дней": 90, "1 год": 365}
    if choice == "Свои даты":
        if custom is None:
            return []
        start, end = custom
    elif choice in days:
        start, end = latest - timedelta(days=days[choice] - 1), latest
    else:
        return rows
    return [row for row in rows if start <= date.fromisoformat(row["date"]) <= end]


def weighted_trend(rows: list[dict], selected: list[dict]) -> list[float | None]:
    """Seven calendar days ending on each displayed day, using all fetched history."""
    if not rows:
        return []
    first = min(date.fromisoformat(row["date"]) for row in rows)
    result = []
    for current in selected:
        end = date.fromisoformat(current["date"])
        start = end - timedelta(days=6)
        window = [row for row in rows if start <= date.fromisoformat(row["date"]) <= end]
        volume = sum(row["sales_count"] for row in window)
        if start < first or volume == 0:
            result.append(None)
        else:
            result.append(sum(row["avg_price_usd"] * row["sales_count"] for row in window) / volume)
    return result


def weekly_sales(rows: list[dict]) -> list[tuple[date, int]]:
    totals: dict[date, int] = {}
    for row in rows:
        day = date.fromisoformat(row["date"])
        week_start = day - timedelta(days=day.weekday())
        totals[week_start] = totals.get(week_start, 0) + row["sales_count"]
    return sorted(totals.items())


def weekly_marks(groups: list[tuple[date, int]], today: date) -> tuple[list[str], list[str]]:
    current_week = today - timedelta(days=today.weekday())
    labels = ["Текущая неполная неделя" if day == current_week else "" for day, _ in groups]
    colors = ["#f59e0b" if day == current_week else "#4c78a8" for day, _ in groups]
    return labels, colors


def format_fetch_time(value: datetime | None) -> str:
    if value is None:
        return "нет"
    local = value.astimezone()
    offset = local.utcoffset()
    if offset is None:
        raise ValueError("Неизвестный часовой пояс времени обновления")
    minutes = int(offset.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    hours, remainder = divmod(abs(minutes), 60)
    zone = f"UTC{sign}{hours}" + (f":{remainder:02d}" if remainder else "")
    return f"{local:%d.%m.%Y, %H:%M} ({zone})"


def listing_url(listing: dict) -> str | None:
    listing_id = listing.get("id")
    if not isinstance(listing_id, (str, int)) or isinstance(listing_id, bool):
        return None
    identifier = str(listing_id)
    if not identifier or not all(char.isalnum() or char in "-_" for char in identifier):
        return None
    return f"https://csfloat.com/item/{quote(identifier, safe='')}"


def supported_by_csfloat(variant: dict) -> bool:
    """Known successful history query, including phase filter."""
    return (
        variant["market_hash_name"] == ITEM_NAME
        and variant["paint_index"] == PAINT_INDEX
        and variant["phase"] == "Phase 4"
        and variant["wear"] == "Factory New"
        and variant["edition"] == "Normal"
        and variant["weapon_name"] == "Skeleton Knife"
        and variant["skin_name"] == "★ Skeleton Knife | Doppler"
    )


def analytics_support(variant: dict) -> tuple[bool, bool, str]:
    name = variant["market_hash_name"]
    paint_index = variant["paint_index"]
    if not name:
        return False, False, "У варианта нет market_hash_name."
    if variant["phase"] and paint_index is None:
        return False, False, "Фаза указана, но paint_index отсутствует."
    if variant["market_name_is_ambiguous"] and paint_index is None:
        return False, False, "Одинаковое рыночное имя используется несколькими раскрасками без paint_index."
    history_ok = not variant["market_name_is_ambiguous"] or supported_by_csfloat(variant)
    reason = ("История продаж для совпадающих рыночных имён пока отключена: фильтрация другой фазы "
              "параметром paint_index в API истории не проверена." if not history_ok else "")
    return True, history_ok, reason


def available_paints(catalog: CatalogRepository, skin_id: str) -> list[dict]:
    return [row for row in catalog.paints_for_skin(skin_id)
            if catalog.variants_for_paint(row["source_skin_id"])]


def available_wears(variants: list[dict]) -> list[str]:
    present = {row["wear_name"] for row in variants}
    return sorted(present, key=lambda wear: (WEAR_ORDER.index(wear) if wear in WEAR_ORDER else len(WEAR_ORDER), wear))


def show_paint_selector(paints: list[dict]) -> bool:
    return len(paints) > 1


@st.cache_resource
def load_catalog() -> CatalogRepository:
    return CatalogRepository(CATALOG_DIR)


def choose_variant(catalog: CatalogRepository) -> dict:
    weapons = catalog.weapons()
    weapon = st.selectbox("Оружие", weapons, format_func=lambda row: f"{row['category']} · {row['name']}",
                          index=next((i for i, row in enumerate(weapons) if row["name"] == "Skeleton Knife"), 0))
    skins = catalog.skins_for_weapon(weapon["weapon_id"])
    if not skins:
        st.info("Для этого оружия нет скинов в каталоге.")
        st.stop()
    skin = st.selectbox("Скин", skins, format_func=lambda row: row["finish_name"] or row["name"],
                        index=next((i for i, row in enumerate(skins) if row["name"] == "★ Skeleton Knife | Doppler"), 0))
    paints = available_paints(catalog, skin["skin_id"])
    if not paints:
        st.info("Для этого скина нет доступных вариантов.")
        st.stop()
    if show_paint_selector(paints):
        paint = st.selectbox("Фаза / раскраска", paints,
                             format_func=lambda row: row["phase"] or f"Paint index {row['paint_index'] or 'не указан'}",
                             index=next((i for i, row in enumerate(paints) if row["paint_index"] == "421"), 0))
    else:
        paint = paints[0]
    variants = catalog.variants_for_paint(paint["source_skin_id"])
    wears = available_wears(variants)
    wear = st.selectbox("Состояние", wears, index=wears.index("Factory New") if "Factory New" in wears else 0)
    editions = sorted({"StatTrak" if row["stattrak"].lower() == "true" else
                       "Souvenir" if row["souvenir"].lower() == "true" else "Normal"
                       for row in variants if row["wear_name"] == wear},
                      key=lambda value: (value != "Normal", value))
    edition = st.selectbox("Версия", editions)
    matches = []
    for row in variants:
        if row["wear_name"] == wear:
            selected = catalog.selected_variant(row["source_variant_id"])
            if selected["edition"] == edition:
                matches.append(selected)
    if len(matches) != 1:
        st.warning("Выбор не соответствует одному варианту каталога.")
        st.stop()
    return matches[0]


def listing_table(rows: list[dict], paint_index: int | None = PAINT_INDEX) -> list[dict]:
    result = []
    for index, listing in enumerate(rows):
        item = listing.get("item")
        if not isinstance(item, dict):
            raise ValueError(f"Объявление {index}: поле item отсутствует или имеет неверный тип")
        if paint_index is not None and item.get("paint_index") != paint_index:
            raise ValueError(f"Объявление {index}: paint_index не равен {paint_index}")
        cents = listing.get("price")
        if not isinstance(cents, int) or isinstance(cents, bool) or cents < 0:
            raise ValueError(f"Объявление {index}: поле price не является неотрицательным целым числом")
        result.append({
            "Цена, USD": cents / 100,
            "Float": item.get("float_value"),
            "Pattern": item.get("paint_seed"),
            "Объявление": listing_url(listing),
        })
    return sorted(result, key=lambda row: row["Цена, USD"])


def main() -> None:
    st.title("CS2 Market Monitor")
    try:
        catalog = load_catalog()
        variant = choose_variant(catalog)
    except CatalogError as exc:
        st.error(f"Ошибка локального каталога: {exc}")
        st.stop()
    st.subheader(variant["market_hash_name"])
    st.caption(f"{variant['weapon_name']} · {variant['skin_name']} · {variant['phase'] or 'без фазы'} · "
               f"{variant['wear']} · {variant['edition']} · paint_index={variant['paint_index']}")
    if variant["image_url"]:
        st.image(variant["image_url"], width=220)
    st.caption(f"Редкость: {variant['rarity_name'] or 'не указана'} · "
               f"Float диапазон: {variant['min_float'] or '—'}–{variant['max_float'] or '—'}")
    listings_ok, history_ok, limitation = analytics_support(variant)
    if not listings_ok:
        st.info(f"Ценовая аналитика недоступна: {limitation}")
        return
    if limitation:
        st.info(limitation)

    cache_key = (variant["source_variant_id"], variant["market_hash_name"], variant["paint_index"])

    if st.button("Обновить данные", icon="🔄"):
        load_history.clear()
        load_listings.clear()
        st.rerun()
    st.caption("История обновляется не чаще раза в час, объявления — раз в 5 минут. Кнопка сбрасывает кэш.")

    try:
        history, history_fetched = load_history(*cache_key) if history_ok else ([], None)
    except (RuntimeError, ValueError) as exc:
        st.error(f"Не удалось получить историю продаж: {exc}")
        history, history_fetched = [], None
    try:
        raw_listings, listings_fetched = load_listings(*cache_key)
        listings = listing_table(raw_listings, variant["paint_index"])
    except (RuntimeError, ValueError) as exc:
        st.error(f"Не удалось получить объявления: {exc}")
        listings, listings_fetched = [], None

    st.caption(
        "Последнее успешное получение из API — "
        f"история: {format_fetch_time(history_fetched)}; "
        f"объявления: {format_fetch_time(listings_fetched)}"
    )

    choices = ["7 дней", "30 дней", "90 дней", "1 год", "Весь период", "Свои даты"]
    choice = st.segmented_control("Период продаж", choices, default="30 дней")
    custom = None
    if choice == "Свои даты" and history:
        first = min(date.fromisoformat(row["date"]) for row in history)
        last = max(date.fromisoformat(row["date"]) for row in history)
        selected = st.date_input("Даты включительно", value=(first, last), min_value=first, max_value=last)
        if isinstance(selected, tuple) and len(selected) == 2:
            custom = selected
        else:
            st.info("Выберите начальную и конечную даты.")
    selected_history = select_history(history, choice or "30 дней", custom)

    lowest = listings[0]["Цена, USD"] if listings else None
    latest = history[-1] if history else None
    latest_price = latest["avg_price_usd"] if latest else None
    difference = lowest - latest_price if lowest is not None and latest_price is not None else None
    difference_percent = difference / latest_price * 100 if difference is not None and latest_price else None
    columns = st.columns(5)
    columns[0].metric("Минимальное объявление", f"${lowest:,.2f}" if lowest is not None else "—")
    columns[1].metric("Последняя средняя продажа", f"${latest_price:,.2f}" if latest_price is not None else "—", help=f"{latest['date']}, сделок: {latest['sales_count']}" if latest else None)
    columns[1].caption(f"{latest['date']} · {latest['sales_count']} сделок" if latest else "Дата и число сделок недоступны")
    columns[2].metric("Объявление − продажа", f"${difference:+,.2f}" if difference is not None else "—", delta=f"{difference_percent:+.2f}%" if difference_percent is not None else None, delta_color="off")
    columns[3].metric("Загружено объявлений", len(listings) if listings else "—")
    columns[4].metric("Продаж за период", sum(row["sales_count"] for row in selected_history) if selected_history else "—")
    st.caption("Разница сопоставляет минимальное текущее объявление с последней дневной средней продаж. Это разные рыночные показатели, а не гарантированная скидка.")

    if not history and not history_ok:
        st.info("Графики продаж для этого варианта недоступны до проверки фильтров истории CSFloat.")
    elif not history:
        st.info("История продаж недоступна или пуста.")
    elif not selected_history:
        st.info("За выбранный период нет дней с продажами.")
    else:
        dates = [row["date"] for row in selected_history]
        price_mode = st.radio("Цена", ["Ежедневные значения", "Тренд за 7 дней"], horizontal=True)
        prices = ([row["avg_price_usd"] for row in selected_history] if price_mode == "Ежедневные значения"
                  else weighted_trend(history, selected_history))
        price_chart = go.Figure(go.Scatter(
            x=dates, y=prices,
            mode="lines+markers", name=price_mode,
            customdata=[row["sales_count"] for row in selected_history],
            hovertemplate="%{x}<br>$%{y:.2f}<br>Продаж: %{customdata}<extra></extra>",
        ))
        price_title = ("Средняя цена продаж по дням" if price_mode == "Ежедневные значения"
                       else "Средневзвешенная цена продаж за 7 дней")
        price_chart.update_layout(title=price_title, yaxis_title="USD", hovermode="x unified")
        st.plotly_chart(price_chart, width="stretch")

        long_period = (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days >= 60
        volume_mode = st.radio("Объём продаж", ["По дням", "По неделям"], index=1 if long_period else 0, horizontal=True)
        if volume_mode == "По неделям":
            groups = weekly_sales(selected_history)
            volume_dates, volumes = [day.isoformat() for day, _ in groups], [count for _, count in groups]
            today = datetime.now().astimezone().date()
            labels, colors = weekly_marks(groups, today)
        else:
            volume_dates, volumes = dates, [row["sales_count"] for row in selected_history]
            labels, colors = None, "#4c78a8"
        volume_chart = go.Figure(go.Bar(x=volume_dates, y=volumes, name="Продажи", text=labels, marker_color=colors))
        if volume_mode == "По неделям" and any(labels):
            st.caption("🟠 Текущая неделя ещё не завершилась; её объём нельзя сравнивать с полными неделями.")
        volume_chart.update_layout(title=f"Количество завершённых продаж {volume_mode.lower()}", yaxis_title="Сделок", hovermode="x unified")
        st.plotly_chart(volume_chart, width="stretch")
        st.caption("Тренд — средняя за 7 календарных дней с весом по числу сделок; расчёт использует историю до начала выбранного периода. Недельный объём — сумма сделок с понедельника по воскресенье; крайние недели могут быть неполными.")

    st.subheader("Текущие объявления")
    if listings:
        st.dataframe(listings, hide_index=True, width="stretch", column_config={
            "Цена, USD": st.column_config.NumberColumn(format="$%.2f"),
            "Float": st.column_config.NumberColumn(format="%.8f"),
            "Объявление": st.column_config.LinkColumn(display_text="Открыть"),
        })
    else:
        st.info("Объявления недоступны или список пуст.")


if __name__ == "__main__":
    main()
