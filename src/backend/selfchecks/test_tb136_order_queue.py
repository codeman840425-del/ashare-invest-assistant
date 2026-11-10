# ruff: noqa: S101
"""T-B136c: entry orders must never send a future failure back to an earlier signal."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from retest.t_r58 import sim
from selfchecks import tb136_retest as synthetic

PB = sim.Params(group="B", d=0.01, fill_delay=2)


def queue_stock(*, afternoon_capacity: bool) -> sim.StockInput:
    day = synthetic._flat_day(vol=4700)
    synthetic._set(day, 59, 61, 10.30)
    synthetic._set(day, 61, 240, 10.45)
    # The first signal freezes q=4800; a later signal would freeze q=4700.
    # Only the first order's afternoon prospects differ; every morning bar is identical.
    day[4][198] = 10000
    day[5][198] = day[4][198] * day[3][198]
    day[4][199] = 10000 if afternoon_capacity else 100
    day[5][199] = day[4][199] * day[3][199]
    return synthetic._stock([*synthetic._base(), day, synthetic._flat_day()])


def entry_prefix(stock: sim.StockInput, params: sim.Params, slot: int) -> list[tuple]:
    return [
        (leg.entry_day, leg.trigger_slot, leg.entry_slot, leg.entry_price, leg.q)
        for leg in sim.simulate(stock, params, synthetic._seg(stock))
        if leg.entry_day == 6 and leg.entry_slot <= slot
    ]


def test_tb136_afternoon_capacity_cannot_reselect_morning_slot_64() -> None:
    no_capacity = queue_stock(afternoon_capacity=False)
    with_capacity = queue_stock(afternoon_capacity=True)
    for name in ("o", "h", "l", "c", "v", "a"):
        np.testing.assert_array_equal(
            getattr(no_capacity, name)[:, :199], getattr(with_capacity, name)[:, :199]
        )
    assert entry_prefix(no_capacity, PB, 64) == entry_prefix(with_capacity, PB, 64)
    # A still-pending q=4800 order occupies the morning; q=4700 cannot be selected in hindsight.
    assert entry_prefix(no_capacity, PB, 64) == []
    assert sim.simulate(no_capacity, PB, synthetic._seg(no_capacity)) == []
    later = sim.simulate(with_capacity, PB, synthetic._seg(with_capacity))
    assert len(later) == 1
    assert later[0].trigger_slot == 60
    assert later[0].entry_slot == 200
    assert later[0].q == 4800


@pytest.mark.parametrize("fill_delay", [1, 2])
def test_tb136_execution_cursor_never_rewinds_after_order_failure(fill_delay: int) -> None:
    stock = queue_stock(afternoon_capacity=False)
    params = replace(PB, fill_delay=fill_delay)
    market = sim.Market(stock, params)
    original = market.can_fill
    visited: list[tuple[int, int]] = []

    def traced(d: int, slot: int, q: int, buy: bool) -> bool:
        visited.append((d, slot))
        return original(d, slot, q, buy)

    market.can_fill = traced
    sim.simulate(stock, params, synthetic._seg(stock), market=market)
    assert visited
    assert visited == sorted(visited)


def test_tb136_failed_next_bar_allows_only_later_signal() -> None:
    stock = queue_stock(afternoon_capacity=False)
    counters: dict[str, int] = {}
    legs = sim.simulate(stock, replace(PB, fill_delay=1), synthetic._seg(stock), counters)
    assert counters["entry_abandoned"] == 1
    assert len(legs) == 1
    # The first order fails at slot 61 open; confirmation restarts from that slot's close.
    assert legs[0].trigger_slot == 62
    assert legs[0].entry_slot == 63
    assert legs[0].q == 4700


@pytest.mark.parametrize("cutoff", [63, 64, 119, 198])
def test_tb136_future_suffix_cannot_create_earlier_fills(cutoff: int) -> None:
    stock = queue_stock(afternoon_capacity=True)
    before = entry_prefix(stock, PB, cutoff)
    for array in (stock.o, stock.h, stock.l, stock.c, stock.v, stock.a):
        array[6, cutoff + 1:] = np.nan
    assert entry_prefix(stock, PB, cutoff) == before


@pytest.mark.parametrize("direction", ["sell_first", "buy_first"])
def test_tb136_real_slot_64_fill_survives_afternoon_capacity_change(direction: str) -> None:
    day = synthetic._flat_day()
    synthetic._set(day, 61, 71, 10.30 if direction == "sell_first" else 9.70)
    synthetic._set(day, 71, 240, 10.10 if direction == "sell_first" else 9.90)
    stock = synthetic._stock([*synthetic._base(), day, synthetic._flat_day()])
    legs = sim.simulate(stock, PB, synthetic._seg(stock))
    assert len(legs) == 1
    assert legs[0].entry_slot == 64
    assert legs[0].direction == direction
    before = entry_prefix(stock, PB, 64)
    stock.v[6, 199] = 1
    stock.a[6, 199] = stock.c[6, 199]
    assert entry_prefix(stock, PB, 64) == before


def test_tb136_pending_order_fails_once_at_cutoff_and_is_not_retried() -> None:
    stock = queue_stock(afternoon_capacity=False)
    counters: dict[str, int] = {}
    assert sim.simulate(stock, PB, synthetic._seg(stock), counters) == []
    assert counters["signals"] == 1
    assert counters["entry_abandoned"] == 1


def test_tb136_order_rejects_rewind_and_terminal_reentry() -> None:
    stock = queue_stock(afternoon_capacity=False)
    market = sim.Market(stock, replace(PB, fill_delay=1))
    order = market.entry_order(synthetic._seg(stock)[0], 6, 60, "sell_first")
    with pytest.raises(ValueError, match="advance one bar"):
        market.advance_entry(order, 60)
    assert market.advance_entry(order, 61) == "abandoned"
    stock.v[6, 61] = 10000
    with pytest.raises(ValueError, match="terminal"):
        market.advance_entry(order, 62)
    assert order.leg.entry_slot == 240
    assert np.isnan(order.leg.entry_price)
