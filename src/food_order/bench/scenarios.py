from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Turn:
    send: str
    expect_contains: list[str] = field(default_factory=list)
    expect_regex: str | None = None
    timeout_s: float | None = None
    await_replies: int = 1


@dataclass
class Scenario:
    id: str
    description: str = ""
    turns: list[Turn] = field(default_factory=list)
    path: Path | None = None


def _parse_turn(raw: dict[str, Any]) -> Turn:
    if "send" not in raw or not str(raw["send"]).strip():
        raise ValueError("each turn requires a non-empty 'send' field")
    expect = raw.get("expect_contains") or []
    if isinstance(expect, str):
        expect = [expect]
    await_replies = int(raw.get("await_replies") or 1)
    if await_replies < 1:
        raise ValueError("await_replies must be >= 1")
    return Turn(
        send=str(raw["send"]),
        expect_contains=[str(x) for x in expect],
        expect_regex=raw.get("expect_regex"),
        timeout_s=float(raw["timeout_s"]) if raw.get("timeout_s") is not None else None,
        await_replies=await_replies,
    )


def load_scenario(path: Path) -> Scenario:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"scenario root must be a mapping: {path}")
    scenario_id = data.get("id") or path.stem
    turns_raw = data.get("turns") or []
    if not turns_raw:
        raise ValueError(f"scenario has no turns: {path}")
    return Scenario(
        id=str(scenario_id),
        description=str(data.get("description") or ""),
        turns=[_parse_turn(t) for t in turns_raw],
        path=path,
    )


def load_scenarios(path: Path, *, only_id: str | None = None) -> list[Scenario]:
    if path.is_file():
        scenarios = [load_scenario(path)]
    elif path.is_dir():
        files = sorted(
            [*path.glob("*.yaml"), *path.glob("*.yml")],
            key=lambda p: p.name,
        )
        if not files:
            raise FileNotFoundError(f"no YAML scenarios in {path}")
        scenarios = [load_scenario(f) for f in files]
    else:
        raise FileNotFoundError(path)

    if only_id:
        scenarios = [s for s in scenarios if s.id == only_id]
        if not scenarios:
            raise ValueError(f"no scenario with id={only_id!r}")
    return scenarios
