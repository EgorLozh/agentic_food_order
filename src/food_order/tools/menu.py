from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from food_order.adapters.base import MenuSource
from food_order.domain.models import (
    MenuItem,
    OrderItem,
    OrderState,
    PendingClarification,
    PickupPoint,
)

_STOPWORDS = frozenset(
    {
        "для",
        "и",
        "с",
        "на",
        "в",
        "из",
        "по",
        "без",
        "или",
        "the",
        "a",
        "of",
    }
)

_PROTEIN_TOKENS = frozenset(
    {
        "куриная",
        "куриный",
        "куриную",
        "куриной",
        "свиная",
        "свиной",
        "свиную",
        "говяжья",
        "говяжий",
        "говяжью",
        "сырная",
        "сырный",
        "сырную",
        "веган",
        "веганская",
    }
)


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def _significant_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for token in _normalize(text).split():
        if token in _STOPWORDS:
            continue
        if re.fullmatch(r"\d+г?", token):
            continue
        if len(token) < 2:
            continue
        tokens.add(token)
    return tokens


def _stem_token(token: str) -> str:
    # Light Russian stemming for food terms: шаурма/шаурму/шаурмы → шаурм
    if len(token) <= 4:
        return token
    for suffix in ("ами", "ями", "ов", "ев", "ам", "ям", "ах", "ях", "ую", "ая", "ое", "ые", "ие", "ый", "ий", "ой", "ая", "у", "ы", "и", "а", "я", "е", "о"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    return token


def _stemmed(tokens: set[str]) -> set[str]:
    return {_stem_token(t) for t in tokens}


def _stems_compatible(a: str, b: str) -> bool:
    if a == b:
        return True
    if abs(len(a) - len(b)) > 2:
        return False
    return SequenceMatcher(None, a, b).ratio() >= 0.85


def _fuzzy_stem_overlap(query_stems: set[str], name_stems: set[str]) -> float:
    if not query_stems:
        return 0.0
    matched = 0
    for qs in query_stems:
        if any(_stems_compatible(qs, ns) for ns in name_stems):
            matched += 1
    return matched / len(query_stems)


def _protein_stems(stems: set[str]) -> set[str]:
    protein = {_stem_token(p) for p in _PROTEIN_TOKENS}
    return {s for s in stems if any(_stems_compatible(s, p) for p in protein)}


def _score_match(query: str, candidate: str, aliases: list[str]) -> float:
    q = _normalize(query)
    if not q:
        return 0.0
    names = [_normalize(candidate), *(_normalize(a) for a in aliases)]
    if q in names:
        return 1.0

    # Exact alias/name containment only as whole token/phrase boundaries —
    # not substring inside longer compound titles like «Кляр для шаурмы».
    for name in names:
        if q == name:
            return 1.0
        if len(q) >= 4 and (name.startswith(q + " ") or name.endswith(" " + q)):
            return 0.9
        if len(name) >= 4 and (q.startswith(name + " ") or q.endswith(" " + name)):
            return 0.9

    q_tokens = _significant_tokens(query)
    q_stems = _stemmed(q_tokens)
    if not q_tokens:
        return 0.0

    best = 0.0
    for name in names:
        name_tokens = _significant_tokens(name)
        name_stems = _stemmed(name_tokens)
        if not name_tokens:
            continue

        stem_overlap = _fuzzy_stem_overlap(q_stems, name_stems)
        token_overlap = len(q_tokens & name_tokens) / max(len(q_tokens), 1)
        overlap = max(stem_overlap, token_overlap)

        q_proteins = _protein_stems(q_stems)
        name_proteins = _protein_stems(name_stems)
        protein_ok = True
        if q_proteins:
            if name_proteins and not any(
                _stems_compatible(qp, np) for qp in q_proteins for np in name_proteins
            ):
                protein_ok = False
                overlap *= 0.35
            elif not any(
                _stems_compatible(qp, ns) for qp in q_proteins for ns in name_stems
            ):
                protein_ok = False
                overlap *= 0.45

        ratio = SequenceMatcher(None, q, name).ratio()
        ratio_score = ratio * 0.85
        if not protein_ok:
            ratio_score = min(ratio_score, 0.32)
        if stem_overlap == 0:
            ratio_score = min(ratio_score, 0.38)

        score = max(overlap, ratio_score)
        if overlap < 0.35 and ratio < 0.72:
            score = min(score, 0.35)
        best = max(best, score)

    return best


class MenuMatcher:
    def __init__(self, menu: list[MenuItem]) -> None:
        self.menu = menu
        self._by_exact_name = {item.name: item for item in menu if item.available}

    def resolve_item(self, name: str, qty: int) -> tuple[OrderItem | None, list[str]]:
        query = name.strip()
        if not query:
            return None, []

        # FeedMer-style exact match (case-sensitive trim)
        exact = self._by_exact_name.get(query)
        if exact:
            return self._to_order_item(exact, qty), []

        scored = [
            (item, _score_match(query, item.name, item.aliases))
            for item in self.menu
            if item.available
        ]
        scored = [(item, score) for item, score in scored if score > 0.4]
        scored.sort(key=lambda x: x[1], reverse=True)

        if not scored:
            return None, []

        best_item, best_score = scored[0]
        if best_score >= 0.85:
            return self._to_order_item(best_item, qty), []
        # Clear winner with decent fuzzy score (typos like «Куринная мини»)
        if best_score >= 0.75 and (len(scored) == 1 or best_score - scored[1][1] >= 0.15):
            return self._to_order_item(best_item, qty), []

        # Drop weak / protein-mismatched noise from clarification list
        floor = max(0.45, best_score * 0.85)
        candidates = [item.name for item, score in scored[:5] if score >= floor][:3]
        return None, candidates

    @staticmethod
    def _to_order_item(item: MenuItem, qty: int) -> OrderItem:
        return OrderItem(
            sku_id=item.sku_id,
            name=item.name,
            qty=qty,
            unit_price=item.price,
        )


def resolve_pickup_point(
    query: str | None,
    points: list[PickupPoint],
) -> tuple[PickupPoint | None, list[PickupPoint]]:
    """Resolve a pickup query.

    Returns ``(point, [])`` on a clear match, ``(None, candidates)`` when several
    points score close enough that the customer must choose, or ``(None, [])``
    when nothing matches.
    """
    if not query:
        return None, []
    query_stripped = query.strip()
    exact = [point for point in points if point.active and point.name == query_stripped]
    if len(exact) == 1:
        return exact[0], []
    if len(exact) > 1:
        return None, exact

    scored = [
        (point, _score_match(query, point.name, point.aliases))
        for point in points
        if point.active
    ]
    scored = [(point, score) for point, score in scored if score >= 0.75]
    if not scored:
        return None, []
    scored.sort(key=lambda x: x[1], reverse=True)
    best_point, best_score = scored[0]
    if len(scored) == 1 or best_score - scored[1][1] >= 0.15:
        return best_point, []
    floor = max(0.75, best_score - 0.15)
    candidates = [point for point, score in scored if score >= floor]
    return None, candidates


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
