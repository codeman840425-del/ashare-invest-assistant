"""T-B118：dry-run 强制盘中在盘后墙钟下仍计入活样本，且不放进午休/隔夜旧票。离线，不发请求。"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "probes"))
import p11_gaps as g

BJ = g.BJ
RECV_AH = datetime(2026, 11, 10, 15, 40, tzinfo=BJ)  # 工作日收盘后
T_LIVE = RECV_AH - timedelta(seconds=3)
T_LUNCH = datetime(2026, 11, 10, 11, 30, 57, tzinfo=BJ)
T_OLD = datetime(2026, 7, 16, 9, 23, 33, tzinfo=BJ)
RECV_PM = datetime(2026, 11, 10, 13, 5, 49, tzinfo=BJ)
T_PM = datetime(2026, 11, 10, 13, 5, 36, tzinfo=BJ)


def test_red_after_hours_plain_session_excludes_live_mock_tick() -> None:
    """红：只按 same_auction_session，盘后收到时刻会把 mock 的「现在−3s」活样本全部排除。"""
    if g.same_auction_session(T_LIVE, RECV_AH):
        raise AssertionError("not g.same_auction_session(T_LIVE, RECV_AH)")
    if g.is_bj_session(RECV_AH):
        raise AssertionError("not g.is_bj_session(RECV_AH)")


def test_green_force_session_keeps_live_excludes_stale() -> None:
    """绿：FORCE_SESSION 平移后，活样本计入，11:30:57 与 7 月旧票仍排除；盘中路径不变。"""
    if not (g.in_session_for_threshold(T_LIVE, RECV_AH, True)):
        raise AssertionError("g.in_session_for_threshold(T_LIVE, RECV_AH, True)")
    if g.in_session_for_threshold(T_LUNCH, RECV_AH, True):
        raise AssertionError("not g.in_session_for_threshold(T_LUNCH, RECV_AH, True)")
    if g.in_session_for_threshold(T_OLD, RECV_AH, True):
        raise AssertionError("not g.in_session_for_threshold(T_OLD, RECV_AH, True)")
    if not (g.in_session_for_threshold(T_PM, RECV_PM, True)):
        raise AssertionError("g.in_session_for_threshold(T_PM, RECV_PM, True)")
    if g.in_session_for_threshold(T_LUNCH, RECV_PM, True):
        raise AssertionError("not g.in_session_for_threshold(T_LUNCH, RECV_PM, True)")
    # 非强制时行为与 same_auction_session 相同
    if g.in_session_for_threshold(T_PM, RECV_PM, False) is not g.same_auction_session(
        T_PM, RECV_PM
    ):
        raise AssertionError(
            'g.in_session_for_threshold(T_PM, RECV_PM, False) is g.s'
            'ame_auction_session(T_PM, RECV_PM)'
        )
    if g.in_session_for_threshold(T_LIVE, RECV_AH, False) is not g.same_auction_session(
        T_LIVE, RECV_AH
    ):
        raise AssertionError(
            'g.in_session_for_threshold(T_LIVE, RECV_AH, False) is g'
            '.same_auction_session(T_LIVE, RECV_AH)'
        )
