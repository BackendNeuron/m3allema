"""Token prices, used to show cost per run and to enforce budgets.

Built-in entries cover current Claude models; add others (or override these)
under ``pricing:`` in ``config.yaml``. A model without a known price reports no
cost, and budgets cannot be enforced for it.
"""

from __future__ import annotations

from collections.abc import Mapping

from m3allema.config.models import Price
from m3allema.domain.messages import Usage

CACHE_READ_RATIO = 0.1
CACHE_WRITE_RATIO = 1.25

BUILTIN_PRICES: dict[str, Price] = {
    "claude-fable-5-1": Price(input=10.0, output=50.0),
    "claude-opus-5-5": Price(input=4.0, output=20.0, cache_read=0.20),
    "claude-opus-5": Price(input=5.0, output=25.0),
    "claude-sonnet-5-5": Price(input=2.0, output=10.0, cache_read=0.20),
    "claude-sonnet-5": Price(input=2.0, output=10.0),
    "claude-haiku-5-5": Price(input=0.10, output=0.50),
}


def cost_of(price: Price, usage: Usage) -> float:
    """Cost of ``usage`` at ``price``, in USD."""
    cache_read = (
        price.cache_read if price.cache_read is not None else price.input * CACHE_READ_RATIO
    )
    cache_write = (
        price.cache_write if price.cache_write is not None else price.input * CACHE_WRITE_RATIO
    )
    total = (
        usage.input_tokens * price.input
        + usage.output_tokens * price.output
        + usage.cache_read_tokens * cache_read
        + usage.cache_write_tokens * cache_write
    )
    return total / 1_000_000


class PriceBook:
    """Looks up prices by model name, preferring configured overrides.

    Args:
        overrides: Prices from ``config.yaml``, keyed by model name.

    """

    def __init__(self, overrides: Mapping[str, Price] | None = None) -> None:
        self._prices = {**BUILTIN_PRICES, **(overrides or {})}

    def cost(self, model: str, usage: Usage) -> float | None:
        """Cost of ``usage`` on ``model`` in USD, or ``None`` when the price is unknown."""
        price = self._prices.get(model)
        return cost_of(price, usage) if price else None
