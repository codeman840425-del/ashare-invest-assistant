# ruff: noqa: S101
"""T-R58d quantity precision and prefix invariance, entirely synthetic."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from retest.t_r58 import features, sim


def stock(day: date) -> sim.StockInput:
    arrays = [np.full((1, 240), value) for value in (10.0, 10.1, 9.9, 10.0, 100.0, 1990.0)]
    return sim.StockInput("SZ", "000001", [day], *arrays, np.array([sim.OK]), np.array([False]), [])


@pytest.mark.parametrize(
    ("day", "expected"),
    [(date(2026, 4, 12), False), (date(2026, 4, 13), True), (date(2026, 8, 7), True)],
)
def test_tb136_market_quantity_precision_boundary(day: date, expected: bool) -> None:
    market = sim.Market(stock(day), sim.Params(group="B", d=0.01))
    assert bool(market.days[0]["valid"][0]) is expected


def test_tb136_zero_volume_still_requires_zero_turnover() -> None:
    values = [np.array([x]) for x in (10.0, 10.1, 9.9, 10.0, 0.0, 1.0)]
    assert not features.bar_ok(*values, volume_quantum=100)[0]


def test_tb136_quantity_tolerance_does_not_expand_past_one_step() -> None:
    values = [np.array([x]) for x in (10.0, 10.1, 9.9, 10.0, 100.0, 2100.0)]
    assert not features.bar_ok(*values, volume_quantum=100)[0]


def test_tb136_late_bad_bar_cannot_revoke_prefix_features() -> None:
    source = stock(date(2026, 4, 13))
    original = sim.Market(source, sim.Params(group="B", d=0.01))
    source.a[0, 200] = 10000.0
    changed = sim.Market(source, sim.Params(group="B", d=0.01))
    for key in ("valid", "vwap", "dev", "sigma", "cumvol", "cumamt"):
        np.testing.assert_allclose(
            original.days[0][key][:200], changed.days[0][key][:200], equal_nan=True
        )
    assert not changed.days[0]["valid"][200]
