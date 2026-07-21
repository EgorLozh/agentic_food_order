from __future__ import annotations

import re
import unicodedata

from food_order.adapters.base import MenuSource
from food_order.domain.models import (
    MenuItem,
    OrderItem,
    OrderState,
    PendingClarification,
    PickupPoint,
)


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def _score_match(query: str, candidate: str, aliases: list[str]) -> float:
    q = _normalize(query)
    if not q:
        return 0.0
    names = [_normalize(candidate), *(_normalize(a) for a in aliases)]
    if q in names:
        return 1.0
    if any(q in name or name in q for name in names):
        return 0.85
    q_tokens = set(q.split())
    best = 0.0
    for name in names:
        tokens = set(name.split())
        if not tokens:
            continue
        overlap = len(q_tokens & tokens) / max(len(q_tokens), 1)
        best = max(best, overlap)
    return best


class MenuMatcher:
    def __init__(self, menu: list[MenuItem]) -> None:
        self.menu = menu

    def resolve_item(self, name: str, qty: int) -> tuple[OrderItem | None, list[str]]:
        scored = [
            (item, _score_match(name, item.name, item.aliases))
            for item in self.menu
            if item.available
        ]
        scored = [(item, score) for item, score in scored if score > 0.4]
        scored.sort(key=lambda x: x[1], reverse=True)

        if not scored:
            return None, []

        best_item, best_score = scored[0]
        if best_score >= 0.85:
            return (
                OrderItem(
                    sku_id=best_item.sku_id,
                    name=best_item.name,
                    qty=qty,
                    unit_price=best_item.price,
                ),
                [],
            )

        candidates = [item.name for item, _ in scored[:3]]
        return None, candidates


def resolve_pickup_point(
    query: str | None,
    points: list[PickupPoint],
) -> PickupPoint | None:
    if not query:
        return None
    scored = [
        (point, _score_match(query, point.name, point.aliases))
        for point in points
        if point.active
    ]
    scored = [(point, score) for point, score in scored if score >= 0.75]
    if not scored:
        return None
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[0][0]


async def resolve_items_from_names(
    menu_source: MenuSource,
    raw_items: list[tuple[str, int]],
) -> tuple[list[OrderItem], list[PendingClarification]]:
    menu = await menu_source.get_menu()
    matcher = MenuMatcher(menu)
    resolved: list[OrderItem] = []
    clarifications: list[PendingClarification] = []

    for name, qty in raw_items:
        item, candidates = matcher.resolve_item(name, qty)
        if item:
            resolved.append(item)
        else:
            clarifications.append(
                PendingClarification(raw_name=name, candidates=candidates)
            )
    return resolved, clarifications


def apply_clarifications_to_state(
    state: OrderState,
    resolved: list[OrderItem],
) -> None:
    state.pending_clarifications = []
    by_sku = {item.sku_id: item for item in state.items}
    for item in resolved:
        if item.sku_id in by_sku:
            by_sku[item.sku_id].qty += item.qty
        else:
            by_sku[item.sku_id] = item
    state.items = list(by_sku.values())
