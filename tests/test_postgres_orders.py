from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import asyncpg
import pytest

from food_order.adapters.orders_factory import (
    CompositeOrderSink,
    build_order_sink,
)
from food_order.adapters.postgres_orders import (
    PAYWAY_BY_PAYMENT,
    PostgresOrderSink,
    cafe_now,
    order_date,
    payway_for,
)
from food_order.adapters.telegram_orders import TelegramAdminOrderSink
from food_order.domain.models import OrderItem, OrderState, PaymentMethod
from food_order.settings import Settings


class FakeTransaction:
    async def __aenter__(self) -> "FakeTransaction":
        return self

    async def __aexit__(self, *exc_info: Any) -> bool:
        return False


class FakeConnection:
    """Records SQL; the DB is the one that assigns ids (RETURNING pk_orders)."""

    def __init__(
        self,
        *,
        assigned_pk: int = 284840,
        existing_userid: int | None = None,
        cafe_timezone: str | None = None,
    ) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.assigned_pk = assigned_pk
        self.existing_userid = existing_userid
        self.cafe_timezone = cafe_timezone

    def transaction(self) -> FakeTransaction:
        return FakeTransaction()

    async def execute(self, sql: str, *args: Any) -> str:
        self.executed.append((sql, args))
        return "OK"

    async def fetchval(self, sql: str, *args: Any) -> Any:
        self.executed.append((sql, args))
        if "INSERT INTO orders" in sql:
            return self.assigned_pk
        if "SELECT userid FROM chatids" in sql:
            return self.existing_userid
        if "SELECT timezone FROM cafes" in sql:
            return self.cafe_timezone
        if "INSERT INTO users" in sql:
            return 5001
        if "SELECT name FROM users" in sql:
            return "Клиент Telegram 7"
        return None


class NotNullConnection(FakeConnection):
    """Mimics a DB where orders.pk_orders has no sequence (no id assigned)."""

    async def fetchval(self, sql: str, *args: Any) -> Any:
        if "INSERT INTO orders" in sql:
            raise asyncpg.NotNullViolationError('null value in column "pk_orders"')
        return await super().fetchval(sql, *args)


class FakePool:
    def __init__(self, conn: FakeConnection) -> None:
        self.conn = conn

    class _Acquire:
        def __init__(self, conn: FakeConnection) -> None:
            self.conn = conn

        async def __aenter__(self) -> FakeConnection:
            return self.conn

        async def __aexit__(self, *exc_info: Any) -> bool:
            return False

    def acquire(self) -> "FakePool._Acquire":
        return FakePool._Acquire(self.conn)


def make_sink(conn: FakeConnection) -> PostgresOrderSink:
    sink = PostgresOrderSink("postgresql://nobody@localhost/none")
    sink._pool = FakePool(conn)  # type: ignore[assignment]
    return sink


def make_state(**overrides: Any) -> OrderState:
    base = {
        "items": [
            OrderItem(sku_id="1", name="Куриная Стандарт 320г", qty=2, unit_price=300),
            OrderItem(sku_id="2", name="Воткинский лимонад", qty=1, unit_price=110),
        ],
        "pickup_point_id": "68",
        "pickup_point_name": "Raketa на Молодежной 107б",
        "pickup_time": "23:59",
        "payment_method": PaymentMethod.CARD,
        "phone": "+79001234567",
    }
    base.update(overrides)
    return OrderState(**base)


def sql_of(conn: FakeConnection, fragment: str) -> tuple[tuple[Any, ...], ...]:
    return tuple(args for sql, args in conn.executed if fragment in sql)


def test_order_date_rolls_over_when_pickup_time_passed() -> None:
    now = datetime(2026, 10, 4, 20, 30)
    assert order_date("23:00", now) == "04.10.2026"
    assert order_date("10:00", now) == "05.10.2026"
    assert order_date(None, now) == "04.10.2026"


def test_payway_labels_match_feedmer_enum() -> None:
    assert payway_for(PaymentMethod.CASH) == "наличными"
    assert payway_for(PaymentMethod.CARD) == "картой при получении"
    assert set(PAYWAY_BY_PAYMENT.values()) == {"наличными", "картой при получении"}


