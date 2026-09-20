from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable
from typing import TypeVar

from food_order.bench.client import BenchTelegramClient
from food_order.bench.report import (
    RunReport,
    ScenarioResult,
    TurnResult,
    utc_now_iso,
)
from food_order.bench.scenarios import Scenario, Turn

T = TypeVar("T")


def check_expectations(reply: str, turn: Turn) -> list[str]:
    failed: list[str] = []
    lowered = reply.casefold()
    for needle in turn.expect_contains:
        if needle.casefold() not in lowered:
            failed.append(f"missing:{needle}")
    if turn.expect_regex:
        if re.search(turn.expect_regex, reply, flags=re.IGNORECASE | re.DOTALL) is None:
            failed.append(f"regex:{turn.expect_regex}")
    return failed


def _log(msg: str) -> None:
    print(msg, flush=True)


async def _await_with_heartbeat(
    awaitable: Awaitable[T],
    *,
    interval_s: float = 5.0,
) -> T:
    task = asyncio.ensure_future(awaitable)
    started = time.perf_counter()
    while True:
        done, _ = await asyncio.wait({task}, timeout=interval_s)
        if done:
            return task.result()
        elapsed = time.perf_counter() - started
        _log(f"     ... waiting for bot reply ({elapsed:.0f}s)")


async def run_scenarios(
    *,
    client: BenchTelegramClient,
    scenarios: list[Scenario],
    label: str,
    delay_s: float = 1.5,
    scenario_delay_s: float = 2.0,
    default_timeout_s: float = 90.0,
    progress: bool = True,
) -> RunReport:
    started_at = utc_now_iso()
    results: list[ScenarioResult] = []
    total = len(scenarios)

    if progress:
        _log(f"Running {total} scenario(s), label={label}, bot=@{client.bot_username}")

    for i, scenario in enumerate(scenarios):
        if i > 0 and scenario_delay_s > 0:
            if progress:
                _log(f"  (pause {scenario_delay_s:.1f}s between scenarios)")
            await asyncio.sleep(scenario_delay_s)
        if progress:
            _log(f"\n==> [{i + 1}/{total}] {scenario.id}")
            if scenario.description:
                _log(f"    {scenario.description}")
        result = await _run_one(
            client=client,
            scenario=scenario,
            delay_s=delay_s,
            default_timeout_s=default_timeout_s,
            progress=progress,
        )
        results.append(result)
        if progress:
            status = "PASS" if result.ok else "FAIL"
            _log(f"    scenario {status} in {result.total_ms / 1000:.1f}s")

    return RunReport(
        label=label,
        started_at=started_at,
        finished_at=utc_now_iso(),
        bot_username=client.bot_username,
        scenarios=results,
    )


async def _run_one(
    *,
    client: BenchTelegramClient,
    scenario: Scenario,
    delay_s: float,
    default_timeout_s: float,
    progress: bool = True,
) -> ScenarioResult:
    turn_results: list[TurnResult] = []
    t_scenario = time.perf_counter()
    # Telethon conversation default per get_response; real waits use per-reply timeout.
    per_reply = max(
        default_timeout_s,
        max((t.timeout_s or default_timeout_s) for t in scenario.turns),
    )

    async with client.conversation(timeout=per_reply) as conv:
        for index, turn in enumerate(scenario.turns):
            if index > 0 and delay_s > 0:
                await asyncio.sleep(delay_s)
            # CLI --timeout is a floor; YAML timeout_s may only raise it for that turn.
            yaml_timeout = turn.timeout_s
            timeout_s = max(
                default_timeout_s,
                yaml_timeout if yaml_timeout is not None else default_timeout_s,
            )
            send_preview = _clip(turn.send, 80)
            if progress:
                extra = (
                    f", await_replies={turn.await_replies}"
                    if turn.await_replies > 1
                    else ""
                )
                _log(
                    f"  -> turn {index}: send {send_preview!r} "
                    f"(per-reply timeout {timeout_s:.0f}s{extra})"
                )
            try:
                replies, latency_ms = await _await_with_heartbeat(
                    client.send_and_wait_replies(
                        conv,
                        turn.send,
                        count=turn.await_replies,
                        timeout_s=timeout_s,
                    )
                )
                if progress and len(replies) > 1:
                    for i, part in enumerate(replies):
                        _log(f"     reply[{i}]: {_clip(part, 120)}")
                joined = "\n".join(replies)
                failed = check_expectations(joined, turn)
                turn_result = TurnResult(
                    index=index,
                    send=turn.send,
                    reply=_clip(joined),
                    latency_ms=latency_ms,
                    ok=not failed,
                    expect_failed=failed,
                )
                turn_results.append(turn_result)
                if progress:
                    _print_turn_progress(turn_result)
            except Exception as exc:  # noqa: BLE001
                turn_result = TurnResult(
                    index=index,
                    send=turn.send,
                    reply="",
                    latency_ms=None,
                    ok=False,
                    error=str(exc),
                )
                turn_results.append(turn_result)
                if progress:
                    _print_turn_progress(turn_result)
                # Stop scenario on hard failure (timeout / disconnect).
                break

    total_ms = (time.perf_counter() - t_scenario) * 1000.0
    return ScenarioResult(
        id=scenario.id,
        description=scenario.description,
        ok=all(t.ok for t in turn_results) and len(turn_results) == len(scenario.turns),
        total_ms=total_ms,
        turns=turn_results,
    )


def _print_turn_progress(turn: TurnResult) -> None:
    status = "PASS" if turn.ok else "FAIL"
    lat = f"{turn.latency_ms:.0f}ms" if turn.latency_ms is not None else "-"
    if turn.error:
        _log(f"     {status} {lat} | error: {turn.error}")
    elif turn.expect_failed:
        _log(
            f"     {status} {lat} | expect: {', '.join(turn.expect_failed)} | "
            f"reply: {_clip(turn.reply, 120)}"
        )
    else:
        _log(f"     {status} {lat} | reply: {_clip(turn.reply, 120)}")


def _clip(text: str, limit: int = 500) -> str:
    text = text.replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"
