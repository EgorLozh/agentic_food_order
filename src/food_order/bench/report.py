from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class TurnResult:
    index: int
    send: str
    reply: str
    latency_ms: float | None
    ok: bool
    error: str | None = None
    expect_failed: list[str] = field(default_factory=list)


@dataclass
class ScenarioResult:
    id: str
    description: str
    ok: bool
    total_ms: float
    turns: list[TurnResult]


@dataclass
class RunReport:
    label: str
    started_at: str
    finished_at: str
    bot_username: str
    scenarios: list[ScenarioResult]

    @property
    def ok(self) -> bool:
        return all(s.ok for s in self.scenarios)

    def latencies_ms(self) -> list[float]:
        return [
            t.latency_ms
            for s in self.scenarios
            for t in s.turns
            if t.latency_ms is not None and t.ok
        ]


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    k = (len(ordered) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(ordered) - 1)
    return ordered[f] + (ordered[c] - ordered[f]) * (k - f)


def summarize_latencies(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "mean": None, "p50": None, "p95": None, "max": None}
    return {
        "count": len(values),
        "mean": statistics.fmean(values),
        "p50": _percentile(values, 50),
        "p95": _percentile(values, 95),
        "max": max(values),
    }


def summarize_quality(scenarios: list[ScenarioResult] | list[dict[str, Any]]) -> dict[str, Any]:
    """Pass/fail counts and rates for scenarios and turns."""
    if scenarios and isinstance(scenarios[0], ScenarioResult):
        scenario_ok = sum(1 for s in scenarios if s.ok)  # type: ignore[union-attr]
        scenario_total = len(scenarios)
        turns = [t for s in scenarios for t in s.turns]  # type: ignore[union-attr]
        turn_ok = sum(1 for t in turns if t.ok)
        turn_total = len(turns)
    else:
        scenario_ok = sum(1 for s in scenarios if s.get("ok"))  # type: ignore[union-attr]
        scenario_total = len(scenarios)
        turns = [t for s in scenarios for t in (s.get("turns") or [])]  # type: ignore[union-attr]
        turn_ok = sum(1 for t in turns if t.get("ok"))
        turn_total = len(turns)

    scenario_fail = scenario_total - scenario_ok
    turn_fail = turn_total - turn_ok
    return {
        "scenarios_passed": scenario_ok,
        "scenarios_failed": scenario_fail,
        "scenarios_total": scenario_total,
        "scenarios_pass_pct": _pct(scenario_ok, scenario_total),
        "scenarios_fail_pct": _pct(scenario_fail, scenario_total),
        "turns_passed": turn_ok,
        "turns_failed": turn_fail,
        "turns_total": turn_total,
        "turns_pass_pct": _pct(turn_ok, turn_total),
        "turns_fail_pct": _pct(turn_fail, turn_total),
    }


