from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.custom.conversation import Conversation
from telethon.tl.types import User

# Bot replies that mean "still busy" — wait for the next message.
_BUSY_MARKERS = (
    "подождите, обрабатываю",
    "обрабатываю предыдущее",
)


class BenchTelegramClient:
    """User-account client that chats with the food-order bot."""

    def __init__(
        self,
        *,
        api_id: int,
        api_hash: str,
        session: str,
        bot_username: str,
    ) -> None:
        self._client = TelegramClient(session, api_id, api_hash)
        self.bot_username = bot_username.lstrip("@")
        self._bot: User | None = None

    async def start(self, *, require_bot: bool = True) -> None:
        await self._client.start()
        if not require_bot:
            return
        entity = await self._client.get_entity(self.bot_username)
        if not isinstance(entity, User) or not entity.bot:
            raise RuntimeError(f"{self.bot_username!r} is not a Telegram bot")
        self._bot = entity

    async def disconnect(self) -> None:
        await self._client.disconnect()

    async def get_me(self) -> User:
        me = await self._client.get_me()
        if not isinstance(me, User):
            raise RuntimeError("expected a user account session")
        return me

    @property
    def bot(self) -> User:
        if self._bot is None:
            raise RuntimeError("client not started")
        return self._bot

    @asynccontextmanager
    async def conversation(self, *, timeout: float) -> AsyncIterator[Conversation]:
        async with self._client.conversation(
            self.bot,
            timeout=timeout,
            exclusive=True,
        ) as conv:
            yield conv

    async def send_and_wait_reply(
        self,
        conv: Conversation,
        text: str,
        *,
        timeout_s: float,
    ) -> tuple[str, float]:
        """Send text and wait for one bot reply. Returns (reply, latency_ms)."""
        replies, latency_ms = await self.send_and_wait_replies(
            conv,
            text,
            count=1,
            timeout_s=timeout_s,
        )
        return replies[0], latency_ms

    async def send_and_wait_replies(
        self,
        conv: Conversation,
        text: str,
        *,
        count: int,
        timeout_s: float,
    ) -> tuple[list[str], float]:
        """Send text and collect ``count`` non-busy bot replies.

        ``timeout_s`` is the max wait **per reply** (not for the whole turn/run).
        ``latency_ms`` is measured until the first useful reply.
        """
        if count < 1:
            raise ValueError("count must be >= 1")
        t0 = time.perf_counter()
        await self._send_with_flood_retry(conv, text)

        replies: list[str] = []
        first_latency_ms: float | None = None
        while len(replies) < count:
            reply = await self._wait_one_reply(conv, timeout_s=timeout_s)
            if first_latency_ms is None:
                first_latency_ms = (time.perf_counter() - t0) * 1000.0
            replies.append(reply)
        return replies, first_latency_ms if first_latency_ms is not None else 0.0

    async def _wait_one_reply(self, conv: Conversation, *, timeout_s: float) -> str:
        """Wait for a single non-busy bot message; ``timeout_s`` applies to this wait only."""
        deadline = time.perf_counter() + timeout_s
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                raise TimeoutError(f"no bot reply within {timeout_s:.0f}s")
            try:
                response = await asyncio.wait_for(conv.get_response(), timeout=remaining)
            except TimeoutError as exc:
                raise TimeoutError(f"no bot reply within {timeout_s:.0f}s") from exc
            reply = (response.message or response.raw_text or "").strip()
            if self._is_busy_notice(reply):
                continue
            return reply

    async def _send_with_flood_retry(self, conv: Conversation, text: str) -> None:
        try:
            await conv.send_message(text)
        except FloodWaitError as exc:
            await asyncio.sleep(exc.seconds + 1)
            await conv.send_message(text)

    @staticmethod
    def _is_busy_notice(text: str) -> bool:
        lowered = text.casefold()
        return any(marker in lowered for marker in _BUSY_MARKERS)
