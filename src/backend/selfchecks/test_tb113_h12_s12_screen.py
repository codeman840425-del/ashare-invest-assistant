# ruff: noqa: S101
"""T-B113 / T-A83④ H12/S12: system_only → holdings exits; screen null → 持仓∪自选 only."""

from __future__ import annotations

from decimal import Decimal

import pytest

try:
    from app.signals.screen import screen_membership
except ImportError:  # baseline before T-B113
    screen_membership = None  # type: ignore[assignment]


HOLDINGS_WATCH = {"pool": "持仓 ∪ 自选", "boards": {"main": True}, "security_types": ["stock"]}
HOLDINGS_ONLY = {"pool": "持仓", "boards": {"main": True}, "security_types": ["stock"]}


def test_tb113_h12_system_only_evaluates_holdings_exits_only() -> None:
    if screen_membership is None:
        pytest.fail("app.signals.screen.screen_membership missing (H12/S12 not implemented)")
    assert (
        screen_membership(
            universe=HOLDINGS_ONLY,
            quantity=0,
            on_watchlist=True,
            mount_policy="system_only",
            proposed_action="buy",
        )
        == "outside_universe"
    )
    assert (
        screen_membership(
            universe=HOLDINGS_ONLY,
            quantity=100,
            on_watchlist=False,
            mount_policy="system_only",
            proposed_action="buy",
        )
        == "system_exit_only"
    )
    assert (
        screen_membership(
            universe=HOLDINGS_ONLY,
            quantity=100,
            on_watchlist=False,
            mount_policy="system_only",
            proposed_action="sell",
        )
        is None
    )


def test_tb113_s12_screen_null_pool_is_holdings_union_watchlist_not_full_market() -> None:
    if screen_membership is None:
        pytest.fail("app.signals.screen.screen_membership missing (H12/S12 not implemented)")
    assert (
        screen_membership(
            universe={"pool": None, "boards": {"main": True}, "security_types": ["stock"]},
            quantity=0,
            on_watchlist=False,
            mount_policy="user",
            proposed_action="buy",
        )
        == "universe_pool_not_supported"
    )
    assert (
        screen_membership(
            universe={"pool": "全市场", "boards": {"main": True}, "security_types": ["stock"]},
            quantity=Decimal(0),
            on_watchlist=False,
            mount_policy="user",
            proposed_action="buy",
        )
        == "universe_pool_not_supported"
    )
    assert (
        screen_membership(
            universe=HOLDINGS_WATCH,
            quantity=0,
            on_watchlist=False,
            mount_policy="user",
            proposed_action="buy",
        )
        == "outside_universe"
    )
    assert (
        screen_membership(
            universe=HOLDINGS_WATCH,
            quantity=0,
            on_watchlist=True,
            mount_policy="user",
            proposed_action="buy",
        )
        is None
    )
