# ruff: noqa: S101
"""T-T48 / G7 H18：H-01（hold_risk_monitor）null 传播正式用例。

走真实后端求值路径（不得 mock 掉求值本身）：
- ``app.strategy.cards.fixtures.calculate``（fixtures.py）
- ``app.strategy.cards.dsl.Interpreter.evaluate`` / ``value``（dsl.py）

夹具：卡内 ``H01-FX8``（desc 含【虚构】；limit 价 null、有效 K 不足）。
断言：null 按卡规定传播 → ``insufficient_data``，不记通过、不当作 0；不产 LIMIT_LOCKED。
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.config_files import MarketRulesConfig
from app.strategy.cards.dsl import Interpreter
from app.strategy.cards.fixtures import calculate
from app.strategy.cards.preflight import feature_registry, preflight

ROOT = Path(__file__).resolve().parents[3]
CARD_PATH = ROOT / "docs/strategies/cards/hold_risk_monitor.md"


@pytest.fixture(scope="module")
def h01_corpus() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], MarketRulesConfig, set[str]]:
    registry = feature_registry((ROOT / "docs/strategies/feature_spec.md").read_text(encoding="utf-8"))
    staged, errors = preflight([CARD_PATH.read_text(encoding="utf-8")], registry)
    assert errors == [], errors
    assert len(staged) == 1
    blocks = staged[0].blocks
    card = blocks["strategy-card"]
    spec = blocks["strategy-spec"]
    fixtures = blocks["validation"]["fixtures"]
    fx8 = next(f for f in fixtures if f["id"] == "H01-FX8")
    assert "【虚构】" in fx8["desc"]
    market_rules = MarketRulesConfig.model_validate(
        yaml.safe_load((ROOT / "config/market_rules.yaml").read_text(encoding="utf-8"))
    )
    return card, spec, fx8, market_rules, set(registry)


def _run(
    card: dict[str, Any],
    spec: dict[str, Any],
    fx: dict[str, Any],
    market_rules: MarketRulesConfig,
    feature_keys: set[str],
) -> dict[str, Any]:
    return calculate(
        card,
        spec,
        features=fx["features"],
        series=fx["series"],
        holding=fx.get("holding", {}),
        context={**fx.get("ctx", {}), **fx.get("plan", {})},
        security=fx["security"],
        as_of=dt.date.fromisoformat(fx["as_of"]),
        market_rules=market_rules,
        feature_keys=feature_keys,
    )


def test_h18_h01_fx8_null_propagates_to_insufficient_data(
    h01_corpus: tuple[dict[str, Any], dict[str, Any], dict[str, Any], MarketRulesConfig, set[str]],
) -> None:
    """H01-FX8：limit null + 预热不足 → insufficient_data；rule_ids_passed 空；不当 0。"""
    card, spec, fx8, market_rules, keys = h01_corpus
    assert fx8["features"]["f.limit_up_price"] is None
    assert fx8["features"]["f.limit_down_price"] is None
    assert len(fx8["series"]["f.close_qfq"]) < 62  # 卡：MA60 预热不足

    actual = _run(card, spec, fx8, market_rules, keys)

    # 卡 expect / 正文：不足 → insufficient_data，建议 hold，不记通过
    assert actual["state"] == "insufficient_data"
    assert actual["action"] == "hold"
    assert actual["rule_ids_passed"] == []
    # null 不记为通过
    assert all(t.passed is not True for t in actual["rule_traces"])
    # 至少一条规则因缺数据 passed=null（不当作 False/0）
    assert any(t.passed is None for t in actual["rule_traces"]), [
        (t.rule_id, t.passed) for t in actual["rule_traces"]
    ]
    # limit 价 null 不产生 LIMIT_LOCKED（卡：无涨跌幅日 limit null）
    assert "LIMIT_LOCKED" not in actual["reason_codes"]
    # 与卡 expect 对齐
    assert actual["state"] == fx8["expect"]["state"]
    assert actual["action"] == fx8["expect"]["action"]
    assert actual["rule_ids_passed"] == fx8["expect"]["rule_ids_passed"]


def test_h18_tamper_null_as_false_self_fails(
    h01_corpus: tuple[dict[str, Any], dict[str, Any], dict[str, Any], MarketRulesConfig, set[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """篡改自证：把 null 当成 False（跳过/当 0）后，H18 断言必须失败；不改 src 文件。"""
    card, spec, fx8, market_rules, keys = h01_corpus
    good = _run(card, spec, fx8, market_rules, keys)
    assert good["state"] == "insufficient_data"

    real_evaluate = Interpreter.evaluate

    def _null_as_false(self: Interpreter, parsed: Any) -> bool | None:
        value = real_evaluate(self, parsed)
        # 错误语义：缺数据当不通过（False），而不是 None
        return False if value is None else value

    monkeypatch.setattr(Interpreter, "evaluate", _null_as_false)
    tampered = _run(card, spec, fx8, market_rules, keys)

    # 证明错误路径会改变结果（否则自证无效）
    assert tampered["state"] != "insufficient_data", (
        f"篡改未改变 state={tampered['state']!r}；无法自证"
    )
    # 正式断言在错误语义下必须失败
    with pytest.raises(AssertionError):
        assert tampered["state"] == "insufficient_data"
        assert tampered["rule_ids_passed"] == []
        assert any(t.passed is None for t in tampered["rule_traces"])
