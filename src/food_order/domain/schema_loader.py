from __future__ import annotations

from pathlib import Path

import yaml

from food_order.domain.models import OrderSchema


def load_order_schema(path: Path) -> OrderSchema:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return OrderSchema.model_validate(data)
