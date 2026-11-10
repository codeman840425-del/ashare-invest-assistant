# ruff: noqa: S101, E501, PT018
"""T-B134：/today 持仓行 t_view 的纯函数自检（合成数据，不连库、不出网、不调用麦蕊）。

契约只读参照 ``git show 1fe3ab9:docs/contracts/intraday-bars.md`` §3.7（T-A145）、§3.8（T-A146）。
用例名与契约 §3.7「本节验收用例名」、§3.8「新增用例」、§5.1 M4 对应；正式用例由测试在 tests/ 下另写。
"""

from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal

import pytest

from app.aggregates import t_view as tv
from app.schemas.enums import DataStatus, GapReason, SecurityType

BJ = dt.timezone(dt.timedelta(hours=8))
DAY = dt.date(2026, 11, 10)


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


# ---- §3.8 量比 ----


def test_t_view_volume_ratio_per_minute_avg_240() -> None:
    v = build()
    assert tv.minutes_elapsed(at(10, 0)) == 30
    assert v.volume_ratio == "2.00"
    assert v.data_status is DataStatus.FRESH and v.gaps == []


def test_t_view_volume_ratio_minutes_frozen_at_lunch() -> None:
    assert [
        tv.minutes_elapsed(at(h, m))
        for h, m in [(11, 30), (12, 15), (13, 0), (13, 1), (15, 0), (15, 30)]
    ] == [120, 120, 120, 121, 240, 240]
    # 12:15 时最后一根仍为 11:30 的 bar：N 按 as_of 取 120
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


def test_t_view_volume_ratio_needs_5_days() -> None:
    v = build(history=[Decimal(24000)] * 3)
    assert v.volume_ratio is None and v.data_status is DataStatus.PARTIAL
    assert [(g.key, g.reason, g.message) for g in v.gaps] == [
        ("t_view.volume_ratio", GapReason.NO_SOURCE, "历史分时不足 5 个交易日")
    ]


def test_t_view_volume_ratio_zero_history_gap() -> None:
    v = build(history=[Decimal(0)] * 5)
    assert v.volume_ratio is None and v.data_status is DataStatus.PARTIAL
    assert [(g.key, g.message) for g in v.gaps] == [("t_view.volume_ratio", "历史 5 日无成交")]


def test_t_view_volume_ratio_null_has_gap() -> None:
    v = build(bars=bars(3, 0), now=at(9, 33, 30))
    assert v.volume_ratio is None
    assert ("t_view.volume_ratio", GapReason.NO_SOURCE, "今日无成交") in [
        (g.key, g.reason, g.message) for g in v.gaps
    ]
    assert v.data_status is DataStatus.PARTIAL


def test_t_view_volume_ratio_half_up_2dp() -> None:
    # 1 根 9:31 量 1 股、V5 = 8 × 1200 → 1 ÷ 8 = 0.125 → 0.13（ROUND_HALF_UP，银行家舍入会得 0.12）
    assert (
        build(bars=bars(1, 1), now=at(9, 31, 5), history=[Decimal(1920)] * 5).volume_ratio == "0.13"
    )


# ---- §3.7 ②⑧ 均价与偏离 ----


def test_t_view_vwap_and_dev() -> None:
    b = [
        tv.Bar(ts=at(9, 31), close=Decimal("10"), volume=Decimal(100), amount=Decimal(1000)),
        tv.Bar(ts=at(9, 32), close=Decimal("11"), volume=Decimal(100), amount=Decimal(1100)),
        tv.Bar(ts=at(9, 33), close=Decimal("12"), volume=Decimal(200), amount=Decimal(2400)),
    ]
    v = build(bars=b, now=at(9, 33, 30))
    # vwap = 4500 / 400 = 11.25；dev = (12 − 11.25) / 11.25 × 100 = 6.6667
    assert (v.vwap, v.dev_pct, v.as_of) == ("11.25", "6.6667", at(9, 33))


def test_t_view_dev_pct_is_percent_4dp() -> None:
    b = [tv.Bar(ts=at(9, 31), close=Decimal("10.059"), volume=Decimal(100), amount=Decimal(1000))]
    assert build(bars=b, now=at(9, 31, 5)).dev_pct == "0.5900"


def test_t_view_vwap_2dp_half_up() -> None:
    b = [tv.Bar(ts=at(9, 31), close=Decimal("10"), volume=Decimal(100), amount=Decimal("1000.5"))]
    assert build(bars=b, now=at(9, 31, 5)).vwap == "10.01"


# ---- §3.7 ①③ 字段与阈值 ----


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


