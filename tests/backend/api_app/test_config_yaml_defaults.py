"""plan v0.2 §6.1：``config/*.yaml`` 的键与默认值（“YAML 默认值 == 本节表格”，归测试）。

三层比对：
1. 测试内快照 ``config_defaults_v0_2/*.yaml``（plan §6.1 代码块原文）自身可解析、关键默认值正确、
   跨文件一致（不依赖文档、不依赖后端）；
2. 快照 == plan §6.1 代码块（需 v0.2 文档：``AIA_DOCS_DIR``，否则 skip）；
3. 仓库 ``config/*.yaml``（``AIA_CONFIG_DIR``，默认 ``<repo>/config``）== 快照；文件尚未创建时 skip，
   原因写明依赖“T-B01 后续（plan §6.1：文件由后端创建）”。

``market_rules.yaml`` 的第二段在 plan 中只写了 ``effective_from``（注释：除 ``main_board_st: 5`` 外与上一段相同、
文件中写全），所以比对仓库文件时按该注释展开后再比。
"""

from __future__ import annotations

import copy
import os
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.unit]

HERE = Path(__file__).resolve().parent
SNAP_DIR = HERE / "config_defaults_v0_2"
NAMES = ("realtime", "ingest", "market_rules", "risk_controls", "horizon_classifier")
REPO_ROOT = HERE.parents[2]
CONFIG_DIR = Path(os.environ.get("AIA_CONFIG_DIR", REPO_ROOT / "config")).resolve()


def snap(name: str) -> dict[str, Any]:
    return yaml.safe_load((SNAP_DIR / f"{name}.yaml").read_text(encoding="utf-8"))


def plan_blocks(plan: str) -> dict[str, str]:
    sec = plan[plan.index("### 6.1 业务配置文件") : plan.index("## 7. 风险与合规")]
    return dict(re.findall(r"\*\*`config/([a-z_]+)\.yaml`\*\*[^\n]*\n```yaml\n(.*?)```", sec, re.S))


