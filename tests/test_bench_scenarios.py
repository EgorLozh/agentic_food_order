from __future__ import annotations

from pathlib import Path

from food_order.bench.cli import _default_report_path
from food_order.bench.report import RunReport, ScenarioResult, TurnResult, compare_reports, report_to_dict
from food_order.bench.runner import check_expectations
from food_order.bench.scenarios import Turn, load_scenarios


def test_load_scenarios_dir() -> None:
    scenarios = load_scenarios(Path("config/scenarios"))
    ids = {s.id for s in scenarios}
    assert "happy_shaurma" in ids
    assert "cancel_flow" in ids
    assert all(s.turns for s in scenarios)
    happy = next(s for s in scenarios if s.id == "happy_shaurma")
    submit = happy.turns[-1]
    assert submit.send == "да"
    assert submit.await_replies == 2
    assert "Новый заказ" in submit.expect_contains


def test_check_expectations() -> None:
    turn = Turn(send="hi", expect_contains=["телефон", "оплат"])
    assert check_expectations("Нужен телефон и способ оплаты", turn) == []
    failed = check_expectations("Что-то другое", turn)
    assert any(f.startswith("missing:") for f in failed)


def test_check_expectations_joined_replies() -> None:
    turn = Turn(
        send="да",
        expect_contains=["Новый заказ", "ORD-", "Молодеж"],
        await_replies=2,
    )
    joined = "Новый заказ ORD-ABCDEF12\nСамовывоз: Молодежная\nЗаказ принят ORD-ABCDEF12"
    assert check_expectations(joined, turn) == []


def test_default_report_path_uses_timestamp() -> None:
    from datetime import datetime

    path = _default_report_path("openai/gpt-5.1-mini", started_at=datetime(2026, 9, 20, 23, 5, 7))
    assert path == Path("reports") / "20260920_230507_openai_gpt-5_1-mini.json"



def test_report_ok_and_compare(tmp_path: Path) -> None:
    report = RunReport(
        label="openai",
        started_at="t0",
        finished_at="t1",
        bot_username="bot",
        scenarios=[
            ScenarioResult(
                id="s1",
                description="",
                ok=True,
                total_ms=1000,
                turns=[
                    TurnResult(
                        index=0,
                        send="/start",
                        reply="ok",
                        latency_ms=100,
                        ok=True,
                    )
                ],
            )
        ],
    )
    payload = report_to_dict(report)
    assert payload["ok"] is True
    assert payload["latency_summary"]["count"] == 1

    other = {
        "label": "ollama",
        "ok": True,
        "scenarios": [
            {
                "id": "s1",
                "turns": [
                    {"index": 0, "latency_ms": 200, "ok": True},
                ],
            }
        ],
        "latency_summary": {"p50": 200, "p95": 200, "mean": 200, "count": 1},
    }
    assert compare_reports(payload, other) == 0
