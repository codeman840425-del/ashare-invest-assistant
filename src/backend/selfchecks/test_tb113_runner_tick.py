# ruff: noqa: S101
"""T-B113: ingest heartbeat round invokes IngestCore.tick when wired."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.config_files import IngestConfig
from app.ingest.core import IngestCore

ROOT = Path(__file__).resolve().parents[3]
CFG = IngestConfig.model_validate(
    yaml.safe_load((ROOT / "config/ingest.yaml").read_text(encoding="utf-8"))
).licences


def test_tb113_write_heartbeat_source_calls_tick_ingest_core() -> None:
    ingest_py = ROOT / "src/backend/app/workers/ingest.py"
    src = ingest_py.read_text(encoding="utf-8")
    assert "tick_ingest_core" in src, "runner missing IngestCore.tick call site (T-A84)"


def test_tb113_tick_ingest_core_calls_core_tick(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_NAME", "api")
    monkeypatch.setenv("APP_ENV", "local")
    try:
        from app.ingest import runtime
    except ImportError:
        pytest.fail("app.ingest.runtime missing — IngestCore tick hook not wired")
    core = IngestCore(CFG)
    called: list[dt.datetime] = []

    def _capture(now: dt.datetime) -> list[Any]:
        called.append(now)
        return []

    monkeypatch.setattr(core, "tick", _capture)
    runtime.set_ingest_core(core)
    try:
        when = dt.datetime(2026, 11, 9, 17, 0, tzinfo=dt.UTC)
        runtime.tick_ingest_core(when)
        assert called == [when]
    finally:
        runtime.set_ingest_core(None)
