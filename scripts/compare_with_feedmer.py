"""Пишет один и тот же заказ двумя путями и сравнивает получившиеся строки:

  1) "feedmer"  — дословный SQL каркаса: DBlib.addItem (строка на единицу, pk_order = NULL),
                  затем DBlib.saveOrder (INSERT ... RETURNING pk_orders),
                  затем UPDATE items SET pk_order = ... (как в saveOrder);
  2) "agentic"  — PostgresOrderSink этого проекта.

Запуск:
    .venv/Scripts/python.exe scripts/compare_with_feedmer.py
"""

from __future__ import annotations

import asyncio

import asyncpg

from food_order.adapters.orders_factory import build_order_sink
from food_order.domain.models import OrderItem, OrderState, PaymentMethod
from food_order.settings import get_settings

TELEGRAM_ID = 990000002
STRDATE = "04.10.2026"
PICKUP_TIME = "23:55"
CAFE_ID = 68
TEL = "+79990001122"
NAME = f"Клиент Telegram {TELEGRAM_ID}"
# 2 × 300 ₽ + 1 × 110 ₽
CART = [("Куриная Стандарт 320г", 300, 2), ("Воткинский лимонад", 110, 1)]

# Дословно из DBlib.js:920 (saveOrder) — порядок и набор колонок каркаса.
FEEDMER_ORDER_SQL = """
INSERT INTO orders (userid, strdate, deliverysum, formaladdr, "deliveryTimeStart",
    "deliveryTimeFinish", "cafeId", "printedDeliverySum", "payway", "recipientName",
    tel, addr, "ASAP", "className", "howToGet", "whatToDoIfNoAnswer",
    "bToCContractNum", "isDelivery")
VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18)
RETURNING pk_orders
"""

# Дословно из DBlib.js:600 (addItem)
FEEDMER_ITEM_SQL = """
INSERT INTO items (item_name, strdate, userid, cafeid, item_price, pk_order)
VALUES ($1, $2, $3, $4, $5, $6)
"""

# Дословно из DBlib.js:931 (привязка позиций к заказу внутри saveOrder)
FEEDMER_BIND_ITEMS_SQL = """
UPDATE items SET pk_order = $1
WHERE pk_order IS NULL AND cafeid = $2 AND userid = $3
  AND TO_DATE(strdate, 'DD.MM.YYYY') >= TO_DATE($4, 'DD.MM.YYYY') - INTERVAL '1 DAY'
"""

# Дословно из DBlib.js:569 (создание пользователя) + chatids из DBlib.js:731
# без колонки max_chatid, которой в этой БД нет.
FEEDMER_USER_SQL = """
INSERT INTO users (tel, addr, name, step, formaladdr, "invitedBy", "expectedOrderType")
VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING userid
"""
FEEDMER_CHATID_SQL = """
INSERT INTO chatids (userid, telegram_chatid, last_messanger, "cafeId", "superBotId", "vk_chatid")
VALUES ($1, $2, 'telegram', $3, NULL, NULL)
"""


async def ensure_user(conn: asyncpg.Connection) -> int:
    userid = await conn.fetchval(
        "SELECT userid FROM chatids WHERE telegram_chatid = $1 AND userid IS NOT NULL",
        TELEGRAM_ID,
    )
    if userid is not None:
        return userid
    userid = await conn.fetchval(FEEDMER_USER_SQL, None, None, NAME, "0", None, None, None)
    await conn.execute(FEEDMER_CHATID_SQL, userid, TELEGRAM_ID, CAFE_ID)
    return userid


async def write_like_feedmer(conn: asyncpg.Connection, userid: int) -> int:
    for name, price, qty in CART:
        for _ in range(qty):
            await conn.execute(FEEDMER_ITEM_SQL, name, STRDATE, userid, CAFE_ID, price, None)
    pk = await conn.fetchval(
        FEEDMER_ORDER_SQL,
        userid,
        STRDATE,
        0,  # deliverysum: calculateDeliverySum() = 0 for pickup
        None,  # formaladdr: pickup
        PICKUP_TIME,  # deliveryTimeStart
        None,  # deliveryTimeFinish: pickup has no window
        CAFE_ID,
        0,  # printedDeliverySum = deliverysum
        "картой при получении",
        NAME,
        TEL,
        None,  # addr
        False,  # ASAP: время выбрано явно, не кнопка ASAP
        None,  # className
        None,  # howToGet
        None,  # whatToDoIfNoAnswer
        None,  # bToCContractNum
        False,  # isDelivery: самовывоз
    )
    await conn.execute(FEEDMER_BIND_ITEMS_SQL, pk, CAFE_ID, userid, STRDATE)
    return pk


