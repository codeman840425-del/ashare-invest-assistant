# ruff: noqa: S101
"""T-B112 L-1: production refuses IngestCore without engine."""

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


def test_tb112_l1_production_requires_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(RuntimeError, match="engine is required"):
        IngestCore(CFG)


def test_tb112_l1_non_production_allows_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    core = IngestCore(CFG)
    assert core.engine is None
