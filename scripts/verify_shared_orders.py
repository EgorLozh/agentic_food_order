"""End-to-end check: a confirmed order lands in the shared FeedMer PostgreSQL.

Usage:
    .venv/Scripts/python.exe scripts/verify_shared_orders.py [telegram_user_id] [--direct]

Default path goes through the real agent tool chain
(OrderAgentTools.get_order_summary -> submit_order -> ToolRegistry -> order sink),
i.e. exactly what happens in the bot when the customer confirms the summary.
`--direct` writes through the sink alone.
"""

from __future__ import annotations

import asyncio
import sys

import asyncpg

from food_order.adapters.orders_factory import build_order_sink
from food_order.domain.models import OrderItem, OrderState, PaymentMethod
from food_order.domain.schema_loader import load_order_schema
from food_order.settings import get_settings
from food_order.tools.order_agent_tools import OrderAgentTools
from food_order.tools.registry import ToolRegistry

DEMO_TELEGRAM_ID = 990000001
DEMO_ITEMS = [
    OrderItem(sku_id="demo-1", name="Куриная Стандарт 320г", qty=2, unit_price=300),
    OrderItem(sku_id="demo-2", name="Воткинский лимонад", qty=1, unit_price=110),
]


class _MenuNotNeeded:
    """The submit path never asks for the menu; this keeps the check offline."""

    async def get_menu(self):
        raise RuntimeError("menu is not used on the submit path")

    async def get_pickup_points(self):
        raise RuntimeError("pickup points are not used on the submit path")


async def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    direct = "--direct" in sys.argv
    telegram_user_id = int(args[0]) if args else DEMO_TELEGRAM_ID

    settings = get_settings()
    db_url = settings.orders_database_url or settings.database_url or ""
    if not db_url:
        print("DATABASE_URL / ORDERS_DATABASE_URL is not set")
        return 2

    total = float(sum(item.unit_price * item.qty for item in DEMO_ITEMS))
    state = OrderState(
        items=list(DEMO_ITEMS),
        pickup_point_id="68",
        pickup_point_name="Raketa на Молодежной 107б",
        pickup_time="23:55",
        payment_method=PaymentMethod.CARD,
        phone="+79990001122",
    )

    sink = build_order_sink(settings)
    print(f"ORDER_SINK = {settings.order_sink}   sink = {type(sink).__name__}")

    if direct:
        created = await sink.create_order(
            telegram_user_id=telegram_user_id, state=state, total=total
        )
        order_id = created.order_id
        total_written = created.total
    else:
        tools = OrderAgentTools(
            tools=ToolRegistry(menu_source=_MenuNotNeeded(), order_sink=sink),
            schema=load_order_schema(settings.order_schema_path),
            state=state,
            telegram_user_id=telegram_user_id,
        )
        summary = await tools.get_order_summary({})
        print(
            "get_order_summary ok="
            f"{summary.get('ok')} total={summary.get('summary', {}).get('total')}"
        )
        if not summary.get("ok"):
            print(f"summary failed: {summary}")
            return 1
        result = await tools.submit_order({})
        print(f"submit_order result = {result}")
        if not result.get("ok"):
            return 1
        order_id = str(result["order_id"])
        total_written = result.get("total")

    print(f"заказ записан как pk_orders={order_id}, total={total_written}")

    close = getattr(sink, "close", None)
    if close is not None:
        await close()

    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=1)
    try:
        async with pool.acquire() as conn:
            order = await conn.fetchrow(
                "SELECT * FROM orders WHERE pk_orders = $1", int(order_id)
            )
            items = await conn.fetch(
                "SELECT id, item_name, item_price, cafeid, userid FROM items"
                " WHERE pk_order = $1 ORDER BY id",
                int(order_id),
            )
            chat = await conn.fetchrow(
                "SELECT userid, telegram_chatid, last_messanger FROM chatids"
                " WHERE telegram_chatid = $1",
                telegram_user_id,
            )
        print("\n--- последний заказ в public.orders ---")
        for key in (
            "pk_orders",
            "userid",
            "strdate",
            "deliveryTimeStart",
            "deliveryTimeFinish",
            "cafeId",
            "payway",
            "recipientName",
            "tel",
            "deliverysum",
            "isDelivery",
            "comment",
            "timestamp",
        ):
            print(f"  {key:<20} {order[key]}")
        print("\n--- public.items ---")
        for item in items:
            print(
                f"  id={item['id']} userid={item['userid']} cafeid={item['cafeid']}"
                f" {item['item_name']} — {item['item_price']} ₽"
            )
        print(f"  сумма позиций: {sum(i['item_price'] for i in items)} ₽")
        print("\n--- public.chatids ---")
        print(f"  {dict(chat) if chat else 'no mapping row'}")
    finally:
        await pool.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
