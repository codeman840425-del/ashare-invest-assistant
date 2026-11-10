# ruff: noqa: S101, E501, PT018
"""T-T78：T-B134 /today 持仓行 t_view 正式契约用例（纯函数，合成数据）。

契约只读参照 ``git show 1fe3ab9:docs/contracts/intraday-bars.md`` §3.7、§3.8，
以及 today-view.md 相关条款。本文件覆盖 11+6+2 中不连库的 17 个用例名；
连库两例见 ``test_tb134_t_view_db_t_t78.py``。

不连库、不出网、不调用麦蕊。合成代码 600000，无真实样本。
"""

from __future__ import annotations

import datetime as dt
import logging
import sys
from decimal import Decimal
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[3] / "src" / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.aggregates import t_view as tv
from app.schemas.enums import DataStatus, GapReason, SecurityType

BJ = dt.timezone(dt.timedelta(hours=8))


def at(hh: int, mm: int, ss: int = 0) -> dt.datetime:
    return dt.datetime(2026, 11, 10, hh, mm, ss, tzinfo=BJ)


def bars(n: int, per: int, price: str = "10", start: tuple[int, int] = (9, 31)) -> list[tv.Bar]:
    first = at(*start)
    return [
        tv.Bar(
            ts=first + dt.timedelta(minutes=i),
            close=Decimal(price),
            volume=Decimal(per),
            amount=Decimal(price) * per,
        )
        for i in range(n)
    ]


def build(**kw: object) -> tv.TView:
    args: dict[str, object] = {
        "code": "600000",
        "security_type": SecurityType.STOCK,
        "base_qty": Decimal(1000),
        "sold_today": Decimal(0),
        "holding_sellable": None,
        # 默认：10:00 累计 6000 股（30 根 × 200），过去 5 日每日 240 分钟 × 100 股
        "bars": bars(30, 200),
        "history": [Decimal(24000)] * 5,
        "now": at(10, 0, 30),
        "trading_day": True,
        "scheduled": False,
        "interval_s": 60,
        "thresholds": None,
    }
    args.update(kw)
    return tv.build(**args)  # type: ignore[arg-type]


# ---- §3.7 十一例 ----


def test_t_view_field_types_and_nullability() -> None:
    out = build().model_dump(mode="json")
    assert set(out) == {
        "vwap",
        "dev_pct",
        "volume_ratio",
        "base_qty",
        "sellable_qty",
        "data_status",
        "as_of",
        "gaps",
    }
    for key in ("vwap", "dev_pct", "volume_ratio", "base_qty", "sellable_qty"):
        assert isinstance(out[key], str)
        Decimal(out[key])
    assert out["base_qty"] == "1000" and out["sellable_qty"] == "1000"
    assert out["as_of"] == "2026-11-10T10:00:00+08:00" and out["gaps"] == []
    assert "dev_pct_threshold" not in out and "volume_ratio_threshold" not in out
    assert out["data_status"] == DataStatus.FRESH.value


def test_t_view_dev_pct_is_percent_4dp() -> None:
    # (10.059 − 10) / 10 × 100 = 0.5900；按未四舍五入的均价计算
    b = [tv.Bar(ts=at(9, 31), close=Decimal("10.059"), volume=Decimal(100), amount=Decimal(1000))]
    v = build(bars=b, now=at(9, 31, 5))
    assert v.dev_pct == "0.5900"
    # 对照：均价 11.25、末收 12 → (12 − 11.25) / 11.25 × 100 = 6.6667
    mixed = [
        tv.Bar(ts=at(9, 31), close=Decimal("10"), volume=Decimal(100), amount=Decimal(1000)),
        tv.Bar(ts=at(9, 32), close=Decimal("11"), volume=Decimal(100), amount=Decimal(1100)),
        tv.Bar(ts=at(9, 33), close=Decimal("12"), volume=Decimal(200), amount=Decimal(2400)),
    ]
    v2 = build(bars=mixed, now=at(9, 33, 30))
    assert (v2.vwap, v2.dev_pct, v2.as_of) == ("11.25", "6.6667", at(9, 33))


def test_t_view_thresholds_absent_until_validated() -> None:
    # 契约 §3.7 ③：本契约不写阈值数值，未验证前不下发键（缺省而非 null）
    assert tv.THRESHOLDS is None
    for th in (
        None,
        tv.Thresholds(dev_pct=Decimal("1"), volume_ratio=Decimal("1"), validated=False),
    ):
        out = build(thresholds=th).model_dump(mode="json")
        assert "dev_pct_threshold" not in out and "volume_ratio_threshold" not in out
    fixture = tv.Thresholds(dev_pct=Decimal("1.5"), volume_ratio=Decimal("3"), validated=True)
    out = build(thresholds=fixture).model_dump(mode="json")
    assert (out["dev_pct_threshold"], out["volume_ratio_threshold"]) == ("1.5", "3")


