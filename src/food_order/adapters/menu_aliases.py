from __future__ import annotations

from pathlib import Path

import yaml

from food_order.domain.models import MenuItem


def load_menu_aliases(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = data.get("aliases", data)
    if not isinstance(raw, dict):
        return {}
    return {
        str(name): [str(a) for a in (aliases or [])]
        for name, aliases in raw.items()
    }


def apply_menu_aliases(
    items: list[MenuItem],
    aliases_by_name: dict[str, list[str]],
) -> list[MenuItem]:
    if not aliases_by_name:
        return items
    result: list[MenuItem] = []
    for item in items:
        extra = aliases_by_name.get(item.name, [])
        if not extra:
            result.append(item)
            continue
        merged = list(dict.fromkeys([*item.aliases, *extra]))
        result.append(item.model_copy(update={"aliases": merged}))
    return result
