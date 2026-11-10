# ruff: noqa: S101
"""T-T63 / G7：H12、S12、S20 执行链缺口补例（不重复 T-T46 已有用例）。

已有覆盖（本文件不再重写；亲跑 + 篡改反验见 reports/T-T63.md）：
- ``tests/backend/unit/test_tb113_l1_l10_runner_h12_h17_t_t46.py``
  ``test_tb113_h12_system_only_evaluates_holdings_exits_only``
  （system_only 只对持仓离场求值；未持有含在自选出局）
- 同文件 ``test_tb113_s12_screen_null_pool_is_holdings_union_watchlist_not_full_market``
  （拒全市场 / pool=None；只扫持仓 ∪ 自选）。S20 运行侧「只扫持仓 ∪ 自选」与此合并。

本文件只补缺口：H12 的 422 ``STRATEGY_SYSTEM_ONLY`` 与北交所；S12 的 bse / ST / 停牌 / F2；
官方卡字段直通（S12/S20 的 screen:null 规范化，以及 H-01 主板键）。
T-T64：在 T-B119 合入后去掉两条 strict xfail，断言未改、未弱化。
T-T67：H12/S12 板块三例改为生产 ``board_in_universe``，删除测试内复刻。

对照：``git show 60ce9fd:docs/strategies/T-R41/g7_review_H-01_S-01.md`` §6、
/workspace/team/reports/T-R47.md、T-A111.md。夹具均为【虚构】；不调麦蕊。
"""

from __future__ import annotations

import datetime as dt
import sys
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src/backend"))

import app.signals.screen as screen_mod
from app.common.errors import AppError, ErrorCode
from app.config_files import MarketRulesConfig
from app.signals.execution import assess
from app.signals.models import MarketFacts, SignalInput
from app.strategy.cards.fixtures import calculate
from app.strategy.universe_norm import board_in_universe
from app.strategy.cards.preflight import feature_registry, preflight
from app.strategy.instances import creation

H01_PATH = ROOT / "docs/strategies/cards/hold_risk_monitor.md"
S01_PATH = ROOT / "docs/strategies/cards/st_pullback_ma.md"
_FIC_MAIN = "600000.SH"
_FIC_BSE = "830001.BJ"
_AT = dt.datetime(2026, 11, 9, 15, 0, tzinfo=dt.UTC)


def _load_card(path: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    registry = feature_registry((ROOT / "docs/strategies/feature_spec.md").read_text(encoding="utf-8"))
    staged, errors = preflight([path.read_text(encoding="utf-8")], registry)
    assert errors == [], errors
    assert len(staged) == 1
    blocks = staged[0].blocks
    fixtures = blocks["validation"]["fixtures"]
    assert all("【虚构】" in fx["desc"] for fx in fixtures)
    return blocks["strategy-card"], blocks["strategy-spec"], fixtures


@pytest.fixture(scope="module")
def h01() -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    return _load_card(H01_PATH)


@pytest.fixture(scope="module")
def s01() -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    return _load_card(S01_PATH)


@pytest.fixture(scope="module")
def market_rules() -> MarketRulesConfig:
    return MarketRulesConfig.model_validate(
        yaml.safe_load((ROOT / "config/market_rules.yaml").read_text(encoding="utf-8"))
    )


@pytest.fixture(scope="module")
def feature_keys() -> set[str]:
    return set(feature_registry((ROOT / "docs/strategies/feature_spec.md").read_text(encoding="utf-8")))


def _fixture(fixtures: list[dict[str, Any]], fid: str) -> dict[str, Any]:
    return next(fx for fx in fixtures if fx["id"] == fid)


def _run_fx(
    card: dict[str, Any],
    spec: dict[str, Any],
    fx: dict[str, Any],
    market_rules: MarketRulesConfig,
    feature_keys: set[str],
    *,
    features: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return calculate(
        card,
        spec,
        features=features if features is not None else fx["features"],
        series=fx["series"],
        holding=fx.get("holding", {}),
        context={**fx.get("ctx", {}), **fx.get("plan", {})},
        security=fx["security"],
        as_of=dt.date.fromisoformat(fx["as_of"]),
        market_rules=market_rules,
        feature_keys=feature_keys,
    )


def _admit(universe: dict[str, Any] | None, **kwargs: Any) -> str | None:
    return screen_mod.screen_membership(universe=universe, **kwargs)


# ---- H12 缺口：422、北交所、主板键 ------------------------------------------------


def test_h12_official_card_system_only_holdings_pool_and_bse_false(
    h01: tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]],
) -> None:
    card, _spec, _fx = h01
    assert card["mount_policy"] == "system_only"
    assert card["universe"]["pool"] == "持仓"
    assert card["universe"]["boards"]["bse"] is False
    assert "stock" in card["universe"]["security_types"]


