# ruff: noqa: S101
"""T-T48/T-T49 / G7 H18：H-01（hold_risk_monitor）null 传播正式用例。

走真实后端求值路径（不得 mock 掉求值本身）：
- ``app.strategy.cards.fixtures.calculate``（fixtures.py）
- ``app.strategy.cards.dsl.Interpreter.evaluate`` / ``value``（dsl.py）

夹具：卡内 ``H01-FX8``（desc 含【虚构】；limit 价 null、有效 K 不足）。
T-T49：逐条钉住缺数据规则 passed is None；补 null→0 篡改自证；
使 dsl.py:247 / :253 单点 null→False 均可被抓住。
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

# H01-FX8 实测：预热不足导致的 null 规则（X1 无 plan 被跳过，不在 traces）
_NULL_RULE_IDS = frozenset({"X2", "W1", "C2", "I1"})
# 可独立求值、本夹具下为 False（不得变成 True）
_FALSE_RULE_IDS = frozenset({"W2", "W3", "C1"})


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


def _assert_h18(actual: dict[str, Any], fx8: dict[str, Any]) -> None:
    """H18 正式断言（含 T-T49 逐条 passed is None）。"""
    assert actual["state"] == "insufficient_data"
    assert actual["action"] == "hold"
    assert actual["rule_ids_passed"] == []
    assert all(t.passed is not True for t in actual["rule_traces"])
    by_id = {t.rule_id: t.passed for t in actual["rule_traces"]}
    # 逐条：缺数据规则必须 None（捕获 dsl :247 / :253 单点 null→False）
    for rid in _NULL_RULE_IDS:
        assert rid in by_id, f"缺少规则轨迹 {rid}"
        assert by_id[rid] is None, f"{rid} passed={by_id[rid]!r}，期望 None"
    for rid in _FALSE_RULE_IDS:
        assert rid in by_id
        assert by_id[rid] is False, f"{rid} passed={by_id[rid]!r}，期望 False"
    assert "LIMIT_LOCKED" not in actual["reason_codes"]
    assert actual["state"] == fx8["expect"]["state"]
    assert actual["action"] == fx8["expect"]["action"]
    assert actual["rule_ids_passed"] == fx8["expect"]["rule_ids_passed"]


def test_h18_h01_fx8_null_propagates_to_insufficient_data(
    h01_corpus: tuple[dict[str, Any], dict[str, Any], dict[str, Any], MarketRulesConfig, set[str]],
) -> None:
    """H01-FX8：limit null + 预热不足 → insufficient_data；缺数据规则逐条 passed is None。"""
    card, spec, fx8, market_rules, keys = h01_corpus
    assert fx8["features"]["f.limit_up_price"] is None
    assert fx8["features"]["f.limit_down_price"] is None
    assert len(fx8["series"]["f.close_qfq"]) < 62
    actual = _run(card, spec, fx8, market_rules, keys)
    _assert_h18(actual, fx8)


def test_h18_tamper_null_as_false_self_fails(
    h01_corpus: tuple[dict[str, Any], dict[str, Any], dict[str, Any], MarketRulesConfig, set[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """篡改自证：evaluate 层 null→False 后正式断言失败。"""
    card, spec, fx8, market_rules, keys = h01_corpus
    _assert_h18(_run(card, spec, fx8, market_rules, keys), fx8)

    real_evaluate = Interpreter.evaluate

    def _null_as_false(self: Interpreter, parsed: Any) -> bool | None:
        value = real_evaluate(self, parsed)
        return False if value is None else value

    monkeypatch.setattr(Interpreter, "evaluate", _null_as_false)
    tampered = _run(card, spec, fx8, market_rules, keys)
    with pytest.raises(AssertionError):
        _assert_h18(tampered, fx8)


def test_h18_tamper_null_as_zero_self_fails(
    h01_corpus: tuple[dict[str, Any], dict[str, Any], dict[str, Any], MarketRulesConfig, set[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-A86 ② / T-T49：value 层符号 null→0 后正式断言必须失败（不改 src）。"""
    card, spec, fx8, market_rules, keys = h01_corpus
    _assert_h18(_run(card, spec, fx8, market_rules, keys), fx8)

    real_value = Interpreter.value

    def _null_as_zero(self: Interpreter, node: Any, offset: int = 0) -> Any:
        value = real_value(self, node, offset)
        return 0 if value is None else value

    monkeypatch.setattr(Interpreter, "value", _null_as_zero)
    tampered = _run(card, spec, fx8, market_rules, keys)
    # 错误语义下通常会让部分规则变 True / state 变化
    with pytest.raises(AssertionError):
        _assert_h18(tampered, fx8)
