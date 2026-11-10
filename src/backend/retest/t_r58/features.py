"""逐根特征与严格向后回看，出处：方案 §1、§2.2、§2.4。"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from .sim import Event

SLOT_END = [
    f"{minute // 60:02d}:{minute % 60:02d}"
    for start in (9 * 60 + 31, 13 * 60 + 1)
    for minute in range(start, start + 120)
]


def minutes_elapsed(hhmm: str) -> int:
    hour, minute = map(int, hhmm.split(":"))
    t = hour * 60 + minute
    if t <= 11 * 60 + 30:
        return max(t - (9 * 60 + 30), 0)
    if t <= 13 * 60:
        return 120
    return min(120 + t - 13 * 60, 240)


def bar_ok(
    o: np.ndarray, h: np.ndarray, l: np.ndarray, c: np.ndarray,  # noqa: E741  §1 接口字段
    v: np.ndarray, a: np.ndarray,
) -> np.ndarray:
    present = ~np.isnan(np.stack((o, h, l, c, v, a))).any(axis=0)
    avg = np.divide(a, v, out=np.full_like(a, np.nan, dtype=float), where=v > 0)
    # §2.2 第 3 条：仅对正成交量检查额量价，零量必须零额。
    return present & (
        ((v == 0) & (a == 0))
        | ((v > 0) & (avg >= l * (1 - 0.001)) & (avg <= h * (1 + 0.001)))
    )


def day_features(
    o: np.ndarray, h: np.ndarray, l: np.ndarray, c: np.ndarray,  # noqa: E741  §1 接口字段
    v: np.ndarray, a: np.ndarray,
) -> dict[str, np.ndarray]:
    valid = bar_ok(o, h, l, c, v, a)
    cumvol = np.cumsum(np.where(valid, v, 0.0))
    cumamt = np.cumsum(np.where(valid, a, 0.0))
    nbars = np.cumsum(valid)
    vwap = np.divide(
        cumamt, cumvol, out=np.full(len(c), np.nan), where=valid & (cumvol != 0),
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        dev = (c - vwap) / vwap
    # §1、§9 L1：按已完成有效 bar 的累计和求样本方差，不使用未来收益。
    sigma = np.full(len(c), np.nan)
    idx = np.flatnonzero(valid)
    if idx.size:
        cv = c[idx]
        with np.errstate(divide="ignore", invalid="ignore"):
            ret = np.log(cv / np.r_[o[idx[0]], cv[:-1]])
        n = np.arange(1, idx.size + 1)
        s1, s2 = np.cumsum(ret), np.cumsum(ret * ret)
        with np.errstate(divide="ignore", invalid="ignore"):
            var = (s2 - s1 * s1 / n) / (n - 1)
        out = np.sqrt(np.maximum(var, 0.0)) * np.sqrt(n)
        out[n < 2] = np.nan
        sigma[idx] = out
    return {
        "valid": valid, "cumvol": cumvol, "cumamt": cumamt, "vwap": vwap,
        "dev": dev, "nbars": nbars, "sigma": sigma,
    }


def _decimal(value: float) -> Decimal:
    # §1：整数不经浮点转换，其余从十进制 repr 构造。
    if isinstance(value, (int, np.integer)):
        return Decimal(int(value))
    return Decimal(repr(float(value)))


def vr_rounded(v_today: float, n: int, v5: float | None) -> Decimal | None:
    if v5 is None or v5 == 0 or n == 0 or np.isnan(v5):
        return None
    value = (_decimal(v_today) / Decimal(int(n))) / (_decimal(v5) / Decimal(1200))
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def lookbacks(
    dates: list[date], day_vol: np.ndarray, day_amt: np.ndarray,
    traded: np.ndarray, events: list[Event],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    v5 = np.full(len(dates), np.nan)
    adv20 = np.full(len(dates), np.nan)
    adv_cnt = np.zeros(len(dates), dtype=int)
    history: list[int] = []
    for t, current in enumerate(dates):
        past = history[-20:]
        adv_cnt[t] = len(past)
        if past:
            adv20[t] = np.mean(day_amt[past])
        if len(history) >= 5:
            total = 0.0
            for d in history[-5:]:
                adjusted = float(day_vol[d])
                for e in events:
                    if dates[d] < e.ex_date <= current:
                        adjusted *= 1 + e.s + e.r
                total += adjusted
            v5[t] = total
        if traded[t]:
            history.append(t)
    return v5, adv20, adv_cnt