@pytest.mark.asyncio
async def test_create_order_lets_the_database_assign_ids() -> None:
    conn = FakeConnection(assigned_pk=284840, existing_userid=None)
    sink = make_sink(conn)
    state = make_state()
    created = await sink.create_order(telegram_user_id=7, state=state, total=710)

    assert created.order_id == "284840"  # pk_orders returned by the DB
    assert created.payload["table"] == "public.orders"
    assert created.payload["cafe_id"] == 68

    # no client-side id bookkeeping: neither MAX(...)+1 nor an advisory lock
    assert not any("MAX(" in sql for sql, _ in conn.executed)
    assert not any("pg_advisory" in sql for sql, _ in conn.executed)

    order_args = sql_of(conn, "INSERT INTO orders")[0]
    assert "pk_orders" not in order_args
    assert order_args[0] == 5001  # userid created for telegram 7
    assert order_args[1] == "04.10.2026"  # strdate
    assert order_args[2] == 0 and order_args[3] == 0  # deliverysum / printedDeliverySum
    assert order_args[6] == "23:59"  # deliveryTimeStart
    assert order_args[7] is None  # deliveryTimeFinish: самовывоз
    assert order_args[8] == 68  # cafeId
    assert order_args[9] == "картой при получении"  # payway
    assert order_args[10] == "Клиент Telegram 7"  # recipientName
    assert order_args[11] == "+79001234567"  # tel
    assert order_args[13] == "Заказ агентного бота (agentic)"
    assert order_args[14] is False  # isDelivery

    item_args = sql_of(conn, "INSERT INTO items")
    assert len(item_args) == 3  # one row per unit, like FeedMer's cart
    assert item_args[0] == (
        "Куриная Стандарт 320г",
        "04.10.2026",
        5001,
        68,
        300,  # unit price, not qty × price
        284840,  # pk_order links the line to the order
    )
    assert item_args[1] == item_args[0]  # second unit of the same dish
    assert item_args[2][0] == "Воткинский лимонад" and item_args[2][4] == 110
    assert sum(args[4] for args in item_args) == 710  # = FeedMer getOrderSum(pk_order)

    # the telegram user is registered once, in the same shared DB
    assert sql_of(conn, "INSERT INTO users")[0][0] == "Клиент Telegram 7"
    assert sql_of(conn, "INSERT INTO chatids")[0] == (5001, 7)


@pytest.mark.asyncio
async def test_create_order_reuses_existing_user_and_caches_it() -> None:
    conn = FakeConnection(existing_userid=6432)
    sink = make_sink(conn)
    state = make_state(payment_method=PaymentMethod.CASH)

    first = await sink.create_order(telegram_user_id=7, state=state, total=710)
    second = await sink.create_order(telegram_user_id=7, state=state, total=710)

    assert first.order_id == "284840" and second.order_id == "284840"
    assert not sql_of(conn, "INSERT INTO users")
    assert len(sql_of(conn, "SELECT userid FROM chatids")) == 1  # second call served from cache
    assert sql_of(conn, "INSERT INTO orders")[0][9] == "наличными"


@pytest.mark.asyncio
async def test_missing_sequence_raises_actionable_error() -> None:
    sink = make_sink(NotNullConnection())
    with pytest.raises(RuntimeError, match="Общая БД не выдаёт id"):
        await sink.create_order(telegram_user_id=7, state=make_state(), total=710)


def test_cafe_now_handles_zones_and_garbage() -> None:
    assert cafe_now(None) is None
    assert cafe_now("Not/AZone") is None  # unknown zone → caller falls back to local time
    aware = cafe_now("Europe/Samara")
    if aware is None:
        pytest.skip("IANA tz database is not installed (pip install tzdata)")
    assert aware.utcoffset() is not None and aware.utcoffset().total_seconds() == 4 * 3600


@pytest.mark.asyncio
async def test_strdate_follows_cafe_timezone_and_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConnection(existing_userid=6432, cafe_timezone="Europe/Samara")
    sink = make_sink(conn)
    monkeypatch.setattr(
        "food_order.adapters.postgres_orders.cafe_now",
        lambda tz: datetime(2026, 10, 4, 23, 59) if tz else None,
    )
    state = make_state(pickup_time="23:58")
    await sink.create_order(telegram_user_id=7, state=state, total=710)
    await sink.create_order(telegram_user_id=7, state=state, total=710)

    assert sql_of(conn, "SELECT timezone FROM cafes")[0] == (68,)
    assert len(sql_of(conn, "SELECT timezone FROM cafes")) == 1  # read once per cafe
    assert [args[1] for args in sql_of(conn, "INSERT INTO orders")] == [
        "05.10.2026",
        "05.10.2026",
    ]  # 23:58 в таймзоне кафе уже прошло → заказ на завтра, как в saveOrder каркаса


def test_cafe_id_falls_back_to_default_and_raises_without_it() -> None:
    sink = PostgresOrderSink("postgresql://nobody@localhost/none")
    state = make_state(pickup_point_id="центр")
    with pytest.raises(RuntimeError):
        sink._cafe_id(state)

    sink.default_cafe_id = 68
    assert sink._cafe_id(state) == 68


