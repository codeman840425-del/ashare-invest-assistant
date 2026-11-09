# ruff: noqa: S101
"""T-B113 / T-A83④ H17: H-01 multi-horizon card — missing horizon → gap only, not in n/win."""

from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path

import yaml

from app.config_files import RiskControlsConfig
from app.feedback.core import Observation, simulated_failures

ROOT = Path(__file__).resolve().parents[3]
AT = dt.datetime(2026, 11, 9, 15, 0, tzinfo=dt.UTC)
OWNER = uuid.uuid4()
VERSION = uuid.uuid4()
# H-01 declares multiple horizons (intraday_t/short/swing/long); version_horizon stays None.
H01_HORIZONS = ("intraday_t", "short", "swing", "long")


def _cfg() -> RiskControlsConfig:
    raw = yaml.safe_load((ROOT / "config/risk_controls.yaml").read_text())
    return RiskControlsConfig.model_validate(raw)


def _obs(*, horizon: str | None, direction_correct: bool, sid: str) -> Observation:
    return Observation(
        OWNER,
        VERSION,
        uuid.uuid5(uuid.NAMESPACE_URL, sid),
        uuid.uuid5(uuid.NAMESPACE_URL, sid + "-inst"),
        AT - dt.timedelta(days=2),
        horizon,
        5,  # days field present but horizon label missing → unknown
        "complete",
        direction_correct,
        AT - dt.timedelta(days=1),
        AT - dt.timedelta(days=1),
        (sid,),
    )


def test_tb113_h17_missing_horizon_is_gap_not_counted() -> None:
    assert set(H01_HORIZONS) == {"intraday_t", "short", "swing", "long"}
    cfg = _cfg().rc5_loss_streak_drawdown
    good = _obs(horizon="short", direction_correct=False, sid="h01-known")
    missing = _obs(horizon=None, direction_correct=False, sid="h01-missing")
    metric = simulated_failures(
        OWNER,
        VERSION,
        [good, missing],
        cfg,
        version_horizon=None,  # multi-horizon card: no single version_horizon
        at=AT,
    )
    assert "sim_fail_horizon_unknown" in metric.gaps
    # Only the known-horizon failure enters the streak/n; missing is skipped.
    assert metric.value == 1
