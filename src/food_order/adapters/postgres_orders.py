from __future__ import annotations

from datetime import datetime, timedelta

import asyncpg
import structlog

from food_order.adapters.base import OrderSink
from food_order.domain.models import CreatedOrder, OrderState, PaymentMethod

logger = structlog.get_logger(__name__)

# `public.orders.payway` is the FeedMer enum `payway_type`; its labels are the
# customer-facing payment strings.
PAYWAY_BY_PAYMENT: dict[PaymentMethod, str] = {
    PaymentMethod.CASH: "наличными",
    PaymentMethod.CARD: "картой при получении",
}

_USERID_BY_TELEGRAM = """
SELECT userid FROM chatids
WHERE telegram_chatid = $1 AND userid IS NOT NULL
ORDER BY userid DESC LIMIT 1
"""

_INSERT_USER = """
INSERT INTO users (name, step, tel)
VALUES ($1, '0', $2)
RETURNING userid
"""

_INSERT_CHATID = """
INSERT INTO chatids (userid, telegram_chatid, last_messanger)
VALUES ($1, $2, 'telegram')
"""

_UPDATE_USER_TEL = """
UPDATE users SET tel = $1
WHERE userid = $2 AND (tel IS NULL OR tel = '')
"""

_SELECT_USER_NAME = "SELECT name FROM users WHERE userid = $1"

# FeedMer formats orders.strdate in the cafe timezone (scenarios.js saveOrder
# uses cafeInfo.timezone via moment.tz); read it once per cafe.
_SELECT_CAFE_TIMEZONE = 'SELECT timezone FROM cafes WHERE "cafeId" = $1'

# `pk_orders` and `items.id` are assigned by the database, exactly as the
# framework does it (DBlib.js saveOrder/addItem): FeedMer migrations declare
# `orders.pk_orders` with a sequence-backed default and `items.id` as
# GENERATED ALWAYS AS IDENTITY, and both tables are inserted without ids.
_INSERT_ORDER = """
INSERT INTO orders (
    userid, strdate, deliverysum, "printedDeliverySum",
    formaladdr, addr, "deliveryTimeStart", "deliveryTimeFinish", "cafeId",
    payway, "recipientName", tel, "ASAP", comment, "isDelivery"
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9,
    $10::payway_type, $11, $12, $13, $14, $15
)
RETURNING pk_orders
"""

_INSERT_ITEM = """
INSERT INTO items (item_name, strdate, userid, cafeid, item_price, pk_order)
VALUES ($1, $2, $3, $4, $5, $6)
"""

_MISSING_ID_HINT = (
    "Общая БД не выдаёт id: у orders.pk_orders нет последовательности, либо у items.id "
    "нет identity — прогоните миграции FeedMer (раздел «восстановление схемы orders/items»)"
)


def order_date(pickup_time: str | None, now: datetime | None = None) -> str:
    """FeedMer `orders.strdate` (DD.MM.YYYY): a pickup time already passed means tomorrow."""
    moment = now or datetime.now()
    if pickup_time and len(pickup_time) == 5 and pickup_time <= moment.strftime("%H:%M"):
        moment = moment + timedelta(days=1)
    return moment.strftime("%d.%m.%Y")


def cafe_now(timezone_name: str | None) -> datetime | None:
    """Now in the cafe timezone, as FeedMer does with `cafeInfo.timezone`.

    Returns None when the cafe has no timezone or the IANA database is missing
    (Windows needs the `tzdata` package), so the caller falls back to local time.
    """
    if not timezone_name:
        return None
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo(timezone_name))
    except Exception:  # noqa: BLE001 - unknown zone or missing tzdata
        logger.warning("cafe_timezone_unavailable", timezone=timezone_name)
        return None


def payway_for(payment: PaymentMethod | None) -> str | None:
    return PAYWAY_BY_PAYMENT.get(payment) if payment else None


