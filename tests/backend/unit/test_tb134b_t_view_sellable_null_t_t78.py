"""T-T78 / T-B134b：§3.8 ④「快照没有可卖数量」正式用例（纯函数，合成数据）。

契约：git show a281095:docs/contracts/intraday-bars.md §3.8 ④。
契约只给了 key=t_view.sellable_qty 与 reason=user_input_missing，message 文案待架构确认
（实现暂用「持仓快照无可卖数量，暂不提供可卖数」）。不连库、不出网、不调用麦蕊。
"""

from __future__ import annotations

import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[3] / "src" / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.aggregates import t_view as tv
from app.schemas.enums import DataStatus, GapReason, SecurityType

BJ = dt.timezone(dt.timedelta(hours=8))


def at(hh: int, mm: int, ss: int = 0) -> dt.datetime:
    return dt.datetime(2026, 11, 10, hh, mm, ss, tzinfo=BJ)


def bars(
    n: int, per: int, price: str = "10", start: tuple[int, int] = (9, 31)
) -> list[tv.Bar]:
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
        "base_qty": Decimal(800),
        "sold_today": Decimal(0),
        "holding_sellable": Decimal(800),
        "bars": bars(30, 200),
        "history": [Decimal(24000)] * 5,
        "now": at(10, 0, 30),
        "trading_day": True,
        "scheduled": False,
        "interval_s": 60,
        "thresholds": None,
        "base_source": "snapshot",
        "snapshot_as_of": at(10, 0),
        "sellable_known": False,
    }
    args.update(kw)
    return tv.build(**args)  # type: ignore[arg-type]


def _base_gap(view: tv.TView) -> object | None:
    found = [g for g in view.gaps if g.key == "t_view.base_qty"]
    return found[0] if found else None


def _status_at_least_partial(status: DataStatus) -> bool:
    # 契约：至少 partial；无分时等更差状态也算满足，不发明枚举值。
    return status in {DataStatus.PARTIAL, DataStatus.UNAVAILABLE}


def test_t_view_sellable_null_when_snapshot_unknown() -> None:
    # 无流水、快照无可卖数量：sellable_qty 为 null，不加截断，另有 base_qty gap（时点 10:00）。
    v = build()
    assert v.sellable_qty is None
    assert v.base_qty == "800"
    sellable = [g for g in v.gaps if g.key == "t_view.sellable_qty"]
    assert len(sellable) == 1
    assert sellable[0].reason is GapReason.USER_INPUT_MISSING
    # 未验证 / 待架构确认：契约未给出 message 原文；此处只核对实现现行文案，不作为契约验收。
    assert sellable[0].message == "持仓快照无可卖数量，暂不提供可卖数"
    gap = _base_gap(v)
    assert gap is not None
    assert gap.reason is GapReason.USER_INPUT_MISSING
    assert gap.message == "未导入今日成交流水，底仓按持仓快照计，可能含今日买入"
    assert _status_at_least_partial(v.data_status)

    # as_of 空：同样加 base_qty gap（契约）。
    empty = build(snapshot_as_of=None)
    assert empty.sellable_qty is None
    gap = _base_gap(empty)
    assert gap is not None
    assert gap.reason is GapReason.USER_INPUT_MISSING
    assert gap.message == "未导入今日成交流水，底仓按持仓快照计，可能含今日买入"
    assert _status_at_least_partial(empty.data_status)

    # 09:30:00 含（闭区间）；09:29:59 不加 base_qty gap。
    at_open = build(snapshot_as_of=at(9, 30))
    assert _base_gap(at_open) is not None
    assert (
        _base_gap(at_open).message
        == "未导入今日成交流水，底仓按持仓快照计，可能含今日买入"
    )
    before = build(snapshot_as_of=at(9, 29, 59))
    assert _base_gap(before) is None
    assert before.sellable_qty is None
    assert any(
        g.key == "t_view.sellable_qty" and g.reason is GapReason.USER_INPUT_MISSING
        for g in before.gaps
    )

    # 快照时点早于今日 09:30 仍按字面给可卖 null + gap（T-B134b 待裁定 2，fail closed），不加 base_qty gap。
    prev = dt.datetime(2026, 11, 9, 15, 30, tzinfo=BJ)
    early = build(snapshot_as_of=prev)
    assert early.sellable_qty is None
    assert _base_gap(early) is None
    sellable_early = [g for g in early.gaps if g.key == "t_view.sellable_qty"]
    assert len(sellable_early) == 1
    assert sellable_early[0].reason is GapReason.USER_INPUT_MISSING

    # 对照：可卖已知时不走 null，而走 §3.7 截断。
    known = build(sellable_known=True, holding_sellable=Decimal(800))
    assert known.sellable_qty == "800"
    assert all(g.key != "t_view.sellable_qty" for g in known.gaps)
