# ruff: noqa: S101
"""T-B116: AST static guard (A1) + L-1/L-2/L-4 selfchecks. No real Mairui."""

from __future__ import annotations

import ast
import inspect
import os
import socket
import time
from pathlib import Path

import pytest
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "src/backend/app"
PROBE_WHITELIST = (
    "src/backend/probes/common.py",
    "src/backend/probes/tb81.py",
    "src/backend/probes/tb86_history.py",
)
MAIRUI_MARKERS = ("mairuiapi.com", "api.mairuiapi.com", "pro.mairuiapi.com")
HTTP_MODS = {"http.client", "urllib.request", "requests", "httpx"}


def _py_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def test_tb116_a1_static_guard_only_egress_opens_mairui() -> None:
    offenders: list[str] = []
    for path in _py_files(APP):
        rel = path.relative_to(ROOT).as_posix()
        src = path.read_text(encoding="utf-8")
        # app must not import probes
        if "probes" in src and "import" in src:
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module and "probes" in node.module:
                    offenders.append(f"{rel}: imports probes")
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if "probes" in alias.name:
                            offenders.append(f"{rel}: imports probes")
        if rel == "src/backend/app/ingest/egress.py":
            continue
        # master/sources may use urllib but not mairui host
        lower = src.lower()
        has_mairui = any(m in lower for m in MAIRUI_MARKERS)
        has_http = (
            "http.client" in src
            or "urllib.request" in src
            or "import requests" in src
            or "import httpx" in src
            or "socket.create_connection" in src
        )
        if has_mairui and has_http:
            offenders.append(f"{rel}: mairui + http client outside egress")
        elif has_mairui and rel != "src/backend/app/ingest/egress.py":
            # allow string mentions in comments/docs within app only if no connect APIs —
            # still flag HTTPSConnection / urlopen near mairui
            if "HTTPSConnection" in src or "urlopen" in src or "httpx." in src:
                offenders.append(f"{rel}: mairui connect API outside egress")
    assert offenders == [], offenders

    # Probe whitelist exists; not imported by app; dockerignore excludes probes
    for rel in PROBE_WHITELIST:
        assert (ROOT / rel).is_file(), f"missing whitelist probe {rel}"
    dockerignore = (ROOT / "deploy/docker/backend.Dockerfile.dockerignore").read_text(
        encoding="utf-8"
    )
    assert "probes" not in [
        ln.strip().lstrip("!").rstrip("/")
        for ln in dockerignore.splitlines()
        if ln.strip().startswith("!")
    ], "dockerignore must not whitelist probes into image"
    # positive: app/ is whitelisted, probes are not
    assert "!app/" in dockerignore or "!app" in dockerignore


def test_tb116_l4_try_acquire_removed_and_docstring() -> None:
    ip = (ROOT / "src/backend/app/ingest/ip_limit.py").read_text(encoding="utf-8")
    assert "def try_acquire_ip_limit_lock" not in ip
    core = (ROOT / "src/backend/app/ingest/core.py").read_text(encoding="utf-8")
    flush = core.split("def _try_flush_pending", 1)[1].split("\ndef ", 1)[0]
    assert "try-lock" not in flush.lower() or "not try-lock" in flush.lower()
    assert "lock_timeout" in flush or "2s" in flush


def test_tb116_l1_ingest_profile_nullpool_and_timeouts() -> None:
    from app.db.engine import engine_for

    engine_for.cache_clear()
    eng = engine_for("postgresql+psycopg://u:p@127.0.0.1:1/db", profile="ingest")
    assert eng.pool.__class__ is NullPool
    # connect_args
    ca = eng.url.query  # may be empty; inspect creator
    # sqlalchemy stores connect_args on the dialect/engine
    args = eng.dialect.create_connect_args(eng.url)
    # better: look at private _execution_options / pool
    raw = getattr(eng, "get_execution_options", lambda: {})()
    # inspect via create_engine kwargs by reading source
    src = (ROOT / "src/backend/app/db/engine.py").read_text(encoding="utf-8")
    assert 'profile == "ingest"' in src
    assert "connect_timeout" in src and "3" in src
    assert "NullPool" in src
    assert "statement_timeout=5000" in src
    assert "lock_timeout=2000" in src
    engine_for.cache_clear()
    # default profile still pooled
    eng2 = engine_for("postgresql+psycopg://u:p@127.0.0.1:1/db")
    assert eng2.pool.__class__ is not NullPool
    engine_for.cache_clear()


def test_tb116_l1_connect_timeout_bound_blackhole(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fake TCP port that accepts then never answers → connect should bound ≤8s."""
    monkeypatch.setenv("SERVICE_NAME", "ingest")
    monkeypatch.setenv("APP_ENV", "local")
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def accept_forever() -> None:
        try:
            conn, _ = srv.accept()
            # never read/respond; leave connection half-open
            time.sleep(30)
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    import threading

    threading.Thread(target=accept_forever, daemon=True).start()
    from app.db.engine import engine_for

    engine_for.cache_clear()
    url = f"postgresql+psycopg://postgres@127.0.0.1:{port}/postgres"
    eng = engine_for(url, profile="ingest")
    t0 = time.monotonic()
    with pytest.raises(Exception):  # noqa: BLE001 — operational/timeout
        with eng.connect() as conn:
            conn.execute(__import__("sqlalchemy").text("SELECT 1"))
    elapsed = time.monotonic() - t0
    engine_for.cache_clear()
    srv.close()
    assert elapsed <= 8.0, f"connect not bounded: {elapsed}s"


def test_tb116_l2_main_exit_78_no_traceback_no_secret(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setenv("SERVICE_NAME", "ingest")
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.delenv("MAIRUI_LICENCE", raising=False)
    monkeypatch.delenv("APP_MASTER_KEY", raising=False)
    from app.workers import ingest as iw

    monkeypatch.setattr(iw, "legacy_licence_present", lambda environ=None: False)
    monkeypatch.setattr(iw, "master_key_present", lambda environ=None: False)

    class Boom:
        pass

    def bad_settings():  # noqa: ANN001
        raise ValueError("password=super-secret-tb116")

    import app.config as config_mod

    monkeypatch.setattr(config_mod, "get_settings", bad_settings)
    rc = iw.main()
    assert rc == iw.EXIT_LEGACY_LICENCE
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert "super-secret-tb116" not in err
    assert "ValueError" in err
    assert "拒绝启动" in err
