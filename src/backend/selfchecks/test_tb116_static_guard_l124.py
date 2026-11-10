# ruff: noqa: S101
"""T-B116/b: AST static guard (A1/B-2) + L-1/L-2/L-4 selfchecks. No real Mairui."""

from __future__ import annotations

import ast
import os
import socket
import time
from pathlib import Path

import pytest
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "src/backend/app"
PROBES = ROOT / "src/backend/probes"
PROBE_WHITELIST = (
    "src/backend/probes/common.py",
    "src/backend/probes/tb81.py",
    "src/backend/probes/tb86_history.py",
)
PROBE_WHITELIST_SET = set(PROBE_WHITELIST)
MAIRUI_MARKERS = ("mairuiapi.com", "api.mairuiapi.com", "pro.mairuiapi.com")
EGRESS_REL = "src/backend/app/ingest/egress.py"
SOURCES_REL = "src/backend/app/master/sources.py"


def _py_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _http_lib_hits(src: str) -> list[str]:
    hits: list[str] = []
    if "http.client" in src or "from http import client" in src:
        hits.append("http.client")
    if "urllib.request" in src:
        hits.append("urllib.request")
    if "import requests" in src or "from requests" in src:
        hits.append("requests")
    if "import httpx" in src or "from httpx" in src:
        hits.append("httpx")
    if "socket.create_connection" in src:
        hits.append("socket.create_connection")
    return hits



def _http_import_names(src: str) -> list[str]:
    """AST imports of HTTP client modules (avoids attribute-name false positives)."""
    hits: list[str] = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return hits
    http_roots = {"http", "urllib", "requests", "httpx", "urllib3"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in http_roots or alias.name in {
                    "http.client",
                    "urllib.request",
                }:
                    # http is broad; only count http.client style
                    if top == "http" and not alias.name.startswith("http.client"):
                        continue
                    if top == "urllib" and "request" not in alias.name:
                        continue
                    hits.append(alias.name)
        if isinstance(node, ast.ImportFrom) and node.module:
            mod = node.module
            top = mod.split(".")[0]
            if mod in {"http.client", "urllib.request"} or top in {
                "requests",
                "httpx",
                "urllib3",
            }:
                hits.append(mod)
            if mod == "http" and any(a.name == "client" for a in node.names):
                hits.append("http.client")
    return sorted(set(hits))


def _refs_egress_private(src: str) -> list[str]:
    """Ban importing / using egress._https_get or egress.HOST outside egress.py."""
    bad: list[str] = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return bad
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "app.ingest.egress":
            for alias in node.names:
                if alias.name in {"_https_get", "HOST"}:
                    bad.append(f"from app.ingest.egress import {alias.name}")
        if isinstance(node, ast.Attribute):
            # egress._https_get / eg._https_get / egress.HOST
            if isinstance(node.value, ast.Name) and node.attr in {"_https_get", "HOST"}:
                # only flag if name looks like egress alias — conservative: any ._https_get
                if node.attr == "_https_get":
                    bad.append("attr _https_get")
                if node.attr == "HOST" and node.value.id in {
                    "egress",
                    "eg",
                    "egress_mod",
                }:
                    bad.append(f"attr {node.value.id}.HOST")
    # string form import used by deleted wire shim
    if "from app.ingest.egress import _https_get" in src:
        bad.append("string import _https_get")
    if "import app.ingest.egress" in src and "_https_get" in src:
        # covered by attr walk mostly
        pass
    return bad


def test_tb116_a1_static_guard_only_egress_opens_mairui() -> None:
    """T-A88 B-2: HTTP libs only in egress (sources=urllib, no mairui); ban _https_get/HOST
    outside egress; probes exact 3-file whitelist; 4 bypasses must trip.
    """
    offenders: list[str] = []

    for path in _py_files(APP):
        rel = path.relative_to(ROOT).as_posix()
        src = path.read_text(encoding="utf-8")

        # app must not import probes
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

        if rel == EGRESS_REL:
            continue

        http_hits = _http_lib_hits(src)
        has_mairui = any(m in src.lower() for m in MAIRUI_MARKERS)

        if rel == SOURCES_REL:
            # urllib allowed; no other HTTP libs; no mairui host
            other = [h for h in http_hits if h != "urllib.request"]
            if other:
                offenders.append(f"{rel}: non-urllib http lib {other}")
            if has_mairui:
                offenders.append(f"{rel}: mairui marker in sources")
        else:
            # HTTP client libraries forbidden outside egress (and sources urllib)
            if http_hits:
                offenders.append(f"{rel}: http lib outside egress: {http_hits}")
            if has_mairui and (
                "HTTPSConnection" in src or "urlopen" in src or "httpx." in src
            ):
                offenders.append(f"{rel}: mairui connect API outside egress")

        for ref in _refs_egress_private(src):
            offenders.append(f"{rel}: {ref}")

        # wire must be gone (B-2)
        if "def wire(" in src and rel.endswith("daily_lists.py"):
            offenders.append(f"{rel}: wire() must be deleted")

    # probes/: scan every file; only the 3 whitelist entries may combine mairui host
    # markers with an HTTP client import (blocks "new file in probes/" bypass).
    whitelist_paths = {ROOT / r for r in PROBE_WHITELIST}
    if PROBES.is_dir():
        for path in _py_files(PROBES):
            rel = path.relative_to(ROOT).as_posix()
            if path in whitelist_paths:
                continue
            src = path.read_text(encoding="utf-8")
            has_mairui = any(m in src.lower() for m in MAIRUI_MARKERS)
            http_imports = _http_import_names(src)
            if has_mairui and http_imports:
                offenders.append(
                    f"{rel}: probes outside whitelist with mairui+http {http_imports}"
                )
            for ref in _refs_egress_private(src):
                offenders.append(f"{rel}: {ref}")

    assert offenders == [], offenders

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
    assert "!app/" in dockerignore or "!app" in dockerignore


def test_tb116b_b2_four_bypasses_are_detected(tmp_path: Path) -> None:
    """T-A88: the four bypass shapes must be classified as offenders by the guard rules."""
    # 1) import _https_get
    assert _refs_egress_private("from app.ingest.egress import _https_get\n")
    # 2) import HOST + http.client
    src2 = "from app.ingest.egress import HOST\nimport http.client\n"
    assert _refs_egress_private(src2) or _http_lib_hits(src2)
    # 3) call wire — wire deleted; guard flags def wire in daily_lists
    assert "def wire(" not in (
        ROOT / "src/backend/app/ingest/daily_lists.py"
    ).read_text(encoding="utf-8")
    # 4) new probes file with mairui would be flagged (simulate content check)
    fake = "import http.client\nURL = 'https://api.mairuiapi.com/x'\n"
    assert _http_lib_hits(fake) and any(m in fake.lower() for m in MAIRUI_MARKERS)


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
    src = (ROOT / "src/backend/app/db/engine.py").read_text(encoding="utf-8")
    assert 'profile == "ingest"' in src
    assert "connect_timeout" in src and "3" in src
    assert "NullPool" in src
    assert "statement_timeout=5000" in src
    assert "lock_timeout=2000" in src
    engine_for.cache_clear()
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


def test_tb116_l2_main_exit_78_no_traceback_no_secret(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setenv("SERVICE_NAME", "ingest")
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.delenv("MAIRUI_LICENCE", raising=False)
    monkeypatch.delenv("APP_MASTER_KEY", raising=False)
    from app.workers import ingest as iw

    monkeypatch.setattr(iw, "legacy_licence_present", lambda environ=None: False)
    monkeypatch.setattr(iw, "master_key_present", lambda environ=None: False)

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