def test_h12_user_create_instance_422_strategy_system_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """用户创建实例走生产 ``creation.create``，system_only → 422 STRATEGY_SYSTEM_ONLY。"""
    conn = MagicMock()
    conn.execute.return_value.first.return_value = object()
    version = SimpleNamespace(
        config={"mount_policy": "system_only", "horizons": ["short"]},
        lifecycle="published",
    )
    monkeypatch.setattr(creation, "version_owned", lambda *_a, **_k: version)
    with pytest.raises(AppError) as err:
        creation.create(
            conn,
            uuid.uuid4(),
            is_admin=False,
            version_id=uuid.uuid4(),
            account_id=uuid.uuid4(),
            security_code=None,
            scope="account",
            horizon="short",
            overrides=None,
            budget=None,
            risk_config=object(),  # type: ignore[arg-type]
        )
    assert err.value.code == ErrorCode.STRATEGY_SYSTEM_ONLY
    assert err.value.status_code == 422
    assert conn.execute.call_count == 1


def _assert_h12_bse_excluded(universe: dict[str, Any]) -> None:
    assert _FIC_BSE.endswith(".BJ")
    # 原复刻同时检查 security_types=["stock"] 与 boards；类型检查保留，板块改走生产函数
    assert "stock" in universe.get("security_types", [])
    boards = universe.get("boards")
    assert board_in_universe(boards, "bse") is False
    assert board_in_universe(boards, "chinext") is True
    assert board_in_universe(boards, "star") is True


def test_h12_bse_not_in_universe(
    h01: tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]],
) -> None:
    _assert_h12_bse_excluded(h01[0]["universe"])


def test_h12_main_board_in_universe_via_production_key(
    h01: tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]],
) -> None:
    universe = h01[0]["universe"]
    assert "stock" in universe.get("security_types", [])
    boards = universe.get("boards")
    assert board_in_universe(boards, "main_board") is True
    # 同一官方卡上北交所仍须排除，避免「一律 True」也能让本例通过
    assert board_in_universe(boards, "bse") is False


def test_h12_tamper_bse_admitted_self_fails(
    h01: tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]],
) -> None:
    """篡改反验（缺口口径）：把 boards.bse 改成 True 后，北交所排除断言必须 FAIL。"""
    universe = h01[0]["universe"]
    _assert_h12_bse_excluded(universe)
    tweaked = {**universe, "boards": {**universe["boards"], "bse": True}}
    with pytest.raises(AssertionError):
        _assert_h12_bse_excluded(tweaked)


# ---- S12 / S20 缺口：bse、ST、停牌、F2、官方卡直通 --------------------------------


def test_s12_bse_false_on_official_boards(
    s01: tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]],
) -> None:
    card, _spec, _fx = s01
    boards = card["universe"]["boards"]
    assert boards["bse"] is False
    assert bool(boards.get("chinext", False)) is True
    assert bool(boards.get("star", False)) is True
    # 原自造 remapper 补齐 security_types=["stock"] 后再用复刻函数；改为直接断言生产字段与生产门闩
    assert "stock" in card["universe"].get("security_types", [])
    assert board_in_universe(boards, "bse") is False
    assert board_in_universe(boards, "star") is True


