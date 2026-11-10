# ruff: noqa: S101
"""T-T61 / T-B117：stale_threshold 只用同一连续竞价时段；边界先红后绿（离线，不发请求）。"""

from __future__ import annotations

import inspect
import os
import statistics
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src/backend/probes"))
import p11_gaps as g  # noqa: E402

RUN_NAME = "run-20261109-220540"
# 与产品自测及 13:00 段结果一致的构造边界（不嵌入探针原始目录）
BJ = g.BJ
T_LIVE = datetime(2026, 11, 10, 13, 5, 36, tzinfo=BJ)
T_LUNCH = datetime(2026, 11, 10, 11, 30, 57, tzinfo=BJ)
T_OLD = datetime(2026, 7, 16, 9, 23, 33, tzinfo=BJ)
RECV_PM = datetime(2026, 11, 10, 13, 5, 49, tzinfo=BJ)


def _require_session_api() -> None:
    assert hasattr(g, "same_auction_session"), (
        "p11_gaps.same_auction_session 不存在：T-B117 未合入（9cccbd7 预期红）"
    )


def _run_dir() -> Path:
    env = os.environ.get("TT61_P11_RUN")
    candidates = []
    if env:
        candidates.append(Path(env))
    candidates.append(ROOT / "src/backend/probes/results" / RUN_NAME)
    candidates.append(
        Path("/workspace/ashare-invest-assistant/src/backend/probes/results") / RUN_NAME
    )
    for p in candidates:
        if (p / "p11_gaps.json").is_file():
            return p
    pytest.skip(
        f"{RUN_NAME} 不在工作树且未设置 TT61_P11_RUN；本单只用已有结果文件，不重跑探针"
    )


def test_cross_lunch_break_not_same_session() -> None:
    """跨午休：下午收到时刻与 11:30:57 冻结票不同段；与下午盘中 t 同段。"""
    _require_session_api()
    assert g.same_auction_session(T_LIVE, RECV_PM) is True
    assert g.same_auction_session(T_LUNCH, RECV_PM) is False
    assert g.same_auction_session(T_LIVE, RECV_PM.replace(hour=10)) is False


def test_old_date_source_not_same_session() -> None:
    """旧日期源（7 月 t、11 月收到）不得计入本段。"""
    _require_session_api()
    assert g.same_auction_session(T_OLD, RECV_PM) is False
    assert T_OLD.date() != RECV_PM.date()


def test_empty_session_segment_threshold_is_none() -> None:
    """空段：过滤后无同段样本时 ref_p95 / suggested 均为 None。"""
    _require_session_api()
    assert hasattr(g, "session_lags")
    rows = [
        {"lag_s": 12.0, "in_session": False},
        {"lag_s": 10122136.0, "in_session": False},
        {"lag_s": None, "in_session": True},
    ]
    assert g.session_lags(rows) == []
    assert g.session_lags([]) == []
    thr = g.stale_threshold({"ssjy_web": g.lag_quantiles([], -0.4402)})
    assert thr["ref_p95_s"] is None
    assert thr["suggested_s"] is None
    assert thr["basis"] is None


def test_recalc_run_20261109_220540_session_p95() -> None:
    """用已有 run-20261109-220540 重算：只计同段样本，ref_p95_s=14.391，建议 29s。"""
    _require_session_api()
    import json

    run = _run_dir()
    ahead_vals = g.parse_w32tm((run / "ntp_pre.txt").read_text(encoding="utf-8"))
    ahead = round(statistics.fmean(ahead_vals), 4)
    assert ahead == -0.4402
    data = json.loads((run / "p11_gaps.json").read_text(encoding="utf-8"))
    item = next(it for it in data if it.get("name") == "GAP1_snapshot_latency")
    samples = item["evidence"]["samples"]
    per: dict = {}
    n_sess = n_excl = 0
    for src, by_code in samples.items():
        sess: list[float] = []
        for ss in by_code.values():
            for s in ss:
                ts = g.parse_bj(s.get("t")) if s.get("t") else None
                recv = datetime.fromisoformat(s["recv_bj"]) if s.get("recv_bj") else None
                lag = s.get("lag_s")
                if lag is not None and g.same_auction_session(ts, recv):
                    sess.append(lag)
                    n_sess += 1
                elif lag is not None:
                    n_excl += 1
        per[src] = g.lag_quantiles(sess, ahead)
    thr = g.stale_threshold(per)
    assert n_sess == 24 and n_excl == 36
    assert thr["ref_p95_s"] == 14.391
    assert thr["basis"] == "ntp_corrected_p95"
    assert thr["suggested_s"] == 29


def test_local_ahead_and_rfc5905_offset_opposite() -> None:
    """local_ahead_s 与新增 rfc5905_offset_s 符号相反且数值一致；字段含义未翻转。"""
    src = inspect.getsource(g.item1_latency)
    assert "rfc5905_offset_s" in src, "item1_latency 未写入 rfc5905_offset_s（9cccbd7 预期红）"
    vals = g.parse_w32tm(
        "22:05:36, -00.4414716s\n22:05:38, -00.4405399s\n22:05:40, -00.4387174s\n"
    )
    ahead = round(statistics.fmean(vals), 4)
    rfc = round(-ahead, 4)
    assert ahead == -0.4402
    assert rfc == 0.4402
    assert rfc == -ahead
    assert (ahead < 0) and (rfc > 0)
    # 本机慢时真实延迟 = lag − local_ahead_s，应大于未修正值
    lag = 10.182
    assert round(lag - ahead, 3) == 10.622