def _pct(part: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round(100.0 * part / total, 1)


def report_to_dict(report: RunReport) -> dict[str, Any]:
    payload = asdict(report)
    payload["ok"] = report.ok
    payload["latency_summary"] = summarize_latencies(report.latencies_ms())
    payload["quality_summary"] = summarize_quality(report.scenarios)
    return payload


def save_report(report: RunReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report_to_dict(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_report(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def print_quality_summary(quality: dict[str, Any]) -> None:
    sp = quality.get("scenarios_pass_pct")
    sf = quality.get("scenarios_fail_pct")
    tp = quality.get("turns_pass_pct")
    tf = quality.get("turns_fail_pct")
    print(
        f"quality scenarios: "
        f"{quality.get('scenarios_passed', 0)}/{quality.get('scenarios_total', 0)} PASS "
        f"({_fmt_pct(sp)}) | "
        f"{quality.get('scenarios_failed', 0)} FAIL ({_fmt_pct(sf)})",
        flush=True,
    )
    print(
        f"quality turns:     "
        f"{quality.get('turns_passed', 0)}/{quality.get('turns_total', 0)} PASS "
        f"({_fmt_pct(tp)}) | "
        f"{quality.get('turns_failed', 0)} FAIL ({_fmt_pct(tf)})",
        flush=True,
    )


def print_run_table(report: RunReport) -> None:
    print(
        f"{'scenario':<22} {'turn':>4} {'latency_ms':>12} {'status':<6} expect",
        flush=True,
    )
    print("-" * 72, flush=True)
    for scenario in report.scenarios:
        for turn in scenario.turns:
            status = "PASS" if turn.ok else "FAIL"
            lat = f"{turn.latency_ms:.0f}" if turn.latency_ms is not None else "-"
            note = turn.error or (
                ", ".join(turn.expect_failed) if turn.expect_failed else ""
            )
            print(
                f"{scenario.id:<22} {turn.index:>4} {lat:>12} {status:<6} {note}",
                flush=True,
            )
    summary = summarize_latencies(report.latencies_ms())
    quality = summarize_quality(report.scenarios)
    print("-" * 72, flush=True)
    print_quality_summary(quality)
    print(
        f"label={report.label} ok={report.ok} "
        f"p50={_fmt(summary['p50'])} p95={_fmt(summary['p95'])} "
        f"mean={_fmt(summary['mean'])} n={summary['count']}",
        flush=True,
    )


def print_report_dict(report: dict[str, Any]) -> None:
    """Print table + quality for a saved JSON report."""
    print(
        f"{'scenario':<22} {'turn':>4} {'latency_ms':>12} {'status':<6} expect",
        flush=True,
    )
    print("-" * 72, flush=True)
    for scenario in report.get("scenarios") or []:
        sid = scenario.get("id", "?")
        for turn in scenario.get("turns") or []:
            status = "PASS" if turn.get("ok") else "FAIL"
            lat_v = turn.get("latency_ms")
            lat = f"{float(lat_v):.0f}" if lat_v is not None else "-"
            note = turn.get("error") or ", ".join(turn.get("expect_failed") or [])
            print(
                f"{sid:<22} {int(turn.get('index', 0)):>4} {lat:>12} {status:<6} {note}",
                flush=True,
            )
    quality = report.get("quality_summary") or summarize_quality(report.get("scenarios") or [])
    summary = report.get("latency_summary") or summarize_latencies(_all_latencies(report))
    print("-" * 72, flush=True)
    print_quality_summary(quality)
    print(
        f"label={report.get('label')} ok={report.get('ok')} "
        f"p50={_fmt(summary.get('p50'))} p95={_fmt(summary.get('p95'))} "
        f"mean={_fmt(summary.get('mean'))} n={summary.get('count')}",
        flush=True,
    )


def _fmt(value: float | int | None) -> str:
    if value is None:
        return "-"
    return f"{float(value):.0f}ms"


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.1f}%"


def compare_reports(left: dict[str, Any], right: dict[str, Any]) -> int:
    """Print side-by-side comparison. Returns 0 if both reports ok."""
    left_label = str(left.get("label", "A"))
    right_label = str(right.get("label", "B"))

    left_map = _turn_map(left)
    right_map = _turn_map(right)
    keys = sorted(set(left_map) | set(right_map))

    print(
        f"{'scenario':<22} {'turn':>4} "
        f"{left_label:>14} {right_label:>14} {'delta':>10}"
    )
    print("-" * 72)
    for key in keys:
        sid, idx = key
        a = left_map.get(key)
        b = right_map.get(key)
        a_ms = a.get("latency_ms") if a else None
        b_ms = b.get("latency_ms") if b else None
        delta = ""
        if a_ms is not None and b_ms is not None:
            delta = f"{float(b_ms) - float(a_ms):+.0f}"
        print(
            f"{sid:<22} {idx:>4} "
            f"{_fmt_cell(a_ms):>14} {_fmt_cell(b_ms):>14} {delta:>10}"
        )

    print("-" * 72)
    lq = left.get("quality_summary") or summarize_quality(left.get("scenarios") or [])
    rq = right.get("quality_summary") or summarize_quality(right.get("scenarios") or [])
    ls = left.get("latency_summary") or summarize_latencies(_all_latencies(left))
    rs = right.get("latency_summary") or summarize_latencies(_all_latencies(right))
    print(
        f"{left_label}: scenarios {_fmt_pct(lq.get('scenarios_pass_pct'))} PASS / "
        f"{_fmt_pct(lq.get('scenarios_fail_pct'))} FAIL | "
        f"turns {_fmt_pct(lq.get('turns_pass_pct'))} PASS | "
        f"p50={_fmt(ls.get('p50'))} p95={_fmt(ls.get('p95'))}"
    )
    print(
        f"{right_label}: scenarios {_fmt_pct(rq.get('scenarios_pass_pct'))} PASS / "
        f"{_fmt_pct(rq.get('scenarios_fail_pct'))} FAIL | "
        f"turns {_fmt_pct(rq.get('turns_pass_pct'))} PASS | "
        f"p50={_fmt(rs.get('p50'))} p95={_fmt(rs.get('p95'))}"
    )
    return 0 if left.get("ok") and right.get("ok") else 1


def _fmt_cell(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{float(value):.0f}"


def _turn_map(report: dict[str, Any]) -> dict[tuple[str, int], dict[str, Any]]:
    out: dict[tuple[str, int], dict[str, Any]] = {}
    for scenario in report.get("scenarios") or []:
        sid = scenario["id"]
        for turn in scenario.get("turns") or []:
            out[(sid, int(turn["index"]))] = turn
    return out


def _all_latencies(report: dict[str, Any]) -> list[float]:
    values: list[float] = []
    for scenario in report.get("scenarios") or []:
        for turn in scenario.get("turns") or []:
            lat = turn.get("latency_ms")
            if lat is not None and turn.get("ok"):
                values.append(float(lat))
    return values


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
