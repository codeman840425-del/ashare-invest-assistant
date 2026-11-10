# ruff: noqa: S101
"""T-T63 / G7：H-01 H12、S-01 S12/S20 后端执行链正式用例。

对照（只读，不以本文件改 docs）：
- ``git show 60ce9fd:docs/strategies/T-R41/g7_review_H-01_S-01.md`` §6
  H12：system_only 只对持仓求值、未持有不出结论、用户实例化 422 ``STRATEGY_SYSTEM_ONLY``、北交所不在范围
  S12：``screen:null`` 只扫持仓 ∪ 自选、bse:false、ST/停牌/F2 排除
  S20：运行侧「screen:null 只扫持仓 ∪ 自选」（与 S12 合并）
- /workspace/team/reports/T-R47.md、T-A111.md

走生产入口（不 mock 掉被测口径本身）：
- ``app.signals.screen.screen_membership``（service 挂载/选股准入）
- ``app.signals.service`` 中的板块归属判定（boards[master.board]）
- ``app.strategy.instances.creation.create``（用户实例化）
- ``app.strategy.cards.fixtures.calculate``（停牌 / F2）
- ``app.signals.execution.assess``（ST）

夹具：官方卡内【虚构】例 + 本文件构造的虚构标的/特征；不调麦蕊、不碰用户数据。
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
from app.signals.screen import screen_membership
from app.strategy.cards.fixtures import calculate
from app.strategy.cards.preflight import feature_registry, preflight
from app.strategy.instances import creation

H01_PATH = ROOT / "docs/strategies/cards/hold_risk_monitor.md"
S01_PATH = ROOT / "docs/strategies/cards/st_pullback_ma.md"
# 卡内允许的虚构示例代码；北交所用 .BJ 仅作板块标签，不代表真实行情
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


def _admit(
    universe: dict[str, Any] | None,
    *,
    quantity: Decimal | int,
    on_watchlist: bool,
    mount_policy: str,
    proposed_action: str,
) -> str | None:
    return screen_mod.screen_membership(
        universe=universe,
        quantity=quantity,
        on_watchlist=on_watchlist,
        mount_policy=mount_policy,
        proposed_action=proposed_action,
    )


def _board_in_universe(universe: dict[str, Any], board: str, security_type: str = "stock") -> bool:
    """与 service.py persist 中板块/类型判定同一口径（约 :351-:354）。"""
    return security_type in universe.get("security_types", []) and bool(
        universe.get("boards", {}).get(board, False)
    )


def _h01_mount_result(
    universe: dict[str, Any],
    mount_policy: str,
    *,
    quantity: int,
    on_watchlist: bool,
    proposed_action: str,
) -> dict[str, Any]:
    """挂载执行链准入：有诊断则不出结论（与 service 提前返回 {id: None, diagnostic} 一致）。"""
    diag = _admit(
        universe,
        quantity=quantity,
        on_watchlist=on_watchlist,
        mount_policy=mount_policy,
        proposed_action=proposed_action,
    )
    if diag is not None:
        return {"id": None, "diagnostic": diag}
    return {"id": "would_evaluate", "diagnostic": None}


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


def _v1_holdings_watch_universe(official_universe: dict[str, Any]) -> dict[str, Any]:
    """v1 意图池：持仓 ∪ 自选；保留官方 boards，补齐 security_types；去掉叙述性 exclude 键。

    仅用于证明生产 ``screen_membership`` / 板块判定在「已规范化」输入下的行为，
    不是生产改写（官方卡字段直通见 xfail 例）。
    """
    boards = dict(official_universe.get("boards") or {})
    return {
        "pool": "持仓 ∪ 自选",
        "boards": boards,
        "security_types": list(official_universe.get("security_types") or ["stock"]),
    }


# ---- H12 ------------------------------------------------------------------


def _assert_h12_not_held_no_conclusion(card: dict[str, Any]) -> None:
    universe = card["universe"]
    mount = str(card["mount_policy"])
    # 未持有（即使在自选）不得出结论
    for watch in (False, True):
        result = _h01_mount_result(
            universe, mount, quantity=0, on_watchlist=watch, proposed_action="sell"
        )
        assert result["id"] is None, f"未持有仍出结论 watch={watch}: {result}"
        assert result["diagnostic"] == "outside_universe"
    # 持仓可对离场动作求值
    held = _h01_mount_result(
        universe, mount, quantity=100, on_watchlist=False, proposed_action="sell"
    )
    assert held["id"] is not None and held["diagnostic"] is None


def test_h12_official_card_system_only_holdings_pool_and_bse_false(
    h01: tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]],
) -> None:
    card, _spec, _fx = h01
    assert card["mount_policy"] == "system_only"
    assert card["universe"]["pool"] == "持仓"
    assert card["universe"]["boards"]["bse"] is False
    assert "stock" in card["universe"]["security_types"]


def test_h12_system_only_only_evaluates_holdings(
    h01: tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]],
) -> None:
    card, _spec, _fx = h01
    universe, mount = card["universe"], str(card["mount_policy"])
    # 未持有 + 在自选：持仓池仍排除
    assert (
        _admit(universe, quantity=0, on_watchlist=True, mount_policy=mount, proposed_action="buy")
        == "outside_universe"
    )
    # 持仓但非离场动作
    assert (
        _admit(universe, quantity=100, on_watchlist=False, mount_policy=mount, proposed_action="buy")
        == "system_exit_only"
    )
    assert (
        _admit(
            universe, quantity=100, on_watchlist=False, mount_policy=mount, proposed_action="reduce"
        )
        is None
    )
    assert (
        _admit(universe, quantity=100, on_watchlist=False, mount_policy=mount, proposed_action="sell")
        is None
    )


def test_h12_not_held_writes_no_conclusion(
    h01: tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]],
) -> None:
    card, _spec, _fx = h01
    _assert_h12_not_held_no_conclusion(card)


def test_h12_user_create_instance_422_strategy_system_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """用户创建实例走 production ``creation.create``，system_only → 422 STRATEGY_SYSTEM_ONLY。"""
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
    # 在挂载策略检查处即返回，不得继续写实例
    assert conn.execute.call_count == 1


def test_h12_bse_not_in_universe(
    h01: tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]],
) -> None:
    card, _spec, _fx = h01
    universe = card["universe"]
    assert _FIC_BSE.endswith(".BJ")
    assert _board_in_universe(universe, "bse") is False
    # 对照：创业板/科创板在范围内（键名与 Board 枚举一致）
    assert _board_in_universe(universe, "chinext") is True
    assert _board_in_universe(universe, "star") is True


@pytest.mark.xfail(
    reason=(
        "功能缺口：H-01 卡 universe.boards 键为 main，service.py persist 用 "
        "master.board=main_board 且未归一，主板会被误判 outside_universe。"
        "应由后端（或卡键对齐）修，本单不改 src。"
    ),
    strict=True,
)
def test_h12_main_board_in_universe_via_production_key(
    h01: tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]],
) -> None:
    card, _spec, _fx = h01
    # 生产主表 Board 枚举是 main_board，不是卡面的 main
    assert _board_in_universe(card["universe"], "main_board") is True


def test_h12_tamper_admit_not_held_self_fails(
    h01: tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """篡改反验：把 screen_membership 改成一律放行后，未持有不出结论的断言必须 FAIL。"""
    card, _spec, _fx = h01
    _assert_h12_not_held_no_conclusion(card)
    monkeypatch.setattr(screen_mod, "screen_membership", lambda **_k: None)
    with pytest.raises(AssertionError):
        _assert_h12_not_held_no_conclusion(card)


# ---- S12 / S20 -------------------------------------------------------------


def _assert_s12_s20_pool_is_holdings_union_watchlist(universe: dict[str, Any]) -> None:
    """选股执行链：只扫持仓 ∪ 自选，拒绝全市场，非持仓且非自选出局。"""
    mount, buy = "user", "buy"
    assert (
        _admit(
            {**universe, "pool": "全市场"},
            quantity=100,
            on_watchlist=True,
            mount_policy=mount,
            proposed_action=buy,
        )
        == "universe_pool_not_supported"
    )
    assert (
        _admit(
            {**universe, "pool": None},
            quantity=100,
            on_watchlist=True,
            mount_policy=mount,
            proposed_action=buy,
        )
        == "universe_pool_not_supported"
    )
    assert (
        _admit(universe, quantity=100, on_watchlist=False, mount_policy=mount, proposed_action=buy)
        is None
    )
    assert (
        _admit(universe, quantity=0, on_watchlist=True, mount_policy=mount, proposed_action=buy)
        is None
    )
    assert (
        _admit(universe, quantity=0, on_watchlist=False, mount_policy=mount, proposed_action=buy)
        == "outside_universe"
    )


def test_s12_screen_membership_holdings_union_watchlist_not_full_market(
    s01: tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]],
) -> None:
    card, _spec, _fx = s01
    _assert_s12_s20_pool_is_holdings_union_watchlist(_v1_holdings_watch_universe(card["universe"]))


def test_s12_bse_false_on_official_boards(
    s01: tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]],
) -> None:
    card, _spec, _fx = s01
    boards = card["universe"]["boards"]
    assert boards["bse"] is False
    # 官方卡无 security_types，persist 口径会拒全部类型；本例只核 boards 开关本身
    assert bool(boards.get("bse", False)) is False
    assert bool(boards.get("chinext", False)) is True
    assert bool(boards.get("star", False)) is True
    # 用补齐类型后的规范化 universe 再走生产 persist 口径
    uni = _v1_holdings_watch_universe(card["universe"])
    assert _board_in_universe(uni, "bse") is False
    assert _board_in_universe(uni, "star") is True


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


def test_s12_f2_excludes_when_list_days_below_min(
    s01: tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]],
    market_rules: MarketRulesConfig,
    feature_keys: set[str],
) -> None:
    """【虚构】在入场夹具上把 list_days 改到 min_list_days 以下：F2 不通过，不得 entry_ok。"""
    card, spec, fixtures = s01
    fx1 = _fixture(fixtures, "S01-FX1")
    min_days = spec["params_schema"]["min_list_days"]["default"]
    assert min_days == 60
    features = dict(fx1["features"])
    # 40 < 60（F2）且 ≥30（避免与 NEW_LISTING 混为一谈）
    features["f.list_days"] = 40
    actual = _run_fx(card, spec, fx1, market_rules, feature_keys, features=features)
    assert "F2" not in actual["rule_ids_passed"]
    assert actual["state"] == "not_triggered"
    assert actual["action"] == "wait"
    # 对照：原夹具 F2 通过且 entry_ok
    baseline = _run_fx(card, spec, fx1, market_rules, feature_keys)
    assert "F2" in baseline["rule_ids_passed"]
    assert baseline["state"] == "entry_ok"


def _synthetic_buy_signal() -> SignalInput:
    eid = "tt63-fic-e1"
    return SignalInput.model_validate(
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


def test_s12_st_excluded_via_assess() -> None:
    """买入路径：主表 risk_flag=st 时 execution.assess 记 ST_OR_DELISTING。"""
    content = _synthetic_buy_signal()
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


@pytest.mark.xfail(
    reason=(
        "功能缺口：S-01 官方卡 universe 含叙述性 exclude 键（screen_membership 只允许 "
        "boards/pool/security_types），pool 字面为「全市场（持仓 ∪ 自选优先）」不在允许池，"
        "screen:null 无生产改写。实测诊断 universe_not_defined_or_supported，"
        "持仓/自选也无法入选。另缺 security_types，persist 类型校验也会全拒。"
        "应由后端补 screen:null 规范化，本单不改 src。"
    ),
    strict=True,
)
def test_s12_s20_official_card_fields_admit_holdings_and_watchlist(
    s01: tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]],
) -> None:
    """官方卡字段（含 screen:null）直通生产 screen_membership，必须只扫持仓 ∪ 自选。"""
    card, spec, _fx = s01
    assert spec.get("screen") is None
    assert card.get("screen") is None
    universe = card["universe"]
    mount = str(card.get("mount_policy") or "user")
    # 持仓应入选
    assert (
        _admit(universe, quantity=100, on_watchlist=False, mount_policy=mount, proposed_action="buy")
        is None
    )
    # 自选应入选
    assert (
        _admit(universe, quantity=0, on_watchlist=True, mount_policy=mount, proposed_action="buy")
        is None
    )
    # 非持仓且非自选应排除
    assert (
        _admit(universe, quantity=0, on_watchlist=False, mount_policy=mount, proposed_action="buy")
        == "outside_universe"
    )


def test_s12_tamper_full_market_admitted_self_fails(
    s01: tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """篡改反验：把允许池加上「全市场」后，S12 拒绝全市场扫描的断言必须 FAIL。"""
    card, _spec, _fx = s01
    uni = _v1_holdings_watch_universe(card["universe"])
    _assert_s12_s20_pool_is_holdings_union_watchlist(uni)
    monkeypatch.setattr(
        screen_mod,
        "_ALLOWED_POOLS",
        frozenset({"持仓", "持仓 ∪ 自选", "全市场", "全市场（持仓 ∪ 自选优先）"}),
    )
    with pytest.raises(AssertionError):
        _assert_s12_s20_pool_is_holdings_union_watchlist(uni)


# ---- S20 运行侧 screen:null ------------------------------------------------


def _assert_s20_screen_null_not_full_market(spec: dict[str, Any], card: dict[str, Any]) -> None:
    assert spec.get("screen") is None
    assert card.get("screen") is None
    # 运行侧不得把全市场字面池放行（无论是否带「持仓∪自选优先」修饰）
    for pool in ("全市场", "全市场（持仓 ∪ 自选优先）", None):
        diag = _admit(
            {"pool": pool, "boards": {"main": True}, "security_types": ["stock"]},
            quantity=100,
            on_watchlist=True,
            mount_policy="user",
            proposed_action="buy",
        )
        assert diag == "universe_pool_not_supported", f"pool={pool!r} 被放行: {diag}"


def test_s20_official_card_screen_is_null(
    s01: tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]],
) -> None:
    card, spec, _fx = s01
    _assert_s20_screen_null_not_full_market(spec, card)


def test_s20_when_normalized_pool_admits_holdings_and_watchlist_only(
    s01: tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]],
) -> None:
    card, spec, _fx = s01
    assert spec.get("screen") is None
    _assert_s12_s20_pool_is_holdings_union_watchlist(_v1_holdings_watch_universe(card["universe"]))


def test_s20_tamper_full_market_pool_self_fails(
    s01: tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """篡改反验：允许「全市场…」字面池后，S20「screen:null 不得全市场扫描」必须 FAIL。"""
    card, spec, _fx = s01
    _assert_s20_screen_null_not_full_market(spec, card)
    monkeypatch.setattr(
        screen_mod,
        "_ALLOWED_POOLS",
        frozenset({"持仓", "持仓 ∪ 自选", "全市场", "全市场（持仓 ∪ 自选优先）"}),
    )
    with pytest.raises(AssertionError):
        _assert_s20_screen_null_not_full_market(spec, card)