def test_s12_halt_excluded_s01_fx6(
    s01: tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]],
    market_rules: MarketRulesConfig,
    feature_keys: set[str],
) -> None:
    card, spec, fixtures = s01
    fx6 = _fixture(fixtures, "S01-FX6")
    assert "【虚构】" in fx6["desc"]
    actual = _run_fx(card, spec, fx6, market_rules, feature_keys)
    assert actual["state"] == "entry_ok"
    assert actual["action"] == "buy"
    assert "SUSPENDED" in actual["reason_codes"]
    assert actual["reason_details"]["SUSPENDED"]["direction"] == "buy"


def _assert_s12_f2_excludes(
    card: dict[str, Any],
    spec: dict[str, Any],
    fx1: dict[str, Any],
    market_rules: MarketRulesConfig,
    feature_keys: set[str],
) -> None:
    min_days = spec["params_schema"]["min_list_days"]["default"]
    assert min_days == 60
    features = dict(fx1["features"])
    features["f.list_days"] = 40  # < 60（F2）且 ≥30（不与 NEW_LISTING 混）
    actual = _run_fx(card, spec, fx1, market_rules, feature_keys, features=features)
    assert "F2" not in actual["rule_ids_passed"]
    assert actual["state"] == "not_triggered"
    assert actual["action"] == "wait"
    baseline = _run_fx(card, spec, fx1, market_rules, feature_keys)
    assert "F2" in baseline["rule_ids_passed"]
    assert baseline["state"] == "entry_ok"


def test_s12_f2_excludes_when_list_days_below_min(
    s01: tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]],
    market_rules: MarketRulesConfig,
    feature_keys: set[str],
) -> None:
    card, spec, fixtures = s01
    _assert_s12_f2_excludes(card, spec, _fixture(fixtures, "S01-FX1"), market_rules, feature_keys)


def test_s12_st_excluded_via_assess() -> None:
    """买入路径：主表 risk_flag=st 时 execution.assess 记 ST_OR_DELISTING。"""
    eid = "tt63-fic-e1"
    content = SignalInput.model_validate(
        {
            "security_code": _FIC_MAIN,
            "proposed_action": "buy",
            "t_leg": None,
            "score": None,
            "confidence": {"level": "high", "value": "0.8"},
            "stops": {"stop_loss": None, "take_profit": None, "time_stop_days": None},
            "rule_refs": [
                {
                    "rule_id": "E1",
                    "snippet_id": None,
                    "snippet_version": None,
                    "role": "entry",
                    "dimension": "technical",
                    "passed": True,
                    "value": None,
                    "threshold": None,
                    "evidence_ids": [eid],
                }
            ],
            "evidence": [
                {
                    "id": eid,
                    "key": "f.close_qfq",
                    "value": 12.5,
                    "unit": None,
                    "provider": "system",
                    "endpoint": None,
                    "data_as_of": _AT,
                    "fetched_at": _AT,
                    "epistemic_type": "fact",
                }
            ],
            "counter_evidence": [
                {"text": "【虚构】反证未触发", "expr": "f.close_qfq < 0", "evidence_ids": [eid]}
            ],
            "invalidation": [
                {"text": "【虚构】失效未触发", "expr": "f.close_qfq < 1", "evidence_ids": [eid]}
            ],
            "model_refs": [],
            "risk_flags": [],
            "valid_until": None,
            "snapshot_id": str(uuid.uuid4()),
            "feature_set_version": "tt63-fictional",
            "created_at": _AT,
            "data_status": "fresh",
            "data_as_of": _AT,
            "gaps": [],
        }
    )
    facts = MarketFacts(
        price=Decimal("12.5"),
        required_cash=Decimal("1250"),
        is_suspended=False,
        list_days=600,
        limit_locked_up=False,
        limit_locked_down=False,
    )
    kwargs: dict[str, Any] = dict(
        qty=Decimal(0),
        sellable=Decimal(0),
        cash=Decimal("100000"),
        min_buy=100,
        min_sell=100,
        trading=True,
        next_open=_AT,
    )
    st = assess(content, facts, risk_flag="st", **kwargs)
    assert "ST_OR_DELISTING" in [b["code"] for b in st]
    clean = assess(content, facts, risk_flag=None, **kwargs)
    assert "ST_OR_DELISTING" not in [b["code"] for b in clean]