def make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "BOT_TOKEN": "test-token",
        "LLM_PROVIDER": "ollama",
        "ADMIN_TELEGRAM_ID": 42,
        "DATABASE_URL": "postgresql://test_user:pw@localhost:5432/testing",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


def test_build_order_sink_defaults_to_telegram() -> None:
    class FakeBot:
        pass

    sink = build_order_sink(make_settings(), bot=FakeBot())
    assert isinstance(sink, TelegramAdminOrderSink)


def test_build_order_sink_postgres_uses_shared_db() -> None:
    sink = build_order_sink(make_settings(ORDER_SINK="postgres"))
    assert isinstance(sink, PostgresOrderSink)
    assert sink.database_url == "postgresql://test_user:pw@localhost:5432/testing"


def test_build_order_sink_prefers_explicit_orders_database_url() -> None:
    sink = build_order_sink(
        make_settings(ORDER_SINK="postgres", ORDERS_DATABASE_URL="postgresql://orders/db")
    )
    assert isinstance(sink, PostgresOrderSink)
    assert sink.database_url == "postgresql://orders/db"


def test_build_order_sink_postgres_needs_a_database() -> None:
    settings = Settings(
        _env_file=None, BOT_TOKEN="t", LLM_PROVIDER="ollama", ORDER_SINK="postgres"
    )
    assert settings.database_url is None
    with pytest.raises(RuntimeError):
        build_order_sink(settings)


def test_build_order_sink_telegram_requires_admin_id() -> None:
    settings = Settings(_env_file=None, BOT_TOKEN="t", LLM_PROVIDER="ollama")

    class FakeBot:
        pass

    with pytest.raises(RuntimeError):
        build_order_sink(settings, bot=FakeBot())


def test_build_order_sink_both_writes_db_then_notifies_admin() -> None:
    class FakeBot:
        pass

    sink = build_order_sink(make_settings(ORDER_SINK="both", ADMIN_TELEGRAM_ID=42), bot=FakeBot())
    assert isinstance(sink, CompositeOrderSink)
    assert isinstance(sink.primary, PostgresOrderSink)
    assert len(sink.notifications) == 1


@pytest.mark.asyncio
async def test_composite_order_sink_keeps_order_when_notify_fails() -> None:
    class RecordingSink:
        def __init__(self, *, fail: bool = False) -> None:
            self.fail = fail
            self.calls = 0

        async def create_order(self, *, telegram_user_id, state, total):  # type: ignore[no-untyped-def]
            self.calls += 1
            if self.fail:
                raise RuntimeError("telegram is down")
            from food_order.domain.models import CreatedOrder

            return CreatedOrder(order_id="42", total=total, payload={})

    primary = RecordingSink()
    broken = RecordingSink(fail=True)
    sink = CompositeOrderSink(primary, [broken])
    created = await sink.create_order(telegram_user_id=7, state=make_state(), total=710)
    assert created.order_id == "42"
    assert primary.calls == 1 and broken.calls == 1


@pytest.mark.asyncio
async def test_shared_db_integration_when_database_available() -> None:
    """Real insert into the shared FeedMer DB; opt in with FOOD_ORDER_TEST_DB_URL."""
    url = os.environ.get("FOOD_ORDER_TEST_DB_URL")
    if not url:
        pytest.skip("FOOD_ORDER_TEST_DB_URL is not set")

    try:
        pool = await asyncpg.create_pool(url, min_size=1, max_size=1)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"shared DB unreachable: {exc}")

    sink = PostgresOrderSink(url, source_tag="pytest")
    try:
        state = make_state(pickup_time="23:58")
        created = await sink.create_order(telegram_user_id=999_000_111, state=state, total=710)
        pk = int(created.order_id)
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM orders WHERE pk_orders = $1", pk)
            items = await conn.fetch(
                "SELECT * FROM items WHERE pk_order = $1 ORDER BY id", pk
            )
        assert row is not None
        assert row["cafeId"] == 68 and row["payway"] == "картой при получении"
        assert items and all(i["id"] is not None for i in items)  # items.id from identity
        assert [i["item_name"] for i in items] == [
            "Куриная Стандарт 320г",
            "Куриная Стандарт 320г",
            "Воткинский лимонад",
        ]  # one row per unit, as FeedMer writes it
        assert sum(i["item_price"] for i in items) == 710
        # cleanup: the shared test DB stays clean
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM items WHERE pk_order = $1", pk)
            await conn.execute("DELETE FROM orders WHERE pk_orders = $1", pk)
            await conn.execute("DELETE FROM chatids WHERE telegram_chatid = $1", 999_000_111)
            await conn.execute("DELETE FROM users WHERE userid = $1", created.payload["userid"])
    finally:
        await sink.close()
        await pool.close()
