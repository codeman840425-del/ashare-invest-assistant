"""T-B117：GAP1 stale_threshold 只用本段连续竞价样本（先红后绿，离线，不发请求）。"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "probes"))
import p11_gaps as g

# 13:00 段 run-20261109-220540 的 t / recv_bj / lag_s（只读摘录，非原始结果目录）
AHEAD_S = -0.4402
SAMPLES = [
  {
    "src": "real_time_broker",
    "code": "000001",
    "t": "2026-11-10 13:05:36",
    "recv_bj": "2026-11-10T13:05:46.552+08:00",
    "lag_s": 10.553
  },
  {
    "src": "real_time_broker",
    "code": "000001",
    "t": "2026-11-10 13:05:48",
    "recv_bj": "2026-11-10T13:05:54.602+08:00",
    "lag_s": 6.603
  },
  {
    "src": "real_time_broker",
    "code": "000001",
    "t": "2026-11-10 13:05:54",
    "recv_bj": "2026-11-10T13:06:02.469+08:00",
    "lag_s": 8.47
  },
  {
    "src": "real_time_broker",
    "code": "000001",
    "t": "2026-11-10 13:06:03",
    "recv_bj": "2026-11-10T13:06:10.347+08:00",
    "lag_s": 7.348
  },
  {
    "src": "real_time_broker",
    "code": "000001",
    "t": "2026-11-10 13:06:06",
    "recv_bj": "2026-11-10T13:06:18.239+08:00",
    "lag_s": 12.239
  },
  {
    "src": "real_time_broker",
    "code": "000001",
    "t": "2026-11-10 13:06:21",
    "recv_bj": "2026-11-10T13:06:26.313+08:00",
    "lag_s": 5.313
  },
  {
    "src": "real_time_broker",
    "code": "600519",
    "t": "2026-11-10 13:05:35",
    "recv_bj": "2026-11-10T13:05:47.280+08:00",
    "lag_s": 12.281
  },
  {
    "src": "real_time_broker",
    "code": "600519",
    "t": "2026-11-10 13:05:41",
    "recv_bj": "2026-11-10T13:05:55.289+08:00",
    "lag_s": 14.289
  },
  {
    "src": "real_time_broker",
    "code": "600519",
    "t": "2026-11-10 13:05:53",
    "recv_bj": "2026-11-10T13:06:03.084+08:00",
    "lag_s": 10.085
  },
  {
    "src": "real_time_broker",
    "code": "600519",
    "t": "2026-11-10 13:06:02",
    "recv_bj": "2026-11-10T13:06:10.946+08:00",
    "lag_s": 8.947
  },
  {
    "src": "real_time_broker",
    "code": "600519",
    "t": "2026-11-10 13:06:05",
    "recv_bj": "2026-11-10T13:06:19.010+08:00",
    "lag_s": 14.01
  },
  {
    "src": "real_time_broker",
    "code": "600519",
    "t": "2026-11-10 13:06:20",
    "recv_bj": "2026-11-10T13:06:26.915+08:00",
    "lag_s": 6.915
  },
  {
    "src": "real_time_broker",
    "code": "300750",
    "t": "2026-11-10 13:05:36",
    "recv_bj": "2026-11-10T13:05:47.906+08:00",
    "lag_s": 11.907
  },
  {
    "src": "real_time_broker",
    "code": "300750",
    "t": "2026-11-10 13:05:48",
    "recv_bj": "2026-11-10T13:05:55.884+08:00",
    "lag_s": 7.884
  },
  {
    "src": "real_time_broker",
    "code": "300750",
    "t": "2026-11-10 13:05:54",
    "recv_bj": "2026-11-10T13:06:03.736+08:00",
    "lag_s": 9.737
  },
  {
    "src": "real_time_broker",
    "code": "300750",
    "t": "2026-11-10 13:06:00",
    "recv_bj": "2026-11-10T13:06:11.612+08:00",
    "lag_s": 11.613
  },
  {
    "src": "real_time_broker",
    "code": "300750",
    "t": "2026-11-10 13:06:06",
    "recv_bj": "2026-11-10T13:06:19.616+08:00",
    "lag_s": 13.617
  },
  {
    "src": "real_time_broker",
    "code": "300750",
    "t": "2026-11-10 13:06:18",
    "recv_bj": "2026-11-10T13:06:27.607+08:00",
    "lag_s": 9.608
  },
  {
    "src": "real_time_broker",
    "code": "688981",
    "t": "2026-11-10 13:05:44",
    "recv_bj": "2026-11-10T13:05:48.506+08:00",
    "lag_s": 4.506
  },
  {
    "src": "real_time_broker",
    "code": "688981",
    "t": "2026-11-10 13:05:50",
    "recv_bj": "2026-11-10T13:05:56.490+08:00",
    "lag_s": 6.491
  },
  {
    "src": "real_time_broker",
    "code": "688981",
    "t": "2026-11-10 13:05:56",
    "recv_bj": "2026-11-10T13:06:04.347+08:00",
    "lag_s": 8.347
  },
  {
    "src": "real_time_broker",
    "code": "688981",
    "t": "2026-11-10 13:06:02",
    "recv_bj": "2026-11-10T13:06:12.278+08:00",
    "lag_s": 10.279
  },
  {
    "src": "real_time_broker",
    "code": "688981",
    "t": "2026-11-10 13:06:17",
    "recv_bj": "2026-11-10T13:06:20.298+08:00",
    "lag_s": 3.298
  },
  {
    "src": "real_time_broker",
    "code": "688981",
    "t": "2026-11-10 13:06:20",
    "recv_bj": "2026-11-10T13:06:28.217+08:00",
    "lag_s": 8.218
  },
  {
    "src": "real_time_broker",
    "code": "920000",
    "t": "2026-07-16 09:23:33",
    "recv_bj": "2026-11-10T13:05:49.246+08:00",
    "lag_s": 10122136.246
  },
  {
    "src": "real_time_broker",
    "code": "920000",
    "t": "2026-07-16 09:23:33",
    "recv_bj": "2026-11-10T13:05:57.089+08:00",
    "lag_s": 10122144.09
  },
  {
    "src": "real_time_broker",
    "code": "920000",
    "t": "2026-07-16 09:23:33",
    "recv_bj": "2026-11-10T13:06:04.945+08:00",
    "lag_s": 10122151.945
  },
  {
    "src": "real_time_broker",
    "code": "920000",
    "t": "2026-07-16 09:23:33",
    "recv_bj": "2026-11-10T13:06:12.883+08:00",
    "lag_s": 10122159.883
  },
  {
    "src": "real_time_broker",
    "code": "920000",
    "t": "2026-07-16 09:23:33",
    "recv_bj": "2026-11-10T13:06:20.950+08:00",
    "lag_s": 10122167.951
  },
  {
    "src": "real_time_broker",
    "code": "920000",
    "t": "2026-07-16 09:23:33",
    "recv_bj": "2026-11-10T13:06:28.827+08:00",
    "lag_s": 10122175.827
  },
  {
    "src": "ssjy_web",
    "code": "000001",
    "t": "2026-11-10 11:30:57",
    "recv_bj": "2026-11-10T13:05:46.910+08:00",
    "lag_s": 5689.911
  },
  {
    "src": "ssjy_web",
    "code": "000001",
    "t": "2026-11-10 11:30:57",
    "recv_bj": "2026-11-10T13:05:54.906+08:00",
    "lag_s": 5697.907
  },
  {
    "src": "ssjy_web",
    "code": "000001",
    "t": "2026-11-10 11:30:57",
    "recv_bj": "2026-11-10T13:06:02.772+08:00",
    "lag_s": 5705.773
  },
  {
    "src": "ssjy_web",
    "code": "000001",
    "t": "2026-11-10 11:30:57",
    "recv_bj": "2026-11-10T13:06:10.643+08:00",
    "lag_s": 5713.643
  },
  {
    "src": "ssjy_web",
    "code": "000001",
    "t": "2026-11-10 11:30:57",
    "recv_bj": "2026-11-10T13:06:18.636+08:00",
    "lag_s": 5721.636
  },
  {
    "src": "ssjy_web",
    "code": "000001",
    "t": "2026-11-10 11:30:57",
    "recv_bj": "2026-11-10T13:06:26.619+08:00",
    "lag_s": 5729.619
  },
  {
    "src": "ssjy_web",
    "code": "600519",
    "t": "2026-11-10 11:30:57",
    "recv_bj": "2026-11-10T13:05:47.583+08:00",
    "lag_s": 5690.584
  },
  {
    "src": "ssjy_web",
    "code": "600519",
    "t": "2026-11-10 11:30:57",
    "recv_bj": "2026-11-10T13:05:55.592+08:00",
    "lag_s": 5698.593
  },
  {
    "src": "ssjy_web",
    "code": "600519",
    "t": "2026-11-10 11:30:57",
    "recv_bj": "2026-11-10T13:06:03.434+08:00",
    "lag_s": 5706.434
  },
  {
    "src": "ssjy_web",
    "code": "600519",
    "t": "2026-11-10 11:30:57",
    "recv_bj": "2026-11-10T13:06:11.291+08:00",
    "lag_s": 5714.292
  },
  {
    "src": "ssjy_web",
    "code": "600519",
    "t": "2026-11-10 11:30:57",
    "recv_bj": "2026-11-10T13:06:19.313+08:00",
    "lag_s": 5722.313
  },
  {
    "src": "ssjy_web",
    "code": "600519",
    "t": "2026-11-10 11:30:57",
    "recv_bj": "2026-11-10T13:06:27.305+08:00",
    "lag_s": 5730.306
  },
  {
    "src": "ssjy_web",
    "code": "300750",
    "t": "2026-11-10 11:30:57",
    "recv_bj": "2026-11-10T13:05:48.208+08:00",
    "lag_s": 5691.208
  },
  {
    "src": "ssjy_web",
    "code": "300750",
    "t": "2026-11-10 11:30:57",
    "recv_bj": "2026-11-10T13:05:56.187+08:00",
    "lag_s": 5699.188
  },
  {
    "src": "ssjy_web",
    "code": "300750",
    "t": "2026-11-10 11:30:57",
    "recv_bj": "2026-11-10T13:06:04.039+08:00",
    "lag_s": 5707.039
  },
  {
    "src": "ssjy_web",
    "code": "300750",
    "t": "2026-11-10 11:30:57",
    "recv_bj": "2026-11-10T13:06:11.983+08:00",
    "lag_s": 5714.983
  },
  {
    "src": "ssjy_web",
    "code": "300750",
    "t": "2026-11-10 11:30:57",
    "recv_bj": "2026-11-10T13:06:19.995+08:00",
    "lag_s": 5722.996
  },
  {
    "src": "ssjy_web",
    "code": "300750",
    "t": "2026-11-10 11:30:57",
    "recv_bj": "2026-11-10T13:06:27.914+08:00",
    "lag_s": 5730.914
  },
  {
    "src": "ssjy_web",
    "code": "688981",
    "t": "2026-11-10 11:30:57",
    "recv_bj": "2026-11-10T13:05:48.865+08:00",
    "lag_s": 5691.865
  },
  {
    "src": "ssjy_web",
    "code": "688981",
    "t": "2026-11-10 11:30:57",
    "recv_bj": "2026-11-10T13:05:56.786+08:00",
    "lag_s": 5699.786
  },
  {
    "src": "ssjy_web",
    "code": "688981",
    "t": "2026-11-10 11:30:57",
    "recv_bj": "2026-11-10T13:06:04.650+08:00",
    "lag_s": 5707.651
  },
  {
    "src": "ssjy_web",
    "code": "688981",
    "t": "2026-11-10 11:30:57",
    "recv_bj": "2026-11-10T13:06:12.581+08:00",
    "lag_s": 5715.581
  },
  {
    "src": "ssjy_web",
    "code": "688981",
    "t": "2026-11-10 11:30:57",
    "recv_bj": "2026-11-10T13:06:20.601+08:00",
    "lag_s": 5723.601
  },
  {
    "src": "ssjy_web",
    "code": "688981",
    "t": "2026-11-10 11:30:57",
    "recv_bj": "2026-11-10T13:06:28.521+08:00",
    "lag_s": 5731.521
  },
  {
    "src": "ssjy_web",
    "code": "920000",
    "t": "2026-11-10 11:30:57",
    "recv_bj": "2026-11-10T13:05:49.549+08:00",
    "lag_s": 5692.549
  },
  {
    "src": "ssjy_web",
    "code": "920000",
    "t": "2026-11-10 11:30:57",
    "recv_bj": "2026-11-10T13:05:57.392+08:00",
    "lag_s": 5700.392
  },
  {
    "src": "ssjy_web",
    "code": "920000",
    "t": "2026-11-10 11:30:57",
    "recv_bj": "2026-11-10T13:06:05.249+08:00",
    "lag_s": 5708.25
  },
  {
    "src": "ssjy_web",
    "code": "920000",
    "t": "2026-11-10 11:30:57",
    "recv_bj": "2026-11-10T13:06:13.185+08:00",
    "lag_s": 5716.186
  },
  {
    "src": "ssjy_web",
    "code": "920000",
    "t": "2026-11-10 11:30:57",
    "recv_bj": "2026-11-10T13:06:21.252+08:00",
    "lag_s": 5724.253
  },
  {
    "src": "ssjy_web",
    "code": "920000",
    "t": "2026-11-10 11:30:57",
    "recv_bj": "2026-11-10T13:06:29.246+08:00",
    "lag_s": 5732.246
  }
]


def _attach(rows: list) -> dict:
    """按源归组并补 in_session，供 session_lags / lag_quantiles 使用。"""
    by = {}
    for r in rows:
        ts = g.parse_bj(r["t"])
        recv = datetime.fromisoformat(r["recv_bj"])
        item = {**r, "in_session": g.same_auction_session(ts, recv)}
        by.setdefault(r["src"], {}).setdefault(r["code"], []).append(item)
    return by


def _per_source(by: dict, only_session: bool) -> dict:
    out = {}
    for src, codes in by.items():
        lags = []
        for ss in codes.values():
            if only_session:
                lags.extend(g.session_lags(ss))
            else:
                lags.extend(s["lag_s"] for s in ss if s["lag_s"] is not None)
        out[src] = g.lag_quantiles(lags, AHEAD_S)
    return out


@pytest.fixture(scope="module")
def grouped() -> dict:
    return _attach(SAMPLES)


def test_parse_bj_asia_shanghai_not_unit_or_date_bug() -> None:
    """920000 券商源 t 已是完整北京时间日期，不是时区/日期补全/毫秒误解析。"""
    ts = g.parse_bj("2026-07-16 09:23:33")
    if not (ts is not None):
        raise AssertionError("ts is not None")
    if not (ts.utcoffset().total_seconds() == 8 * 3600):
        raise AssertionError("ts.utcoffset().total_seconds() == 8 * 3600")
    if not ((ts.year, ts.month, ts.day, ts.hour, ts.minute, ts.second) == (2026, 7, 16, 9, 23, 33)):
        raise AssertionError(
            "(ts.year, ts.month, ts.day, ts.hour, ts.minute, ts.second) == (2026, 7, 16, 9, 23, 33)"
        )
    live = g.parse_bj("2026-11-10 13:05:36")
    if not (live.hour == 13 and live.tzinfo is not None):
        raise AssertionError("live.hour == 13 and live.tzinfo is not None")
    # 秒级字符串不把毫秒当 unix；时间-only 不瞎补日期
    if g.parse_bj("13:05:36") is not None:
        raise AssertionError("g.parse_bj('13:05:36') is None")


def test_red_unfiltered_p95_distorted(grouped: dict) -> None:
    """红：把 920000 7 月旧票与 ssjy 午休冻结计入池，ref_p95 约 1012 万秒。"""
    thr = g.stale_threshold(_per_source(grouped, only_session=False))
    if not (thr["ref_p95_s"] is not None and thr["ref_p95_s"] > 1_000_000):
        raise AssertionError("thr['ref_p95_s'] is not None and thr['ref_p95_s'] > 1000000")
    if not (thr["suggested_s"] > 1_000_000):
        raise AssertionError("thr['suggested_s'] > 1000000")


def test_green_session_filter_reasonable(grouped: dict) -> None:
    """绿：只保留与收到时刻同段连续竞价的样本后，参考 p95 约 14.4s，建议值 29s。"""
    by = grouped
    # 券商 920000 与全部 ssjy 均不在下午时段
    if not (all(not s["in_session"] for s in by["real_time_broker"]["920000"])):
        raise AssertionError("all((not s['in_session'] for s in by['real_time_broker']['920000']))")
    if not (all(not s["in_session"] for ss in by["ssjy_web"].values() for s in ss)):
        raise AssertionError(
            "all((not s['in_session'] for ss in by['ssjy_web'].values() for s in ss))"
        )
    if not (sum(1 for ss in by["real_time_broker"].values() for s in ss if s["in_session"]) == 24):
        raise AssertionError(
            "sum((1 for ss in by['real_time_broker'].values() for s "
            "in ss if s['in_session'])) == 24"
        )
    thr = g.stale_threshold(_per_source(by, only_session=True))
    if not (thr["ref_p95_s"] == 14.391):
        raise AssertionError("thr['ref_p95_s'] == 14.391")
    if not (thr["basis"] == "ntp_corrected_p95"):
        raise AssertionError("thr['basis'] == 'ntp_corrected_p95'")
    if not (thr["suggested_s"] == 29):
        raise AssertionError("thr['suggested_s'] == 29")
    if not (1 < thr["ref_p95_s"] < 120):
        raise AssertionError("1 < thr['ref_p95_s'] < 120")