def expanded_market_rules(data: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(data)
    first, second = out["segments"][0], out["segments"][1]
    if set(second) == {"effective_from"}:
        full = copy.deepcopy(first)
        full["effective_from"] = second["effective_from"]
        full["price_limit_pct"]["main_board_st"] = 5
        out["segments"][1] = full
    return out


# ---------------- 1. 快照自检 ----------------
@pytest.mark.parametrize("name", NAMES)
def test_snapshot_parses_with_schema_version(name):
    data = snap(name)
    assert isinstance(data, dict) and data["schema_version"] == 1


def test_key_defaults_realtime():
    d = snap("realtime")
    assert d["intervals"] == {"quote_interval_s": 15, "all_market_interval_s": 60, "pro_tier1_interval_s": 60,
                              "pro_tier2_interval_s": 300, "stale_threshold_s": None}
    assert d["boards"]["bse"] is False and d["boards"]["main"] is True
    assert (d["universe"]["tier1_cap"], d["universe"]["universe_hard_cap"]) == (1500, 4000)
    assert (d["watchlist"]["per_user_cap"], d["watchlist"]["focus_cap"]) == (100, 20)
    assert d["notify"]["cadence_default"] == "1min"
    assert d["notify"]["cadence_default"] in {"realtime", "1min", "3min", "5min"}
    assert (d["notify"]["sse_heartbeat_s"], d["notify"]["sse_replay_window_s"]) == (15, 600)
    assert d["intervals"]["quote_interval_s"] >= 5


def test_key_defaults_ingest():
    d = snap("ingest")
    b = d["budget"]
    assert (b["per_minute_budget"], b["max_concurrency"]) == (3000, 1)
    assert sum(b["shares"].values()) <= b["per_minute_budget"]
    assert d["heartbeat"] == {"key": "ingest:heartbeat", "paused_key": "ingest:paused", "interval_s": 15,
                              "ttl_s": 600, "stale_after_s": 120}
    assert d["heartbeat"]["interval_s"] < d["heartbeat"]["stale_after_s"] < d["heartbeat"]["ttl_s"]
    assert d["leader"]["renew_every_s"] < d["leader"]["lease_s"]
    assert d["egress"]["check_on_start"] is True


def test_key_defaults_market_rules():
    d = snap("market_rules")
    seg = d["segments"][0]
    assert seg["effective_from"] == "2026-07-06"
    assert seg["price_limit_pct"] == {"main_board": 10, "main_board_st": 10, "chinext": 20, "star": 20, "bse": 30}
    assert seg["sessions"] == {"call_auction": ["09:15", "09:25"], "morning": ["09:30", "11:30"],
                               "afternoon": ["13:00", "14:57"], "closing_auction": ["14:57", "15:00"]}
    assert seg["t_plus"] == 1 and seg["lot"]["buy_lot"] == 100
    assert seg["fees"]["stamp_duty_sell_pct"] == 0.05 and seg["fees"]["commission_rate_default_pct"] is None
    tiers = seg["impact_cost"]["tiers"]
    assert [t["bp"] for t in tiers] == [0, 5, 15, 30, 60]
    caps = [t["max_participation_pct"] for t in tiers]
    assert caps[-1] is None and caps[:-1] == sorted(caps[:-1])
    second = expanded_market_rules(d)["segments"][1]
    assert second["effective_from"] == "2000-01-01" and second["price_limit_pct"]["main_board_st"] == 5


def test_key_defaults_risk_controls():
    d = snap("risk_controls")
    assert d["rc2_position_cap"]["single_position_max_pct"] == 20
    assert d["rc3_total_exposure"]["regime_ranges"] == {"uptrend": [60, 90], "range": [40, 60], "downtrend": [0, 30]}
    for lo, hi in d["rc3_total_exposure"]["regime_ranges"].values():
        assert 0 <= lo <= hi <= 100
    assert (d["rc4_sector_concentration"]["sw_l1_max_pct"], d["rc4_sector_concentration"]["concept_max_pct"]) == (40, 50)
    assert d["rc5_loss_streak_drawdown"]["closed_loss_streak"] == 3
    assert d["executability"]["cooling_off_after_stop"] == {"enabled": False, "days": 3}
    assert d["executability"]["low_confidence_threshold"] == 0.4
    assert set(k for k in d if k.startswith("rc")) == {
        "rc1_stop_take", "rc2_position_cap", "rc3_total_exposure", "rc4_sector_concentration",
        "rc5_loss_streak_drawdown", "rc6_plan_violation"}


def test_key_defaults_horizon_classifier():
    d = snap("horizon_classifier")
    assert (d["version_no"], d["suitable_threshold"], d["reasons_per_horizon"]) == (1, 60, [2, 4])
    assert d["rules"] == {}
    assert len(d["features"]) == len(set(d["features"])) == 14


def test_snapshot_matches_backend_settings_defaults(backend, clean_env):
    """ingest.yaml 的心跳键名/阈值与后端 Settings 默认值一致（契约 §7.10、plan §6.1）。"""
    s = backend.config.Settings()
    hb = snap("ingest")["heartbeat"]
    assert (s.ingest_heartbeat_key, s.ingest_paused_key, s.ingest_stale_after_s) == (hb["key"], hb["paused_key"], hb["stale_after_s"])


# ---------------- 2. 快照 == plan §6.1 ----------------
@pytest.mark.parametrize("name", NAMES)
def test_snapshot_equals_plan_block(docs_dir, name):
    blocks = plan_blocks((docs_dir / "plan.md").read_text(encoding="utf-8"))
    assert set(blocks) == set(NAMES)
    assert yaml.safe_load(blocks[name]) == snap(name), f"plan §6.1 的 {name}.yaml 已变，请同步快照"


# ---------------- 3. 仓库 config/*.yaml == 快照 ----------------
def _repo_file(name: str) -> Path:
    for ext in (".yaml", ".yml"):
        p = CONFIG_DIR / f"{name}{ext}"
        if p.is_file():
            return p
    pytest.skip(f"{CONFIG_DIR}/{name}.yaml 尚未创建（依赖 T-B01 后续 / T-B02：plan §6.1 文件由后端创建）")


@pytest.mark.parametrize("name", NAMES)
def test_repo_yaml_equals_plan_defaults(name):
    got = yaml.safe_load(_repo_file(name).read_text(encoding="utf-8"))
    want = snap(name)
    if name == "market_rules":
        want = expanded_market_rules(want)
    assert got == want


def test_repo_yaml_loads_in_settings(backend, clean_env, monkeypatch):
    present = [n for n in NAMES if (CONFIG_DIR / f"{n}.yaml").is_file()]
    if not present:
        pytest.skip(f"{CONFIG_DIR} 下没有 plan §6.1 的 yaml（依赖 T-B01 后续 / T-B02）")
    monkeypatch.setenv("CONFIG_DIR", str(CONFIG_DIR))
    business = backend.config.Settings().business
    assert set(present) <= set(business)
