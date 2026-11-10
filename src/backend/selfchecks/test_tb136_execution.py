# ruff: noqa: S101
"""T-R58d cutoff, latency, and execution-prefix checks on synthetic bars only."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import numpy as np
import pytest

from retest.t_r58 import sim, stats
from selfchecks import tb136_retest as synthetic

PB = sim.Params(group="B", d=0.01)


def ending_stock(day: list[np.ndarray]) -> sim.StockInput:
    stock = synthetic._stock([*synthetic._base(7), day])
    stock.dates = [
        date(2026, 10, 30),
        date(2026, 11, 2),
        date(2026, 11, 3),
        date(2026, 11, 4),
        date(2026, 11, 5),
        date(2026, 11, 6),
        date(2026, 11, 9),
        date(2026, 11, 10),
    ]
    return stock


def test_tb136_research_cutoff_allows_new_leg() -> None:
    stock = ending_stock(synthetic._sell_day())
    segment = sim.Segment("holdout", stock.dates[0], stock.dates[-1], embargo=False)
    legs = sim.simulate(stock, PB, [segment])
    assert len(legs) == 1
    assert stock.dates[legs[0].entry_day] == date(2026, 11, 10)
    assert legs[0].exit_day == legs[0].entry_day


def test_tb136_cutoff_unclosed_reason_is_end_not_embargo() -> None:
    stock = ending_stock(synthetic._buy_lock_day())
    segment = sim.Segment("holdout", stock.dates[0], stock.dates[-1], embargo=False)
    legs = sim.simulate(stock, PB, [segment])
    assert len(legs) == 1
    assert legs[0].reason == "unvaluable_end"
    assert legs[0].pnl_bp == 0
    assert legs[0].cons_pnl_bp < 0


def test_tb136_fold_embargo_still_forbids_entry() -> None:
    stock = ending_stock(synthetic._sell_day())
    segment = sim.Segment("fold5", stock.dates[0], stock.dates[-1])
    assert sim.simulate(stock, PB, [segment]) == []


def test_tb136_cross_day_holding_bars_are_actual_fill_span() -> None:
    stock = synthetic._lock_stock(sim.OK)
    leg = sim.simulate(stock, PB, synthetic._seg(stock))[0]
    assert leg.exit_day is not None
    assert leg.exit_slot is not None
    assert leg.hold_bars == (leg.exit_day - leg.entry_day) * 240 + leg.exit_slot - leg.entry_slot
    assert leg.hold_bars > 0


def test_tb136_future_invalid_day_cannot_revoke_deferred_open_fill() -> None:
    stock = synthetic._lock_stock(sim.OK)
    stock.a[7, :] = 1e12
    leg = sim.simulate(stock, PB, synthetic._seg(stock))[0]
    assert leg.exit_day == 7
    assert leg.exit_slot == 0
    assert leg.reason == "deferred"
    assert leg.exec_anomaly


def test_tb136_excluded_deferral_does_not_depend_on_future_bar_quality() -> None:
    stock = synthetic._lock_stock(sim.EXCLUDED)
    stock.a[7, :] = 1e12
    leg = sim.simulate(stock, PB, synthetic._seg(stock))[0]
    assert leg.reason == "unvaluable_excluded"
    assert leg.exit_day is None


def test_tb136_latency_second_tradable_bar_not_second_grid_slot() -> None:
    stock = synthetic._stock([*synthetic._base(), synthetic._sell_day(), synthetic._flat_day()])
    base = sim.simulate(stock, PB, synthetic._seg(stock))[0]
    stock.v[6, base.trigger_slot + 1] = 0
    stock.a[6, base.trigger_slot + 1] = 0
    leg = sim.simulate(stock, replace(PB, fill_delay=2), synthetic._seg(stock))[0]
    assert leg.trigger_slot == base.trigger_slot
    assert leg.entry_slot == base.trigger_slot + 4


def test_tb136_latency_applies_to_exit_as_well_as_entry() -> None:
    stock = synthetic._stock([*synthetic._base(), synthetic._sell_day(), synthetic._flat_day()])
    leg = sim.simulate(stock, replace(PB, fill_delay=2), synthetic._seg(stock))[0]
    assert leg.entry_slot == leg.trigger_slot + 2
    assert leg.exit_slot == leg.exit_trigger_slot + 2


def test_tb136_latency_applies_to_deferred_open() -> None:
    stock = synthetic._lock_stock(sim.OK)
    leg = sim.simulate(stock, replace(PB, fill_delay=2), synthetic._seg(stock))[0]
    assert leg.exit_day == 7
    assert leg.exit_slot == 1


def test_tb136_unvaluable_h_is_unknown_not_silent_time_stop_fallback() -> None:
    stock = synthetic._lock_stock(sim.SUSPENDED)
    segments = synthetic._seg(stock, end_idx=7)
    legs = sim.simulate(stock, PB, segments)
    assert legs[0].hold_bars is None
    controls = sim.simulate_random(stock, PB, segments, legs, seed=136)
    assert controls[0].n_ok == 0
    assert np.isnan(controls[0].mean_bp)


def test_tb136_actual_h_includes_exit_wait_and_random_keeps_h() -> None:
    stock = synthetic._stock([*synthetic._base(), synthetic._sell_day(), synthetic._flat_day()])
    stock.o[6, 63:75] = 11.0
    stock.h[6, 63:75] = 11.01
    segment = synthetic._seg(stock)[0]
    leg = sim.simulate(stock, PB, [segment])[0]
    assert leg.entry_slot == 62
    assert leg.exit_trigger_slot == 62
    assert leg.exit_slot == 75
    assert leg.hold_bars == 13
    market = sim.Market(stock, PB)
    control = market.entry(segment, 6, 100, leg.direction)
    sim._resolve(market, control, segment, random=True, h=leg.hold_bars)
    assert control.entry_slot == 101
    assert control.exit_slot == 114
    assert control.hold_bars == leg.hold_bars


def test_tb136_mae_ignores_the_close_after_exit_open() -> None:
    stock = synthetic._stock([*synthetic._base(), synthetic._sell_day(), synthetic._flat_day()])
    before = sim.simulate(stock, PB, synthetic._seg(stock))[0]
    assert before.exit_slot is not None
    stock.c[before.exit_day, before.exit_slot] = 100.0
    after = sim.simulate(stock, PB, synthetic._seg(stock))[0]
    assert after.exit_slot == before.exit_slot
    assert after.exit_price == before.exit_price
    assert after.mae_bp == before.mae_bp


def test_tb136_future_late_bar_cannot_enable_deferred_early_open() -> None:
    stock = synthetic._lock_stock(sim.OK)
    for array in (stock.o, stock.h, stock.l, stock.c, stock.v, stock.a):
        array[7, 1:] = np.nan
    stock.a[7, 0] = 1e12
    before = sim.simulate(stock, PB, synthetic._seg(stock))[0]
    for array, value in zip(
        (stock.o, stock.h, stock.l, stock.c, stock.v, stock.a),
        (9, 9.01, 8.99, 9, 10000, 90000),
        strict=True,
    ):
        array[7, 239] = value
    after = sim.simulate(stock, PB, synthetic._seg(stock))[0]
    assert before.exit_day == after.exit_day == 7
    assert before.exit_slot == after.exit_slot == 0
    assert before.exit_price == after.exit_price
    assert before.pnl_bp == after.pnl_bp
    assert before.exec_anomaly


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf"), -0.01, 1.01])
def test_tb136_holm_refuses_undefined_or_out_of_range(invalid: float) -> None:
    with pytest.raises(ValueError, match="finite p values"):
        stats.holm([0.01, invalid])


def test_tb136_holm_preserves_all_34_prespecified_trials() -> None:
    values = stats.holm([0.001, *[1.0] * 33])
    assert len(values) == 34
    assert values[0] == 0.034
    assert values[1:] == [1.0] * 33


def test_tb136_execution_bar_bad_close_keeps_its_prior_open_entry() -> None:
    stock = synthetic._stock([*synthetic._base(), synthetic._sell_day(), synthetic._flat_day()])
    first = sim.simulate(stock, PB, synthetic._seg(stock))[0]
    stock.a[first.entry_day, first.entry_slot] = 1e12
    actual = sim.simulate(stock, PB, synthetic._seg(stock))[0]
    assert actual.entry_slot == first.entry_slot
    assert actual.entry_price == first.entry_price
    assert actual.q == first.q
    assert actual.exec_anomaly
