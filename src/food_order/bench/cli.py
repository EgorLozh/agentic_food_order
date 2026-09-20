from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

from food_order.bench.client import BenchTelegramClient
from food_order.bench.report import (
    compare_reports,
    load_report,
    print_run_table,
    save_report,
)
from food_order.bench.runner import run_scenarios
from food_order.bench.scenarios import load_scenarios


def _default_report_path(label: str, *, started_at: datetime | None = None) -> Path:
    stamp = (started_at or datetime.now()).strftime("%Y%m%d_%H%M%S")
    safe_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)
    return Path("reports") / f"{stamp}_{safe_label}.json"


async def _cmd_run(args: argparse.Namespace) -> int:
    _load_dotenv_if_present()
    run_started = datetime.now()

    api_id = args.api_id or _require_int_env("TG_API_ID")
    api_hash = args.api_hash or _require_env("TG_API_HASH")
    session = args.session or os.environ.get("TG_SESSION", "bench.session")
    bot_username = args.bot_username or _require_env("BOT_USERNAME")

    scenarios = load_scenarios(args.scenarios, only_id=args.only_id)
    client = BenchTelegramClient(
        api_id=api_id,
        api_hash=api_hash,
        session=session,
        bot_username=bot_username,
    )

    print(
        "Using a dedicated TEST Telegram account only. "
        "Do not log in with your personal number.",
        flush=True,
    )
    print(
        f"Connecting to Telegram (session={session})…",
        flush=True,
    )

    await client.start()
    print(
        f"Connected. Bot @{bot_username}. Scenarios: {len(scenarios)}",
        flush=True,
    )
    try:
        report = await run_scenarios(
            client=client,
            scenarios=scenarios,
            label=args.label,
            delay_s=args.delay,
            scenario_delay_s=args.scenario_delay,
            default_timeout_s=args.timeout,
            progress=not args.quiet,
        )
    finally:
        await client.disconnect()

    print("\n=== summary ===", flush=True)
    print_run_table(report)

    out = args.output if args.output is not None else _default_report_path(
        args.label, started_at=run_started
    )
    save_report(report, out)
    print(f"report written: {out}", flush=True)
    return 0 if report.ok else 1


async def _cmd_whoami(args: argparse.Namespace) -> int:
    _load_dotenv_if_present()

    api_id = args.api_id or _require_int_env("TG_API_ID")
    api_hash = args.api_hash or _require_env("TG_API_HASH")
    session = args.session or os.environ.get("TG_SESSION", "bench.session")

    client = BenchTelegramClient(
        api_id=api_id,
        api_hash=api_hash,
        session=session,
        bot_username=args.bot_username or os.environ.get("BOT_USERNAME") or "telegram",
    )
    print(
        "Using TEST account session only. Do not log in with your personal number.",
        flush=True,
    )
    await client.start(require_bot=False)
    try:
        me = await client.get_me()
    finally:
        await client.disconnect()

    username = f"@{me.username}" if me.username else "(no username)"
    phone = me.phone or ""
    if len(phone) > 4:
        phone_mask = f"+{'*' * (len(phone) - 4)}{phone[-4:]}"
    elif phone:
        phone_mask = "****"
    else:
        phone_mask = "(hidden)"

    print(f"id={me.id}", flush=True)
    print(f"username={username}", flush=True)
    print(f"phone={phone_mask}", flush=True)
    print(
        f"\nSet ADMIN_TELEGRAM_ID={me.id} in .env (then restart the bot) "
        "so submit scenarios can see «Новый заказ» in this chat.",
        flush=True,
    )
    return 0


def main(argv: list[str] | None = None) -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    parser = argparse.ArgumentParser(
        prog="food-order-bench",
        description="E2E order scenarios against a live Telegram bot (test account only).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Run YAML scenarios via Telegram")
    run_p.add_argument(
        "--scenarios",
        type=Path,
        default=Path("config/scenarios"),
        help="Scenario YAML file or directory",
    )
    run_p.add_argument(
        "--label",
        required=True,
        help="Run label for the report (e.g. openai/gpt-5.1-mini)",
    )
    run_p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="JSON report path (default: reports/YYYYMMDD_HHMMSS_<label>.json)",
    )
    run_p.add_argument("--id", dest="only_id", default=None, help="Run only this scenario id")
    run_p.add_argument(
        "--delay",
        type=float,
        default=1.5,
        help="Pause seconds between turns (default: 1.5)",
    )
    run_p.add_argument(
        "--scenario-delay",
        type=float,
        default=2.0,
        help="Pause seconds between scenarios (default: 2.0)",
    )
    run_p.add_argument(
        "--timeout",
        type=float,
        default=90.0,
        help="Max seconds to wait for each bot reply (default: 90). Not the whole run.",
    )
    run_p.add_argument("--bot-username", default=None, help="Override BOT_USERNAME")
    run_p.add_argument("--api-id", type=int, default=None, help="Override TG_API_ID")
    run_p.add_argument("--api-hash", default=None, help="Override TG_API_HASH")
    run_p.add_argument("--session", default=None, help="Override TG_SESSION path")
    run_p.add_argument(
        "--quiet",
        action="store_true",
        help="Disable live per-turn progress (summary table only)",
    )

    who_p = sub.add_parser(
        "whoami",
        help="Print test account Telegram id for ADMIN_TELEGRAM_ID",
    )
    who_p.add_argument("--api-id", type=int, default=None, help="Override TG_API_ID")
    who_p.add_argument("--api-hash", default=None, help="Override TG_API_HASH")
    who_p.add_argument("--session", default=None, help="Override TG_SESSION path")
    who_p.add_argument("--bot-username", default=None, help="Unused; kept for symmetry")

    cmp_p = sub.add_parser("compare", help="Compare two JSON run reports")
    cmp_p.add_argument("left", type=Path, help="First report JSON")
    cmp_p.add_argument("right", type=Path, help="Second report JSON")

    args = parser.parse_args(argv)

    if args.command == "compare":
        code = compare_reports(load_report(args.left), load_report(args.right))
        raise SystemExit(code)

    if args.command == "run":
        raise SystemExit(asyncio.run(_cmd_run(args)))

    if args.command == "whoami":
        raise SystemExit(asyncio.run(_cmd_whoami(args)))

    raise SystemExit(2)

def _load_dotenv_if_present() -> None:
    """Best-effort load of .env without requiring python-dotenv."""
    path = Path(".env")
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        # Allow spaces around = like in existing .env.example
        if key and key not in os.environ:
            os.environ[key] = value


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Missing {name}. Set it in .env or pass a CLI flag.")
    return value


def _require_int_env(name: str) -> int:
    raw = _require_env(name)
    try:
        return int(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer") from exc


if __name__ == "__main__":
    main()