def test_signals_not_emitted_without_validated_thresholds() -> None:
    # 契约 §3.7：未验证阈值不下发信号。
    # 未验证：T-B134 未实现 vwap_deviation / volume_spike；无 emit_signals API；
    # service 层 scheduled 目前固定 False（M3 未接线）。本例只断言不下发阈值键且无发报辅助。
    assert tv.THRESHOLDS is None
    assert not hasattr(tv, "emit_signals")
    assert not hasattr(tv, "signal_events")
    out = build().model_dump(mode="json")
    assert "dev_pct_threshold" not in out
    assert "volume_ratio_threshold" not in out
    assert "signals" not in out


@pytest.mark.parametrize(
    ("base", "sold", "raw", "expect", "clamped"),
    [
        (1000, 0, 1500, "1000", True),  # 原始可卖 > 底仓
        (1000, 0, -5, "0", True),  # 原始可卖为负
        (1000, 0, 1000, "1000", False),  # 等于底仓：不算截断
        (1000, 0, 0, "0", False),
        (1000, 300, 900, "700", False),  # ≤ 底仓但 > 底仓 − 已卖：取小，不报不一致
        (1000, 1200, None, "0", True),  # 无快照可卖：原始 = 底仓 − 已卖 为负
    ],
)
def test_t_view_sellable_clamped_with_gap(
    base: int,
    sold: int,
    raw: int | None,
    expect: str,
    clamped: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    v = build(
        base_qty=Decimal(base),
        sold_today=Decimal(sold),
        holding_sellable=None if raw is None else Decimal(raw),
    )
    assert v.sellable_qty == expect
    gap = [g for g in v.gaps if g.key == "t_view.sellable_qty"]
    if clamped:
        assert [(g.reason, g.message) for g in gap] == [
            (GapReason.UPSTREAM_ERROR, "可卖数量与底仓不一致，已按较小值显示")
        ]
        assert v.data_status is DataStatus.PARTIAL
        assert "t_view_sellable_exceeds_base:600000" in caplog.text
    else:
        assert gap == [] and v.data_status is DataStatus.FRESH


@pytest.mark.parametrize(
    ("kw", "key"),
    [
        ({"security_type": SecurityType.ETF}, "t_view.security_type"),
        ({"base_qty": Decimal(0)}, "t_view.base_qty"),
        ({"trading_day": False}, "t_view.session"),
        ({"now": at(9, 29, 59), "bars": []}, "t_view.session"),
    ],
)
def test_t_view_not_applicable_keys(kw: dict[str, object], key: str) -> None:
    # 仅断言契约已写明的四项；多项同时成立时的优先级未验证（T-B134 待裁定 3），本例不测。
    # security_type is None 是否走同一键：未验证，不在本参数表。
    v = build(**kw)
    assert v.data_status is DataStatus.UNAVAILABLE
    assert [(g.key, g.reason) for g in v.gaps] == [(key, GapReason.NOT_APPLICABLE)]
    assert (v.vwap, v.dev_pct, v.volume_ratio, v.base_qty, v.sellable_qty, v.as_of) == (None,) * 6


def test_t_view_stale_after_twice_interval_in_session() -> None:
    # 过期条件是 as_of < now − 2×interval_s，相等仍为 FRESH
    assert build(now=at(10, 2, 0)).data_status is DataStatus.FRESH  # 恰好 120 秒
    stale = build(now=at(10, 2, 1))
    assert stale.data_status is DataStatus.STALE and stale.volume_ratio == "2.00"
    assert build(now=at(10, 10, 0), interval_s=300).data_status is DataStatus.FRESH  # 5 分钟档 600 秒
    assert build(now=at(10, 10, 1), interval_s=300).data_status is DataStatus.STALE
    # 下午已开盘仍停在 11:30
    assert build(now=at(13, 5), bars=bars(120, 100)).data_status is DataStatus.STALE


def test_t_view_not_stale_lunch_and_after_close() -> None:
    assert build(now=at(12, 59, 59), bars=bars(120, 100)).data_status is DataStatus.FRESH
    v = build(now=at(16, 0), bars=bars(120, 100) + bars(120, 100, start=(13, 1)))
    assert v.data_status is DataStatus.FRESH and v.as_of == at(15, 0) and v.volume_ratio == "1.00"


def test_t_view_pending_before_first_bar() -> None:
    # 未验证：service 层 scheduled 目前固定 False（M3 未接线）。
    # 「今日分时拉取中」/「今日分时数据未取到」文案待架构确认，本例不断言 gap 文案。
    p = build(bars=[], now=at(9, 30, 20), scheduled=True)
    assert p.data_status is DataStatus.PENDING and p.as_of is None and p.vwap is None
    assert (p.base_qty, p.sellable_qty) == ("1000", "1000")
    u = build(bars=[], now=at(10, 0), scheduled=False)
    assert u.data_status is DataStatus.UNAVAILABLE
    assert [(g.key, g.reason) for g in u.gaps] == [("t_view", GapReason.NO_SOURCE)]


def test_t_view_volume_ratio_null_has_gap() -> None:
    v = build(bars=bars(3, 0), now=at(9, 33, 30))
    assert v.volume_ratio is None
    assert ("t_view.volume_ratio", GapReason.NO_SOURCE, "今日无成交") in [
        (g.key, g.reason, g.message) for g in v.gaps
    ]
    assert v.data_status is DataStatus.PARTIAL


def test_t_view_vwap_2dp_half_up() -> None:
    # 1000.5 / 100 = 10.005 → ROUND_HALF_UP 得 10.01（银行家舍入会得 10.00）
    b = [tv.Bar(ts=at(9, 31), close=Decimal("10"), volume=Decimal(100), amount=Decimal("1000.5"))]
    assert build(bars=b, now=at(9, 31, 5)).vwap == "10.01"


# ---- §3.8 量比六例中的纯函数四例 + 零历史 ----


def test_t_view_volume_ratio_per_minute_avg_240() -> None:
    # Given 过去 5 日各 240 分钟 × 100 股，10:00 今日累计 6000 / Then N=30，量比 2.00
    assert tv.minutes_elapsed(at(10, 0)) == 30
    v = build()
    assert v.volume_ratio == "2.00"
    assert v.data_status is DataStatus.FRESH and v.gaps == []
    # 同一公式 HALF_UP：1 根 09:31 量 1 股、V5 = 8 × 1200 → 1/8=0.125 → 0.13
    assert (
        build(bars=bars(1, 1), now=at(9, 31, 5), history=[Decimal(1920)] * 5).volume_ratio == "0.13"
    )


def test_t_view_volume_ratio_minutes_frozen_at_lunch() -> None:
    assert [
        tv.minutes_elapsed(at(h, m))
        for h, m in [(11, 30), (12, 15), (13, 0), (13, 1), (15, 0), (15, 30)]
    ] == [120, 120, 120, 121, 240, 240]
    # 12:15 时最后一根仍为 11:30：N 按 as_of 取 120
    v = build(bars=bars(120, 100), now=at(12, 15), history=[Decimal(24000)] * 5)
    assert v.as_of == at(11, 30) and v.volume_ratio == "1.00"


def test_t_view_volume_ratio_first_bar_as_is() -> None:
    assert tv.minutes_elapsed(at(9, 31)) == 1
    v = build(bars=bars(1, 5000), now=at(9, 31, 20))
    # (5000 ÷ 1) ÷ (120000 ÷ 1200) = 50.00，竞价量不另加、不另加分钟
    assert v.volume_ratio == "50.00"


def test_t_view_volume_ratio_5min_tier_minutes() -> None:
    assert tv.minutes_elapsed(at(9, 35)) == 5
    v = build(bars=bars(5, 100), now=at(9, 36), interval_s=300)
    assert v.volume_ratio == "1.00" and v.data_status is DataStatus.FRESH


def test_t_view_volume_ratio_zero_history_gap() -> None:
    v = build(history=[Decimal(0)] * 5)
    assert v.volume_ratio is None and v.data_status is DataStatus.PARTIAL
    assert [(g.key, g.reason, g.message) for g in v.gaps] == [
        ("t_view.volume_ratio", GapReason.NO_SOURCE, "历史 5 日无成交")
    ]


# ---- +2：不足 5 日（§3.8 保留）----


def test_t_view_volume_ratio_needs_5_days() -> None:
    v = build(history=[Decimal(24000)] * 3)
    assert v.volume_ratio is None and v.data_status is DataStatus.PARTIAL
    assert [(g.key, g.reason, g.message) for g in v.gaps] == [
        ("t_view.volume_ratio", GapReason.NO_SOURCE, "历史分时不足 5 个交易日")
    ]