def test_s12_tamper_f2_always_pass_self_fails(
    s01: tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]],
    market_rules: MarketRulesConfig,
    feature_keys: set[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """篡改反验（S12 缺口口径）：把 F2 的 list_days 比较改成恒真后，F2 排除断言必须 FAIL。"""
    from app.strategy.cards.dsl import Interpreter

    card, spec, fixtures = s01
    fx1 = _fixture(fixtures, "S01-FX1")
    _assert_s12_f2_excludes(card, spec, fx1, market_rules, feature_keys)

    real = Interpreter.evaluate

    def _list_days_filter_true(self: Interpreter, parsed: Any) -> bool | None:
        value = real(self, parsed)
        inputs = getattr(self, "inputs", {}) or {}
        if any("list_days" in str(k) for k in inputs):
            return True
        return value

    monkeypatch.setattr(Interpreter, "evaluate", _list_days_filter_true)
    with pytest.raises(AssertionError):
        _assert_s12_f2_excludes(card, spec, fx1, market_rules, feature_keys)


def test_s12_s20_official_card_fields_admit_holdings_and_watchlist(
    s01: tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]],
) -> None:
    """官方卡字段（含 screen:null）直通生产 screen_membership，必须只扫持仓 ∪ 自选。"""
    card, spec, _fx = s01
    assert spec.get("screen") is None
    assert card.get("screen") is None
    universe = card["universe"]
    mount = str(card.get("mount_policy") or "user")
    assert (
        _admit(universe, quantity=100, on_watchlist=False, mount_policy=mount, proposed_action="buy")
        is None
    )
    assert (
        _admit(universe, quantity=0, on_watchlist=True, mount_policy=mount, proposed_action="buy")
        is None
    )
    assert (
        _admit(universe, quantity=0, on_watchlist=False, mount_policy=mount, proposed_action="buy")
        == "outside_universe"
    )


def _assert_s20_official_screen_null_rejects_full_market_literals(
    spec: dict[str, Any], card: dict[str, Any]
) -> None:
    assert spec.get("screen") is None
    assert card.get("screen") is None
    # 已有 T-T46 例覆盖 pool="全市场"；这里钉官方卡字面（T-R43 注明的 v1 口径）
    diag = _admit(
        {
            "pool": "全市场（持仓 ∪ 自选优先）",
            "boards": {"main": True},
            "security_types": ["stock"],
        },
        quantity=100,
        on_watchlist=True,
        mount_policy="user",
        proposed_action="buy",
    )
    assert diag == "universe_pool_not_supported", f"官方 pool 字面被放行: {diag}"


def test_s20_official_card_screen_is_null_rejects_official_pool_literal(
    s01: tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]],
) -> None:
    card, spec, _fx = s01
    _assert_s20_official_screen_null_rejects_full_market_literals(spec, card)


def test_s20_tamper_official_pool_literal_self_fails(
    s01: tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """篡改反验（S20 缺口口径）：允许官方 pool 字面后，拒绝全市场扫描的断言必须 FAIL。"""
    card, spec, _fx = s01
    _assert_s20_official_screen_null_rejects_full_market_literals(spec, card)
    monkeypatch.setattr(
        screen_mod,
        "_ALLOWED_POOLS",
        frozenset({"持仓", "持仓 ∪ 自选", "全市场（持仓 ∪ 自选优先）"}),
    )
    with pytest.raises(AssertionError):
        _assert_s20_official_screen_null_rejects_full_market_literals(spec, card)
