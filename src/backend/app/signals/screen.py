"""Screen / universe membership for strategy evaluation (T-A83 H12/S12).

v1 does **not** scan the full market: only ``持仓`` or ``持仓 ∪ 自选``.
``system_only`` cards only emit exit actions (reduce/sell) on holdings.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

Diagnostic = Literal[
    "universe_not_defined_or_supported",
    "universe_pool_not_supported",
    "outside_universe",
    "system_exit_only",
]

_ALLOWED_POOLS = frozenset({"持仓", "持仓 ∪ 自选"})
_EXIT_ACTIONS = frozenset({"reduce", "sell"})


def screen_membership(
    *,
    universe: dict[str, object] | None,
    quantity: Decimal | int | float,
    on_watchlist: bool,
    mount_policy: str = "user",
    proposed_action: str,
) -> Diagnostic | None:
    """Return a diagnostic if the name is excluded from this screen; else None.

    ``screen: null`` / missing full-market pool → ``universe_pool_not_supported``
    (never admit a whole-market scan). ``system_only`` + non-exit → ``system_exit_only``.
    """
    if not universe or set(universe) - {"boards", "pool", "security_types"}:
        return "universe_not_defined_or_supported"
    pool = universe.get("pool")
    if pool not in _ALLOWED_POOLS:
        return "universe_pool_not_supported"
    qty = Decimal(quantity)
    if qty <= 0 and (pool == "持仓" or not on_watchlist):
        return "outside_universe"
    if mount_policy == "system_only" and proposed_action not in _EXIT_ACTIONS:
        return "system_exit_only"
    return None
