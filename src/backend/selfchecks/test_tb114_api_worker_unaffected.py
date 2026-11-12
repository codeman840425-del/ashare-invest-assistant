# ruff: noqa: S101
"""T-B114: api and worker entrypoints do not require ingest IngestCore wiring."""

from __future__ import annotations

import multiprocessing
import os
import sys
from collections.abc import Callable
from multiprocessing.connection import Connection
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def test_tb114_worker_module_import_does_not_bootstrap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_NAME", "worker")
    monkeypatch.setenv("APP_ENV", "local")
    from app.ingest import runtime

    runtime.set_ingest_core(None)
    import app.workers.worker

    assert runtime.get_ingest_core() is None
    assert not hasattr(app.workers.worker, "bootstrap_ingest_core")


def test_tb114_api_app_factory_import_does_not_bootstrap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Importing create_app path must not wire ingest (avoid full Settings if possible)."""
    monkeypatch.setenv("SERVICE_NAME", "api")
    monkeypatch.setenv("APP_ENV", "local")
    from app.ingest import runtime

    runtime.set_ingest_core(None)
    # Prefer lightweight import: app.main may pull Settings; still must not set ingest core.
    import app.main  # noqa: F401

    assert runtime.get_ingest_core() is None


def _assert_main_calls_bootstrap_then_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """ingest.main wires core then enters run; refuse path returns 78 without entering run."""
    monkeypatch.setenv("SERVICE_NAME", "ingest")
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.delenv("MAIRUI_LICENCE", raising=False)
    monkeypatch.delenv("APP_MASTER_KEY", raising=False)

    from app.ingest import runtime
    from app.workers import ingest as ingest_worker

    if not hasattr(ingest_worker, "bootstrap_ingest_core"):
        pytest.fail("bootstrap_ingest_core missing — baseline red (28c3e7d)")

    runtime.set_ingest_core(None)
    monkeypatch.setattr(ingest_worker, "legacy_licence_present", lambda environ=None: False)
    monkeypatch.setattr(ingest_worker, "master_key_present", lambda environ=None: False)

    class _Settings:
        database_url = None
        business = type(
            "B",
            (),
            {"ingest": type("I", (), {"heartbeat": type("H", (), {"interval_s": 15})()})()},
        )()

    import app.config as config_mod

    monkeypatch.setattr(config_mod, "get_settings", lambda: _Settings())

    entered_run: list[str] = []

    def _fake_run(*a: object, **k: object) -> int:
        entered_run.append("run")
        return 0

    monkeypatch.setattr(ingest_worker, "run", _fake_run)
    rc = ingest_worker.main()
    assert rc == ingest_worker.EXIT_LEGACY_LICENCE
    assert entered_run == [], "refuse path must not enter run()"
    assert runtime.get_ingest_core() is None


def _main_refusal_child(output: Connection) -> None:
    from app.ingest import netguard

    try:
        with pytest.MonkeyPatch.context() as monkeypatch:
            _assert_main_calls_bootstrap_then_run(monkeypatch)
        # Exercise the real installed audit hook after fixture teardown. Its state
        # belongs to this interpreter and must not escape into the pytest parent.
        with pytest.raises(netguard.EgressBlocked, match=r"^subprocess$"):
            sys.audit("subprocess.Popen", sys.executable, [sys.executable], None, None)
        output.send((os.getpid(), os.getppid(), "subprocess"))
    finally:
        output.close()


def test_tb114_main_calls_bootstrap_then_run(
    record_testsuite_property: Callable[[str, object], None],
) -> None:
    ctx = multiprocessing.get_context("spawn")
    received, sent = ctx.Pipe(duplex=False)
    child = ctx.Process(target=_main_refusal_child, args=(sent,))
    child.start()
    sent.close()
    try:
        child.join(timeout=15)
        assert not child.is_alive(), "isolated ingest-main check exceeded 15s"
        assert child.exitcode == 0
        assert received.poll(), "isolated child did not complete the original assertions"
        pid, parent_pid, reason = received.recv()
        assert pid == child.pid
        assert parent_pid == os.getpid()
        assert reason == "subprocess"
        record_testsuite_property("netguard_child_pid", pid)
        record_testsuite_property("netguard_parent_pid", parent_pid)
        record_testsuite_property("netguard_child_refusal", reason)
    finally:
        if child.is_alive():
            child.terminate()
            child.join()
        received.close()
        child.close()
