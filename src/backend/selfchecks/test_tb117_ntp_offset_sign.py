"""T-B117：NTP 偏差符号约定（离线，不访问 NTP 服务器）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "probes"))
import p11_gaps as g  # noqa: E402

# 13:00 段 ntp_pre.txt 中的 /dataonly 数值行（ASCII，不读原始结果目录、不访问 ntp.aliyun.com）
W32TM_PRE = (
    "22:05:36, -00.4414716s\n"
    "22:05:38, -00.4405399s\n"
    "22:05:40, -00.4387174s\n"
)


def test_w32tm_negative_means_local_clock_slow():
    """任务事实：本机比 ntp.aliyun.com 慢约 0.44s；w32tm 输出为负。探针约定正值=本机快。"""
    vals = g.parse_w32tm(W32TM_PRE)
    assert vals == [-00.4414716, -00.4405399, -00.4387174]
    ahead = round(sum(vals) / len(vals), 4)
    assert ahead == -0.4402
    # RFC 5905 / 常见实现：offset = server − local（应加到本机上的秒数）
    rfc5905 = round(-ahead, 4)
    assert rfc5905 == 0.4402
    assert rfc5905 == -ahead


def test_lag_correction_when_local_is_slow():
    """本机慢时未修正 lag 偏小；真实延迟 = lag − local_ahead_s = lag + 0.4402。不翻转既有字段。"""
    ahead = -0.4402
    lag = 10.182
    corrected = round(lag - ahead, 3)
    assert corrected == 10.622
    assert corrected > lag


def test_convention_opposite_rfc5905_not_flipped():
    """local_ahead_s 含义保持「本机 − NTP」；rfc5905_offset_s 仅为对照，不改契约。"""
    # 与 item1 写入的 convention / rfc5905_offset_s 一致
    ahead = -0.4402
    rfc = round(-ahead, 4)
    assert rfc == 0.4402
    # 若把 w32tm 负值误当成 RFC offset 去减，修正会走反
    wrong = round(10.182 - 0.4402, 3)
    right = round(10.182 - ahead, 3)
    assert wrong < 10.182 < right