async def write_like_agentic(userid: int, db_url: str) -> str:
    sink = build_order_sink(get_settings())
    state = OrderState(
        items=[OrderItem(sku_id=f"demo-{i}", name=n, qty=q, unit_price=p)
               for i, (n, p, q) in enumerate(CART)],
        pickup_point_id=str(CAFE_ID),
        pickup_point_name="Raketa на Молодежной 107б",
        pickup_time=PICKUP_TIME,
        payment_method=PaymentMethod.CARD,
        phone=TEL,
    )
    created = await sink.create_order(
        telegram_user_id=TELEGRAM_ID, state=state, total=float(sum(p * q for _, p, q in CART))
    )
    close = getattr(sink, "close", None)
    if close is not None:
        await close()
    return created.order_id


async def fetch_order(conn: asyncpg.Connection, pk: int) -> dict:
    return dict(await conn.fetchrow("SELECT * FROM orders WHERE pk_orders = $1", pk))


async def fetch_items(conn: asyncpg.Connection, pk: int) -> list[tuple]:
    rows = await conn.fetch(
        'SELECT item_name, strdate, userid, cafeid, item_price FROM items'
        " WHERE pk_order = $1 ORDER BY item_name, item_price",
        pk,
    )
    return [tuple(r) for r in rows]


def fmt(value: object) -> str:
    text = "NULL" if value is None else str(value)
    return text if len(text) <= 28 else text[:25] + "..."


async def main() -> int:
    settings = get_settings()
    db_url = settings.orders_database_url or settings.database_url or ""
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)
    skipped = {"pk_orders", "timestamp", "recipientName", "comment"}
    try:
        async with pool.acquire() as conn:
            userid = await ensure_user(conn)
            feedmer_pk = await write_like_feedmer(conn, userid)
        agentic_pk = int(await write_like_agentic(userid, db_url))

        async with pool.acquire() as conn:
            fm_order = await fetch_order(conn, feedmer_pk)
            ag_order = await fetch_order(conn, agentic_pk)
            fm_items = await fetch_items(conn, feedmer_pk)
            ag_items = await fetch_items(conn, agentic_pk)

        print(f"feedmer pk={feedmer_pk}   agentic pk={agentic_pk}\n")
        print(f"{'поле orders':<22}{'feedmer':<30}{'agentic':<30}{'':<4}")
        print("-" * 88)
        bad: list[str] = []
        for column in fm_order:
            same = fm_order[column] == ag_order[column]
            if not same and column not in skipped:
                bad.append(column)
            mark = "ok" if same else ("== задано нами" if column in skipped else "РАЗНОЕ")
            print(f"{column:<22}{fmt(fm_order[column]):<30}{fmt(ag_order[column]):<30}{mark}")

        print("\nпозиции (item_name, strdate, userid, cafeid, item_price):")
        print(f"  feedmer : {fm_items}")
        print(f"  agentic : {ag_items}")
        items_same = fm_items == ag_items
        print(f"  совпадают: {items_same}")
        sum_fm = sum(i[4] for i in fm_items)
        sum_ag = sum(i[4] for i in ag_items)
        print(f"  сумма (getOrderSum): feedmer={sum_fm} agentic={sum_ag}")

        print("\nИТОГ:")
        print(f"  расхождения по orders помимо {sorted(skipped)}: {bad or 'нет'}")
        print(f"  позиции идентичны: {items_same}")

        async with pool.acquire() as conn:
            for pk in (feedmer_pk, agentic_pk):
                await conn.execute("DELETE FROM items WHERE pk_order = $1", pk)
                await conn.execute("DELETE FROM orders WHERE pk_orders = $1", pk)
            await conn.execute("DELETE FROM chatids WHERE telegram_chatid = $1", TELEGRAM_ID)
            await conn.execute("DELETE FROM users WHERE userid = $1", userid)
        print("  тестовые строки удалены")
        return 0 if items_same and not bad else 1
    finally:
        await pool.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
