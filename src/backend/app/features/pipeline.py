# ruff: noqa: ANN401
"""Sole derived-feature producer (plan 2.5.10); no vendor IO or shared DB writes."""

from __future__ import annotations

import ast
import copy
import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, cast

from app.strategy.cards.dsl import decimal


@dataclass(frozen=True)
class IndicatorColumn:
    value: Any
    inputs: dict[str, Any]


def indicator(evaluator: Any, node: ast.Call, offset: int) -> Any:
    key = ast.unparse(node) + f"@{offset}"
    if key in evaluator.columns:
        column = evaluator.columns[key]
        evaluator.inputs.update(copy.deepcopy(column.inputs))
        return column.value
    if not evaluator.materialize:
        return None
    previous = evaluator.inputs
    evaluator.inputs = {}
    try:
        value = _compute(evaluator, node, offset)
        inputs = copy.deepcopy(evaluator.inputs)
    finally:
        previous.update(evaluator.inputs)
        evaluator.inputs = previous
    evaluator.columns[key] = IndicatorColumn(value, inputs)
    return value


def _compute(evaluator: Any, node: ast.Call, offset: int) -> Any:
    if not isinstance(node.func, ast.Name):
        raise ValueError("unsafe_function")
    name = node.func.id  # validated Name, never looked up in Python globals
    args = node.args
    if name == "atr":
        n = int(evaluator.value(args[0], offset))
        if not 1 <= n <= 250:
            return None
        close, high, low = (
            evaluator.series.get("f." + key + "_qfq", []) for key in ("close", "high", "low")
        )
        end = len(close) - offset
        if end < n + 1 or len(high) != len(close) or len(low) != len(close):
            return None
        tr = []
        for i in range(1, end):
            if any(v is None for v in (high[i], low[i], close[i - 1])):
                return None
            h, low_value, c = (decimal(v) for v in (high[i], low[i], close[i - 1]))
            tr.append(max(h - low_value, abs(h - c), abs(low_value - c)))
        result = sum(tr[:n], Decimal(0)) / n
        for value in tr[n:]:
            result = (result * (n - 1) + value) / n
        evaluator.inputs["atr_source"] = {
            "f.high_qfq": high[:end],
            "f.low_qfq": low[:end],
            "f.close_qfq": close[:end],
        }
        return result
    if name in {"max2", "greatest", "min2", "least"}:
        values = [evaluator.value(arg, offset) for arg in args]
        return (
            None
            if None in values
            else (max(values) if name in {"max2", "greatest"} else min(values))
        )
    if name == "between":
        values = [evaluator.value(arg, offset) for arg in args]
        return None if None in values else values[1] <= values[0] <= values[2]
    if name in {"cross_up", "cross_down"}:
        a, b, old_a, old_b = [
            evaluator.value(arg, off) for off in (offset, offset + 1) for arg in args
        ]
        if None in (a, b, old_a, old_b):
            return None
        return a > b and old_a <= old_b if name == "cross_up" else a < b and old_a >= old_b
    n_value = evaluator.value(args[1], offset)
    if n_value is None or n_value != int(n_value):
        return None
    n = int(n_value)
    if not 0 <= n <= 250:
        return None
    if name == "ref":
        return evaluator.value(args[0], offset + n)
    if name == "pct_change":
        current, prior = evaluator.value(args[0], offset), evaluator.value(args[0], offset + n)
        return None if current is None or prior in (None, 0) else current / prior - 1
    window_values = evaluator.window(args[0], n, offset)
    if window_values is None:
        return None
    if name in {"highest", "max"}:
        return max(window_values)
    if name in {"lowest", "min"}:
        return min(window_values)
    if name == "ma":
        return sum(window_values, Decimal(0)) / n
    # Other contract functions need their production/cross-section input contracts
    # in T-B72. Never guess an answer merely to make a fixture pass.
    return None


FEATURE_SET_VERSION = "tb72-pit-1"
UTC = dt.UTC


def instant(text: str) -> dt.datetime:
    value = dt.datetime.fromisoformat(text)
    if value.tzinfo is None:
        raise ValueError("available_at_requires_timezone")
    return value


