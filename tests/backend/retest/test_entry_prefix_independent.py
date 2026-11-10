# ruff: noqa: S101
"""Independent T-B136c counterexamples using full simulate, real features, synthetic bars."""
from datetime import date, timedelta

import numpy as np
import pytest

from retest.t_r58 import sim


def scenario(late_volume: float, *, direction: str = "sell_first", early_fill: bool = False) -> sim.StockInput:
    prices = np.full((8, 240), 10.0)
    volumes = np.full_like(prices, 10000.0)
    if early_fill:
        prices[6, 61:71] = 10.30 if direction == "sell_first" else 9.70
        prices[6, 71:] = 10.10 if direction == "sell_first" else 9.90
    else:
        prices[6, 59:61] = 10.30
        prices[6, 61:] = 10.45
        volumes[6] = 4700
        volumes[6, 198] = 10000
    opens = prices.copy()
    changes = np.flatnonzero(np.diff(prices[6])) + 1
    opens[6, changes] = prices[6, changes - 1]
    volumes[6, 199] = late_volume
    return sim.StockInput(
        "SZ", "000001", [date(2024, 3, 4) + timedelta(days=d) for d in range(8)],
        opens, np.maximum(opens, prices) * 1.001, np.minimum(opens, prices) * .999,
        prices, volumes, volumes * (opens + prices) / 2,
        np.zeros(8, dtype=int), np.zeros(8, dtype=bool), [],
    )


def run(s: sim.StockInput) -> list[sim.Leg]:
    return sim.simulate(s, sim.Params(group="B", d=.01, fill_delay=2),
                        [sim.Segment("fold", s.dates[0], s.dates[-1])])


def prefix(legs: list[sim.Leg], cutoff: int) -> list[tuple]:
    return [(l.entry_day, l.trigger_slot, l.entry_slot, l.entry_price, l.q)
            for l in legs if l.entry_day == 6 and l.entry_slot <= cutoff]


@pytest.mark.parametrize("cutoff", [64, 119, 198])
def test_pending_order_future_capacity_never_creates_earlier_leg(cutoff: int) -> None:
    low, high = scenario(100), scenario(10000)
    for key in "ohlcva":
        np.testing.assert_array_equal(getattr(low, key)[:, :199], getattr(high, key)[:, :199])
    low_legs, high_legs = run(low), run(high)
    assert prefix(low_legs, cutoff) == prefix(high_legs, cutoff) == []
    assert low_legs == []
    assert len(high_legs) == 1
    assert (high_legs[0].trigger_slot, high_legs[0].entry_slot, high_legs[0].q) == (60, 200, 4800)


@pytest.mark.parametrize("direction", ["sell_first", "buy_first"])
def test_existing_early_fill_survives_late_capacity_change(direction: str) -> None:
    before = run(scenario(10000, direction=direction, early_fill=True))
    after = run(scenario(1, direction=direction, early_fill=True))
    assert len(before) == 1 and before[0].entry_slot == 64
    assert before[0].direction == direction
    assert prefix(before, 64) == prefix(after, 64)