def test_t_view_thresholds_absent_until_validated() -> None:
    assert tv.THRESHOLDS is None  # 契约 §3.7 ③：本契约不写数值，T-R58 复测前不下发
    for th in (
        None,
        tv.Thresholds(dev_pct=Decimal("1"), volume_ratio=Decimal("1"), validated=False),
    ):
        out = build(thresholds=th).model_dump(mode="json")
        assert "dev_pct_threshold" not in out and "volume_ratio_threshold" not in out
    fixture = tv.Thresholds(dev_pct=Decimal("1.5"), volume_ratio=Decimal("3"), validated=True)
    out = build(thresholds=fixture).model_dump(mode="json")
    assert (out["dev_pct_threshold"], out["volume_ratio_threshold"]) == ("1.5", "3")


# ---- §3.7 ④ 截断 ----


def test_t_view_sellable_is_base_minus_sold_today() -> None:
    # 昨日底仓 1000、今日卖 300（今日买入 500 不进 base_qty）→ 700
    v = build(base_qty=Decimal(1000), sold_today=Decimal(300), holding_sellable=Decimal(700))
    assert (v.base_qty, v.sellable_qty, v.gaps) == ("1000", "700", [])


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


# ---- §3.7 ⑤ 不适用 ----


@pytest.mark.parametrize(
    ("kw", "key"),
    [
        ({"security_type": SecurityType.ETF}, "t_view.security_type"),
        ({"security_type": None}, "t_view.security_type"),
        ({"base_qty": Decimal(0)}, "t_view.base_qty"),
        ({"trading_day": False}, "t_view.session"),
        ({"now": at(9, 29, 59), "bars": []}, "t_view.session"),
        (
            {"security_type": SecurityType.ETF, "base_qty": Decimal(0), "trading_day": False},
            "t_view.security_type",
        ),
    ],
)
def test_t_view_not_applicable_keys(kw: dict[str, object], key: str) -> None:
    v = build(**kw)
    assert v.data_status is DataStatus.UNAVAILABLE
    assert [(g.key, g.reason) for g in v.gaps] == [
        (key, GapReason.NOT_APPLICABLE)
    ]  # 只有一项（T-A146）
    assert (v.vwap, v.dev_pct, v.volume_ratio, v.base_qty, v.sellable_qty, v.as_of) == (None,) * 6


# ---- §3.7 ⑥ 状态 ----


def test_t_view_stale_after_twice_interval_in_session() -> None:
    assert build(now=at(10, 2, 0)).data_status is DataStatus.FRESH  # 恰好 120 秒：不过期
    stale = build(now=at(10, 2, 1))
    assert stale.data_status is DataStatus.STALE and stale.volume_ratio == "2.00"
    assert (
        build(now=at(10, 10, 0), interval_s=300).data_status is DataStatus.FRESH
    )  # 5 分钟档 600 秒
    assert build(now=at(10, 10, 1), interval_s=300).data_status is DataStatus.STALE
    assert (
        build(now=at(13, 5), bars=bars(120, 100)).data_status is DataStatus.STALE
    )  # 下午已开盘仍停在 11:30


def test_t_view_not_stale_lunch_and_after_close() -> None:
    assert build(now=at(12, 59, 59), bars=bars(120, 100)).data_status is DataStatus.FRESH
    v = build(now=at(16, 0), bars=bars(120, 100) + bars(120, 100, start=(13, 1)))
    assert v.data_status is DataStatus.FRESH and v.as_of == at(15, 0) and v.volume_ratio == "1.00"


def test_t_view_pending_before_first_bar() -> None:
    p = build(bars=[], now=at(9, 30, 20), scheduled=True)
    assert p.data_status is DataStatus.PENDING and p.as_of is None and p.vwap is None
    assert (p.base_qty, p.sellable_qty) == ("1000", "1000")
    u = build(bars=[], now=at(10, 0), scheduled=False)
    assert u.data_status is DataStatus.UNAVAILABLE
    assert [(g.key, g.reason) for g in u.gaps] == [("t_view", GapReason.NO_SOURCE)]


def test_t_view_only_on_today_focus_rows() -> None:
    from app.aggregates import models as m

    assert "t_view" not in m.TerminalRow.model_fields  # /terminal 不变
    row = {
        "security_code": "600000",
        "name": "示例",
        "in_watchlist": False,
        "focus": False,
        "quote": None,
        "holding": None,
        "suggestion": None,
        "active_reason_count": 0,
        "max_risk_level": None,
        "data_status": DataStatus.PARTIAL,
        "data_as_of": None,
    }
    focus = m.Focus(
        items=[m.TodayRow(**row, t_view=build()), m.TodayRow(**row, t_view=None)], more=False
    )
    out = focus.model_dump(mode="json")["items"]
    assert out[1]["t_view"] is None  # 非持仓行为 null（§3.7 ①）
    assert "dev_pct_threshold" not in out[0]["t_view"]  # 嵌套序列化仍缺省阈值字段
    assert out[0]["t_view"]["volume_ratio"] == "2.00"
