# ruff: noqa: S101, ANN401
"""Read-only formal synthetic research corpus; no golden answers enter calculate()."""

from __future__ import annotations

import copy
import datetime as dt
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.config_files import MarketRulesConfig
from app.strategy.cards.dsl import Interpreter, parse
from app.strategy.cards.fixtures import calculate, run_fixtures
from app.strategy.cards.preflight import check_adjust, feature_registry, parameter_valid, preflight

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def corpus() -> Any:
    registry = feature_registry((ROOT / "docs/strategies/feature_spec.md").read_text())
    paths = [
        ROOT / "docs/strategies/cards" / name
        for name in ("hold_risk_monitor.md", "sw_ma_trend_pullback.md")
    ]
    staged, errors = preflight([path.read_text() for path in paths], registry)
    market_rules = MarketRulesConfig.model_validate(
        yaml.safe_load((ROOT / "config/market_rules.yaml").read_text())
    )
    return staged, errors, registry, market_rules


@pytest.mark.parametrize("index", range(26))
def test_all_golden_independently(corpus: Any, index: int) -> None:
    staged, _, registry, market_rules = corpus
    inputs = [
        (item.blocks, fixture)
        for item in staged
        for fixture in item.blocks["validation"]["fixtures"]
    ]
    block, fixture = inputs[index]
    result = run_fixtures(
        block["strategy-card"], block["strategy-spec"], [fixture], market_rules, set(registry)
    )[0]
    assert result.passed, (result.fixture_id, result.mismatches)
    assert all(trace.expr and trace.dimension for trace in result.rule_traces)
    assert any(trace.computed_values for trace in result.rule_traces)


def test_preflight_formal_metadata_correction(corpus: Any) -> None:
    staged, errors, _, _ = corpus
    assert len(staged) == 2
    assert errors == []  # d783fdf supplies all three research-owned annotations
    assert all(not item.persistable and not item.runnable for item in staged)


def test_expected_answers_and_identifiers_cannot_drive_calculation(corpus: Any) -> None:
    staged, _, registry, market_rules = corpus
    block = staged[1].blocks
    original = block["validation"]["fixtures"][0]
    changed = copy.deepcopy(original)
    changed["id"] = "arbitrary-id"
    changed["expect"]["state"] = "exit_signal"
    changed["desc"] = "arbitrary narrative"
    result = run_fixtures(
        block["strategy-card"], block["strategy-spec"], [changed], market_rules, set(registry)
    )[0]
    assert not result.passed
    assert result.state == "entry_ok"
    assert result.fixture_id == "arbitrary-id"
    inputs = copy.deepcopy(original)
    inputs["features"]["f.market_regime"] = "downtrend"
    actual = calculate(
        block["strategy-card"],
        block["strategy-spec"],
        features=inputs["features"],
        series=inputs["series"],
        holding=inputs.get("holding", {}),
        context={},
        security=inputs["security"],
        as_of=dt.date.fromisoformat(inputs["as_of"]),
        market_rules=market_rules,
        feature_keys=set(registry),
    )
    assert actual["state"] == "vetoed"


@pytest.mark.parametrize(
    "expression",
    [
        '__import__("os")',
        "f.close_qfq.__class__",
        "f.unknown > 0",
        "ma()",
        "ma(f.close_qfq, 2, 3)",
        "(lambda: 1)()",
        "[x for x in [1]]",
        "f.close_qfq[0]",
        "2 ** 5000000",
        'open("x")',
    ],
)
def test_dsl_rejects_unapproved_python_and_arity(expression: str) -> None:
    with pytest.raises(ValueError, match=r"dsl|unsafe"):
        parse(expression, {"f.close_qfq"}, set(), "entry", "daily_close")


def test_adjustment_mixing_is_rejected(corpus: Any) -> None:
    _, _, registry, _ = corpus
    tree, _, _ = parse("f.close_qfq < ctx.cost_price", set(registry), set(), "exit", "daily_close")
    with pytest.raises(ValueError, match="adjust_mismatch"):
        check_adjust(tree, registry)


@pytest.mark.parametrize("value", [True, "2", 0, 6, 2.5])
def test_strict_parameter_rejection(value: Any) -> None:
    assert not parameter_valid(value, {"type": "int", "min": 1, "max": 5, "step": 1})


def test_missing_warmup_never_manufactures_true() -> None:
    parsed = parse("ma(f.close_qfq, 60) > 1", {"f.close_qfq"}, set(), "entry", "daily_close")
    assert Interpreter({}, {"f.close_qfq": [2, 3]}, {}, {}).evaluate(parsed) is None