class PostgresOrderSink(OrderSink):
    """Write confirmed orders into the shared FeedMer PostgreSQL.

    Rows land in `public.orders` + `public.items` - the same tables the FeedMer
    panel, courier routes and reports read - so one shared DB holds the orders
    of every bot instead of each bot notifying its own Telegram admin.
    """

    def __init__(
        self,
        database_url: str,
        *,
        source_tag: str = "agentic",
        order_comment: str | None = None,
        default_cafe_id: int | None = None,
    ) -> None:
        self.database_url = database_url
        self.source_tag = source_tag
        self.order_comment = order_comment or f"Заказ агентного бота ({source_tag})"
        self.default_cafe_id = default_cafe_id
        self._pool: asyncpg.Pool | None = None
        self._user_cache: dict[int, tuple[int, str]] = {}
        self._cafe_tz: dict[int, str | None] = {}

    async def _get_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(self.database_url, min_size=1, max_size=4)
        return self._pool

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    def _cafe_id(self, state: OrderState) -> int:
        raw = (state.pickup_point_id or "").strip()
        if raw.isdigit():
            return int(raw)
        if self.default_cafe_id is not None:
            return self.default_cafe_id
        raise RuntimeError(
            "Order has no numeric cafeId (pickup_point_id="
            f"{state.pickup_point_id!r}): set ORDERS_DEFAULT_CAFE_ID to persist it"
        )

    async def _resolve_user(
        self, conn: asyncpg.Connection, telegram_user_id: int, tel: str | None
    ) -> tuple[int, str]:
        """Look up (or register) the shared-DB user behind a Telegram account.

        The caller caches the result only after the transaction commits, so a
        rolled-back attempt never leaves a stale userid behind.
        """
        cached = self._user_cache.get(telegram_user_id)
        if cached is not None:
            if tel:
                await conn.execute(_UPDATE_USER_TEL, tel, cached[0])
            return cached

        userid = await conn.fetchval(_USERID_BY_TELEGRAM, telegram_user_id)
        if userid is None:
            name = f"Клиент Telegram {telegram_user_id}"
            userid = await conn.fetchval(_INSERT_USER, name, tel)
            await conn.execute(_INSERT_CHATID, userid, telegram_user_id)
            logger.info(
                "shared_db_user_created", userid=userid, telegram_user_id=telegram_user_id
            )
            return userid, name

        if tel:
            await conn.execute(_UPDATE_USER_TEL, tel, userid)
        name = await conn.fetchval(_SELECT_USER_NAME, userid) or (
            f"Клиент Telegram {telegram_user_id}"
        )
        return userid, name

    async def _cafe_timezone(self, conn: asyncpg.Connection, cafe_id: int) -> str | None:
        if cafe_id not in self._cafe_tz:
            self._cafe_tz[cafe_id] = await conn.fetchval(_SELECT_CAFE_TIMEZONE, cafe_id)
        return self._cafe_tz[cafe_id]

    async def create_order(
        self,
        *,
        telegram_user_id: int,
        state: OrderState,
        total: float,
    ) -> CreatedOrder:
        pool = await self._get_pool()
        cafe_id = self._cafe_id(state)
        payway = payway_for(state.payment_method)

        try:
            async with pool.acquire() as conn:
                # read before the transaction: a missing `cafes` table must not abort it
                tz_name = await self._cafe_timezone(conn, cafe_id)
                strdate = order_date(state.pickup_time, cafe_now(tz_name))
                async with conn.transaction():
                    userid, recipient = await self._resolve_user(
                        conn, telegram_user_id, state.phone
                    )
                    pk_order = await conn.fetchval(
                        _INSERT_ORDER,
                        userid,
                        strdate,
                        0,  # deliverysum: self-pickup, no delivery fee
                        0,  # printedDeliverySum
                        None,  # formaladdr
                        None,  # addr
                        state.pickup_time,
                        None,  # deliveryTimeFinish
                        cafe_id,
                        payway,
                        recipient,
                        state.phone,
                        False,  # ASAP
                        self.order_comment,
                        False,  # isDelivery
                    )
                    # FeedMer stores one row per unit at the unit price
                    # (scenarios.js addItemsFromAi / addItem; the cart counts
                    # rows in collectItemsForUser, getOrderSum = SUM(item_price)).
                    for item in state.items:
                        unit_price = int(round(item.unit_price))
                        for _ in range(item.qty):
                            await conn.execute(
                                _INSERT_ITEM,
                                item.name,
                                strdate,
                                userid,
                                cafe_id,
                                unit_price,
                                pk_order,
                            )
        except asyncpg.NotNullViolationError as exc:
            raise RuntimeError(_MISSING_ID_HINT) from exc

        self._user_cache[telegram_user_id] = (userid, recipient)
        payload = {
            "order_id": str(pk_order),
            "db": "feedmer",
            "table": "public.orders",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "telegram_user_id": telegram_user_id,
            "userid": userid,
            "cafe_id": cafe_id,
            "strdate": strdate,
            "pickup_time": state.pickup_time,
            "payment": state.payment_method.value if state.payment_method else "",
            "payway": payway,
            "phone": state.phone,
            "total": total,
            "items": [item.model_dump(mode="json") for item in state.items],
            "status": "new",
        }
        logger.info(
            "order_persisted",
            order_id=str(pk_order),
            userid=userid,
            cafe_id=cafe_id,
            items=len(state.items),
            total=total,
        )
        return CreatedOrder(order_id=str(pk_order), total=total, payload=payload)
