from __future__ import annotations

import json
from pathlib import Path

import aiosqlite

from food_order.domain.models import OrderState


class SessionStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    async def init(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    telegram_user_id INTEGER PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await db.commit()

    async def get(self, telegram_user_id: int) -> OrderState:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT state_json FROM sessions WHERE telegram_user_id = ?",
                (telegram_user_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return OrderState()
            return OrderState.model_validate(json.loads(row[0]))

    async def save(self, telegram_user_id: int, state: OrderState) -> None:
        payload = json.dumps(state.model_dump(mode="json"), ensure_ascii=False)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO sessions (telegram_user_id, state_json, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(telegram_user_id) DO UPDATE SET
                    state_json = excluded.state_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (telegram_user_id, payload),
            )
            await db.commit()

    async def delete(self, telegram_user_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "DELETE FROM sessions WHERE telegram_user_id = ?",
                (telegram_user_id,),
            )
            await db.commit()
