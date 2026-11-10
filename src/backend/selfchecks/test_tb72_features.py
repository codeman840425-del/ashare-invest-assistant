# ruff: noqa: S101
"""Pure synthetic four-code feature acceptance, with no vendor/credential access."""

import copy
import datetime as dt
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.config_files import MarketRulesConfig
from app.features.evaluation import RuleEvaluator
from app.features.pipeline import prepare
from app.strategy.cards.dsl import Interpreter, parse
from app.strategy.cards.preflight import feature_registry

ROOT = Path(__file__).resolve().parents[3]
ASOF = dt.datetime(2026, 11, 6, 12, tzinfo=dt.UTC)
REGISTRY = feature_registry((ROOT / "docs/strategies/feature_spec.md").read_text())
RULES = MarketRulesConfig.model_validate(
    yaml.safe_load((ROOT / "config/market_rules.yaml").read_text())
)


def inputs(n: int = 70) -> tuple[dict[str, Any], list[str], list[dict[str, Any]]]:
    dates = [(dt.date(2026, 8, 29) + dt.timedelta(days=i)).isoformat() for i in range(n)]
    instrument = {
        "security_code": "688018.SH",
        "board": "star",
        "adjust": "none",
        "currency": "CNY",
        "price_unit": "CNY/share",
        "volume_unit": "share",
        "amount_unit": "CNY",
        "gaps": [],
        "bars": [],
    }
    for i, day in enumerate(dates):
        instrument["bars"].append(
            {
                "trade_date": day,
                "first_seen_at": day + "T08:00:00+00:00",
                "open": str(100 + i),
                "close": str(100 + i),
                "high": str(102 + i),
                "low": str(98 + i),
                "amount": "1000000",
                "is_final": True,
            }
        )
    return (
        instrument,
        dates,
        [{"date": dates[0], "available_at": dates[0] + "T08:00:00+00:00", "value": "1"}],
    )


def frame(n: int = 70) -> dict[str, Any]:
    instrument, dates, factors = inputs(n)
    return prepare(instrument, dates, as_of=ASOF, factors=factors, registry=REGISTRY)


def evaluate(data: dict[str, Any], expr: str = "ma(f.close_qfq,60) > 0") -> dict[str, Any]:
    return RuleEvaluator().evaluate(
        card={"mount_policy": "user"},
        spec={
            "params_schema": {},
            "rules": [
                {
                    "id": "synthetic_rule",
                    "dimension": "technical",
                    "role": "entry",
                    "eval_time": "daily",
                    "expr": expr,
                }
            ],
            "action_map": {"entry_all_core_pass": "buy", "else": "wait"},
        },
        frame=data,
        holding={},
        security={"board": "star"},
        market_rules=RULES,
        registry=REGISTRY,
    )


def test_future_inputs_and_unavailable_revisions_cannot_change_result() -> None:
    instrument, dates, factors = inputs()
    baseline = prepare(instrument, dates, as_of=ASOF, factors=factors, registry=REGISTRY)
    instrument["bars"].append(
        {"trade_date": "2026-11-07", "first_seen_at": "2026-11-07T08:00:00+00:00"}
    )
    dates.append("2026-11-07")
    factors += [
        {"date": dates[0], "available_at": "2026-11-07T00:00:00+00:00", "value": "900"},
        {"date": "2026-11-07", "available_at": "2026-11-07T00:00:00+00:00", "value": "1000"},
    ]
    changed = prepare(instrument, dates, as_of=ASOF, factors=factors, registry=REGISTRY)
    assert changed == baseline
    assert evaluate(changed) == evaluate(baseline)


def test_warmup_columns_and_resolvable_evidence() -> None:
    result = evaluate(frame(10))
    assert result["state"] == "insufficient_data"
    assert result["action"] == "wait"
    result = evaluate(frame())
    assert result["state"] == "entry_ok"
    assert result["columns"]["ma(f.close_qfq, 60)@0"] == Decimal("139.5")
    ids = {item["id"] for item in result["evidence"]}
    assert ids
    assert len(ids) == len(result["evidence"])
    assert all(set(ref["evidence_ids"]) <= ids for ref in result["rule_refs"])
    assert all(item["epistemic_type"] == "hypothesis" for item in result["evidence"])
    assert frame()["features"]["f.rsi14"] == Decimal("100.00")


def test_qfq_at_t_cost_entry_and_raw_not_mutated() -> None:
    instrument, dates, factors = inputs(4)
    original = copy.deepcopy(instrument)
    factors.append({"date": dates[2], "available_at": dates[2] + "T08:00:00+00:00", "value": "2"})
    lots = [
        {
            "date": dates[0],
            "available_at": dates[0] + "T08:00:00+00:00",
            "qty": "2",
            "price": "100",
        },
        {
            "date": dates[2],
            "available_at": dates[2] + "T08:00:00+00:00",
            "qty": "2",
            "price": "102",
        },
    ]
    result = prepare(
        instrument,
        dates,
        as_of=ASOF,
        factors=factors,
        registry=REGISTRY,
        lots=lots,
        entry={"date": dates[0], "available_at": dates[0] + "T08:00:00+00:00", "price": "100"},
    )
    assert result["series"]["f.close_qfq"] == [
        Decimal("50"),
        Decimal("50.5"),
        Decimal("102"),
        Decimal("103"),
    ]
    assert result["context"] == {
        "ctx.cost_price_qfq": Decimal("76"),
        "plan.entry_price_qfq": Decimal("50"),
        "ctx.highest_close_since_entry_qfq": Decimal("103"),
    }
    assert instrument == original


