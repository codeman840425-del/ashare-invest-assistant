# ruff: noqa: S101
"""T-B113 L-1′: engine required for ingest / non-dev APP_ENV (not only production)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.config_files import IngestConfig
from app.ingest.core import IngestCore

ROOT = Path(__file__).resolve().parents[3]
CFG = IngestConfig.model_validate(
    yaml.safe_load((ROOT / "config/ingest.yaml").read_text(encoding="utf-8"))
).licences


def test_tb113_l1_service_ingest_requires_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_NAME", "ingest")
    monkeypatch.setenv("APP_ENV", "local")  # compose default — old guard missed this
    with pytest.raises(RuntimeError, match="engine is required"):
        IngestCore(CFG)


def test_tb113_l1_staging_requires_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_NAME", "api")
    monkeypatch.setenv("APP_ENV", "staging")
    with pytest.raises(RuntimeError, match="engine is required"):
        IngestCore(CFG)


def test_tb113_l1_local_api_allows_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_NAME", "api")
    monkeypatch.setenv("APP_ENV", "local")
    assert IngestCore(CFG).engine is None
