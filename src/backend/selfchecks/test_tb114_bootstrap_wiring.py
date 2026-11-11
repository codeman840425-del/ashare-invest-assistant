# ruff: noqa: S101
"""T-B114: ingest startup wires set_ingest_core(IngestCore(..., engine=...)).

Red on baseline 28c3e7d (no bootstrap); green after wiring. Also proves api/worker
startup paths are unaffected.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from pydantic import SecretStr
from sqlalchemy import Engine, create_engine

from app.config_files import IngestConfig
from app.ingest.core import IngestCore

ROOT = Path(__file__).resolve().parents[3]
CFG = IngestConfig.model_validate(
    yaml.safe_load((ROOT / "config/ingest.yaml").read_text(encoding="utf-8"))
).licences
INGEST_PY = ROOT / "src/backend/app/workers/ingest.py"


def test_tb114_ingest_main_source_calls_bootstrap() -> None:
    src = INGEST_PY.read_text(encoding="utf-8")
    assert "def bootstrap_ingest_core" in src, "missing bootstrap_ingest_core (28c3e7d red)"
    assert "def main" in src
    main_body = src.split("def main", 1)[1].split("\nif __name__", 1)[0]
    assert "bootstrap_ingest_core" in main_body, "main does not call bootstrap (red)"
    # Must construct IngestCore with engine= and set_ingest_core
    boot = src.split("def bootstrap_ingest_core", 1)[1].split("\ndef ", 1)[0]
    assert "IngestCore(" in boot
    assert "engine=" in boot
    assert "set_ingest_core" in boot


def test_tb114_bootstrap_sets_core_with_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_NAME", "ingest")
    monkeypatch.setenv("APP_ENV", "local")
    from app.ingest import runtime
    from app.workers import ingest as ingest_worker

    runtime.set_ingest_core(None)

    # SQLite in-memory answers SELECT 1; enough to prove wiring (not PG-specific).
    engine = create_engine("sqlite+pysqlite:///:memory:")

    class _HB:
        interval_s = 15
        ttl_s = 30

    class _BizIngest:
        heartbeat = _HB()
        licences = CFG

    class _Settings:
        database_url = SecretStr("sqlite+pysqlite:///:memory:")
        business = SimpleNamespace(ingest=_BizIngest())

    def _fake_engine_for(url: str, profile: str = "default") -> Engine:
        assert "sqlite" in url
        return engine

    monkeypatch.setattr("app.db.engine.engine_for", _fake_engine_for)
    got = ingest_worker.bootstrap_ingest_core(_Settings())  # type: ignore[arg-type]
    try:
        core = runtime.get_ingest_core()
        assert core is not None
        assert core.engine is engine
        assert got is engine
    finally:
        runtime.set_ingest_core(None)


def test_tb114_bootstrap_refuses_without_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_NAME", "ingest")
    monkeypatch.setenv("APP_ENV", "local")
    from app.ingest import runtime
    from app.workers import ingest as ingest_worker

    runtime.set_ingest_core(None)

    class _Settings:
        database_url = None
        business = SimpleNamespace(ingest=SimpleNamespace(licences=CFG))

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        ingest_worker.bootstrap_ingest_core(_Settings())  # type: ignore[arg-type]
    assert runtime.get_ingest_core() is None


def test_tb114_api_and_worker_sources_do_not_bootstrap() -> None:
    worker_py = (ROOT / "src/backend/app/workers/worker.py").read_text(encoding="utf-8")
    main_py = (ROOT / "src/backend/app/main.py").read_text(encoding="utf-8")
    assert "bootstrap_ingest_core" not in worker_py
    assert "set_ingest_core" not in worker_py
    assert "bootstrap_ingest_core" not in main_py
    assert "set_ingest_core" not in main_py


def test_tb114_api_service_allows_memory_core_and_worker_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """api/worker startup must not require IngestCore.engine (L-1′ ingest-only)."""
    monkeypatch.setenv("SERVICE_NAME", "api")
    monkeypatch.setenv("APP_ENV", "local")
    from app.ingest import runtime

    runtime.set_ingest_core(None)
    core = IngestCore(CFG)
    assert core.engine is None

    # Importing worker entry must not wire ingest core.
    import app.workers.worker as worker_mod

    assert runtime.get_ingest_core() is None
    # worker.run path source uses runner.run — no bootstrap symbol
    assert not hasattr(worker_mod, "bootstrap_ingest_core")
    src = inspect.getsource(worker_mod)
    assert "bootstrap_ingest_core" not in src
