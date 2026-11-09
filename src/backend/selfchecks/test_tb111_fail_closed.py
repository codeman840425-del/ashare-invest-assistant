# ruff: noqa: S101
"""T-B111 / T-A75: store errors must refuse (fail-closed), never allow outbound."""

from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path
from typing import NoReturn

import yaml

from app.config_files import IngestConfig
from app.ingest.core import IngestCore
from app.ingest.state import Priority
from app.schemas.enums import DataLicenceStatus, DataLicenceTier

ROOT = Path(__file__).resolve().parents[3]
CFG = IngestConfig.model_validate(
    yaml.safe_load((ROOT / "config/ingest.yaml").read_text(encoding="utf-8"))
).licences
NOW0 = dt.datetime(2026, 11, 9, 12, 0, tzinfo=dt.UTC)


class _BoomEngine:
    """Minimal stand-in: connect()/begin() always raise."""

    def connect(self) -> NoReturn:
        raise RuntimeError("tb111 synthetic DB down")

    def begin(self) -> NoReturn:
        raise RuntimeError("tb111 synthetic DB down")


def test_tb111_fail_closed_on_rehydrate_error() -> None:
    uid, lid = uuid.uuid4(), uuid.uuid4()
    core = IngestCore(CFG, engine=_BoomEngine())  # type: ignore[arg-type]
    core.upsert(
        lid,
        user_id=uid,
        tier=DataLicenceTier.ANNUAL,
        status=DataLicenceStatus.ACTIVE,
        now=NOW0,
    )
    assert core.user_escalated_until(lid) is not None
    assert core.allows(lid, Priority.P0, NOW0 + dt.timedelta(seconds=1), verify=True) is False


def test_tb111_fail_closed_on_record_hit_error() -> None:
    uid, lid = uuid.uuid4(), uuid.uuid4()
    core = IngestCore(CFG)
    core.upsert(
        lid,
        user_id=uid,
        tier=DataLicenceTier.ANNUAL,
        status=DataLicenceStatus.ACTIVE,
        now=NOW0,
    )
    core.engine = _BoomEngine()  # type: ignore[assignment]
    tr = core.apply_ip_limited(lid, NOW0)
    assert any(t.event == "ip_limited_escalated" for t in tr)
    assert core.allows(lid, Priority.P0, NOW0 + dt.timedelta(seconds=1)) is False