def test_missing_factor_and_missing_bar_not_filled() -> None:
    instrument, dates, _ = inputs()
    result = prepare(instrument, dates, as_of=ASOF, factors=[], registry=REGISTRY)
    assert all(value is None for value in result["series"]["f.close_qfq"])
    assert evaluate(result)["state"] == "insufficient_data"
    instrument, dates, factors = inputs()
    instrument["bars"].pop(-2)
    result = prepare(instrument, dates, as_of=ASOF, factors=factors, registry=REGISTRY)
    assert result["series"]["f.close_qfq"][-2] is None
    assert evaluate(result)["state"] == "insufficient_data"


def test_suspension_skips_valid_k_but_conflict_rejected() -> None:
    instrument, dates, factors = inputs()
    instrument["gaps"] = [{"trade_date": dates[2], "reason": "suspended"}]
    with pytest.raises(ValueError, match="conflict"):
        prepare(instrument, dates, as_of=ASOF, factors=factors, registry=REGISTRY)
    instrument["bars"].pop(2)
    result = prepare(instrument, dates, as_of=ASOF, factors=factors, registry=REGISTRY)
    assert len(result["series"]["f.close_qfq"]) == 69
    assert dates[2] not in result["visible_dates"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("adjust", "qfq"),
        ("price_unit", "CNY/lot"),
        ("amount_unit", "10k_CNY"),
        ("volume_unit", "lot"),
    ],
)
def test_units_and_adjust_rejected(field: str, value: str) -> None:
    instrument, dates, factors = inputs()
    instrument[field] = value
    with pytest.raises(ValueError, match="unit_or_adjust_mismatch"):
        prepare(instrument, dates, as_of=ASOF, factors=factors, registry=REGISTRY)


def test_scalar_pit_unknown_units_and_derived_override() -> None:
    instrument, dates, factors = inputs()
    row = {
        "feature_key": "f.list_days",
        "unit": REGISTRY["f.list_days"]["unit"],
        "value": 100,
        "available_at": "2026-11-07T00:00:00+00:00",
    }
    result = prepare(
        instrument, dates, as_of=ASOF, factors=factors, registry=REGISTRY, scalars=[row]
    )
    assert result["features"]["f.list_days"] is None
    row["available_at"] = "2026-11-06T00:00:00+00:00"
    row["unit"] = "wrong"
    with pytest.raises(ValueError, match="unit"):
        prepare(instrument, dates, as_of=ASOF, factors=factors, registry=REGISTRY, scalars=[row])
    row["feature_key"] = "f.unknown"
    with pytest.raises(ValueError, match="unknown"):
        prepare(instrument, dates, as_of=ASOF, factors=factors, registry=REGISTRY, scalars=[row])


@pytest.mark.parametrize(
    "expr", ["__import__('os')", "f.unknown > 0", "f.close_qfq.__class__", "open(1)"]
)
def test_unknown_fields_and_arbitrary_code_rejected(expr: str) -> None:
    with pytest.raises(ValueError, match="dsl"):
        parse(expr, set(REGISTRY), set(), "entry", "daily")


def test_atr_wilder_unique_producer_and_short_history() -> None:
    data = frame()
    interp = Interpreter(data["features"], data["series"], {}, {})
    parsed = parse("atr(14) == 4", set(REGISTRY), set(), "entry", "daily")
    assert interp.evaluate(parsed) is True
    assert evaluate(frame(14), "atr(14) > 0")["state"] == "insufficient_data"
    result = evaluate(data, "atr(14) == 4")
    assert result["state"] == "entry_ok"
    assert result["rule_refs"][0]["evidence_ids"]
    assert all(not isinstance(item["value"], (list, dict)) for item in result["evidence"])


def test_delisted_and_partial_entry_history_remain_unknown() -> None:
    instrument, dates, factors = inputs()
    entry = {"date": dates[0], "available_at": dates[0] + "T08:00:00+00:00", "price": "100"}
    instrument["bars"].pop(3)
    result = prepare(instrument, dates, as_of=ASOF, factors=factors, registry=REGISTRY, entry=entry)
    assert "ctx.highest_close_since_entry_qfq" not in result["context"]
    instrument["bars"] = [row for row in instrument["bars"] if row["trade_date"] != "2026-11-06"]
    instrument["gaps"] = [{"trade_date": "2026-11-06", "reason": "delisted"}]
    result = prepare(instrument, dates, as_of=ASOF, factors=factors, registry=REGISTRY, entry=entry)
    assert all(value is None for value in result["features"].values())
    assert evaluate(result)["state"] == "insufficient_data"
    assert evaluate(result)["action"] == "wait"


def test_scalar_publication_is_in_evidence_freshness() -> None:
    instrument, dates, factors = inputs()
    publication = "2026-11-06T11:00:00+00:00"
    result = prepare(
        instrument,
        dates,
        as_of=ASOF,
        factors=factors,
        registry=REGISTRY,
        scalars=[
            {
                "feature_key": "f.list_days",
                "unit": REGISTRY["f.list_days"]["unit"],
                "value": 100,
                "available_at": publication,
            }
        ],
    )
    assert result["data_as_of"] == dt.datetime.fromisoformat(publication)