def prepare(
    instrument: dict[str, Any],
    sessions: list[str],
    *,
    as_of: dt.datetime,
    factors: list[dict[str, Any]],
    scalars: list[dict[str, Any]] | None = None,
    registry: dict[str, dict[str, Any]],
    lots: list[dict[str, Any]] | None = None,
    entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """T-B70 unadjusted CNY/share rows -> qfq@as_of, using only then-visible inputs.

    Factors are explicit cumulative A(d) observations, NEVER implicitly filled as 1.
    This pure adapter does not fetch factors, infer board/status, or read private data.
    """
    if as_of.tzinfo is None:
        raise ValueError("as_of_requires_timezone")
    if (
        instrument.get("adjust"),
        instrument.get("currency"),
        instrument.get("price_unit"),
        instrument.get("amount_unit"),
        instrument.get("volume_unit"),
    ) != ("none", "CNY", "CNY/share", "CNY", "share"):
        raise ValueError("unit_or_adjust_mismatch")
    day = as_of.astimezone(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
    known_factors = [
        row for row in factors if row["date"] <= day and instant(row["available_at"]) <= as_of
    ]
    known_factors.sort(key=lambda row: (row["date"], instant(row["available_at"])))

    def factor(date: str) -> Decimal | None:
        prior = [row for row in known_factors if row["date"] <= date]
        if not prior:
            return None
        value = Decimal(str(prior[-1]["value"]))
        if not value.is_finite() or value <= 0:
            raise ValueError("invalid_adjust_factor")
        return value

    base = factor(day)
    bars = {}
    for row in instrument["bars"]:
        if (
            row["trade_date"] <= day
            and instant(row["first_seen_at"]) <= as_of
            and row.get("is_final") is True
        ):
            if row["trade_date"] in bars:
                raise ValueError("duplicate_daily_bar")
            bars[row["trade_date"]] = row
    observations = [instant(row["available_at"]) for row in known_factors]
    observations.extend(instant(row["first_seen_at"]) for row in bars.values())
    gaps = {
        row["trade_date"]: row["reason"]
        for row in instrument.get("gaps", [])
        if row["trade_date"] <= day
    }
    if any(date in bars and reason in {"suspended", "delisted"} for date, reason in gaps.items()):
        raise ValueError("suspension_or_listing_conflict")
    selected = [
        date
        for date in sessions
        if date <= day and date not in {d for d, r in gaps.items() if r == "suspended"}
    ]
    if selected != sorted(set(selected)):
        raise ValueError("unordered_or_duplicate_sessions")
    inactive = any(reason in {"delisted", "missing_from_list"} for reason in gaps.values())
    series: dict[str, list[Any]] = {
        key: [] for key in ("f.close_qfq", "f.high_qfq", "f.low_qfq", "f.amount")
    }
    missing = []
    for date in selected:
        row = bars.get(date)
        a = factor(date)
        if row is None:
            missing.append("daily_bar_missing:" + date)
        if a is None or base is None:
            missing.append("adjust_factor_missing:" + date)
        for key, field in (("f.close_qfq", "close"), ("f.high_qfq", "high"), ("f.low_qfq", "low")):
            value = (
                Decimal(str(row[field])) * a / base
                if row and a is not None and base is not None and not inactive
                else None
            )
            series[key].append(value)
        series["f.amount"].append(Decimal(str(row["amount"])) if row and not inactive else None)
    features: dict[str, Any] = dict.fromkeys(registry)
    features["f.is_suspended"] = (
        True if gaps.get(day) == "suspended" else False if day in bars else None
    )
    if inactive:
        features["f.is_suspended"] = None
    for key, values in series.items():
        features[key] = values[-1] if values else None
    for row in sorted(scalars or [], key=lambda item: item["available_at"]):
        if instant(row["available_at"]) > as_of or row.get("date", day) > day:
            continue
        key = row["feature_key"]
        if key not in registry:
            raise ValueError("unknown_feature")
        if row["unit"] != registry[key]["unit"]:
            raise ValueError("feature_unit_mismatch")
        if key in series or key in {"f.is_suspended", "f.rsi14"}:
            raise ValueError("derived_feature_override")
        features[key] = row["value"]
        observations.append(instant(row["available_at"]))
    close = series["f.close_qfq"]
    # Wilder RSI14, declared warmup 28, never pad/forward-fill missing bars.
    rsi = None
    if len(close) >= 28 and all(value is not None for value in close):
        changes = [close[i] - close[i - 1] for i in range(1, len(close))]
        gains = [max(value, Decimal(0)) for value in changes]
        losses = [max(-value, Decimal(0)) for value in changes]
        gain, loss = sum(gains[:14], Decimal(0)) / 14, sum(losses[:14], Decimal(0)) / 14
        for up, down in zip(gains[14:], losses[14:], strict=True):
            gain, loss = (gain * 13 + up) / 14, (loss * 13 + down) / 14
        rsi = (Decimal(100) if loss == 0 else 100 - 100 / (1 + gain / loss)).quantize(
            Decimal("0.01")
        )
    features["f.rsi14"] = rsi
    context: dict[str, Any] = {}
    if lots:
        eligible = [
            lot for lot in lots if lot["date"] <= day and instant(lot["available_at"]) <= as_of
        ]
        observations.extend(instant(lot["available_at"]) for lot in eligible)
        total = sum((Decimal(str(lot["qty"])) for lot in eligible), Decimal(0))
        if (
            total > 0
            and base is not None
            and all(factor(lot["date"]) is not None for lot in eligible)
        ):
            context["ctx.cost_price_qfq"] = (
                sum(
                    (
                        Decimal(str(lot["qty"]))
                        * Decimal(str(lot["price"]))
                        * cast(Decimal, factor(lot["date"]))
                        / base
                        for lot in eligible
                    ),
                    Decimal(0),
                )
                / total
            )
    if (
        entry
        and entry["date"] <= day
        and instant(entry["available_at"]) <= as_of
        and base is not None
    ):
        observations.append(instant(entry["available_at"]))
        start = factor(entry["date"])
        if start is not None:
            context["plan.entry_price_qfq"] = Decimal(str(entry["price"])) * start / base
        held = [
            value
            for date, value in zip(selected, close, strict=True)
            if date >= entry["date"] and value is not None
        ]
        complete = [
            value for date, value in zip(selected, close, strict=True) if date >= entry["date"]
        ]
        if held and complete and all(value is not None for value in complete):
            context["ctx.highest_close_since_entry_qfq"] = max(held)
    if inactive:
        features = dict.fromkeys(features)
        context = {}
        missing.append("security_inactive")
    return {
        "feature_set_version": FEATURE_SET_VERSION,
        "as_of": as_of,
        "features": features,
        "series": series,
        "context": context,
        "gaps": sorted(set(missing)),
        "visible_dates": selected,
        "data_as_of": max(observations, default=None),
    }
