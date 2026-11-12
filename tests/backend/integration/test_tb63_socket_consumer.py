"""Synthetic tb63 consumer checks; no Docker/PG or real tb60 assertions run."""

from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

import pytest

from . import tb28_isolation as isolation
from . import test_tb63_signals as consumer
from .test_tb28_isolation_config import metadata


@pytest.fixture(autouse=True)
def no_real_resources(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    events: list[str] = []

    def deny_docker(*_args: object, **_kwargs: object) -> None:
        events.append("docker")
        pytest.fail("real Docker forbidden")

    def deny_connect(*_args: object, **_kwargs: object) -> None:
        events.append("connect")
        pytest.fail("real PG forbidden")

    def deny_write(*_args: object, **_kwargs: object) -> None:
        events.append("write")
        pytest.fail("real SQL forbidden")

    monkeypatch.setattr(isolation.subprocess, "check_output", deny_docker)
    monkeypatch.setattr(consumer.tb60, "create_engine", deny_connect)
    monkeypatch.setattr(consumer.tb60.Connection, "execute", deny_write)
    for key in isolation.ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    # Model the consumer's platform-specific tempfile directory without real resources.
    monkeypatch.setattr(
        consumer.tb60.tempfile, "gettempdir", lambda: str(Path(isolation.SOCKET).resolve().parent)
    )
    return events


def configure(monkeypatch: pytest.MonkeyPatch, socket: str) -> isolation.IsolationTarget:
    target = isolation.IsolationTarget("/synthetic-consumer", socket, "synthetic-volume")
    for key, value in zip(isolation.ENV_KEYS, asdict(target).values(), strict=True):
        monkeypatch.setenv(key, value)
    return target


@pytest.mark.parametrize("socket", ["/tmp/synthetic-pg", "/tmp/tb58-pg3-socket-other"])
def test_consumer_rejects_unsupported_socket_before_all_resources(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    no_real_resources: list[str],
    socket: str,
) -> None:
    configure(monkeypatch, socket)

    def deny_main() -> int:
        no_real_resources.append("tb60")
        pytest.fail("tb60 must not start for an unsupported socket")

    monkeypatch.setattr(consumer.tb60, "main", deny_main)
    with pytest.raises(ValueError, match="tb60.*socket"):
        consumer.test_isolated_pg_guard_writes_and_savepoint(monkeypatch, capsys)
    assert no_real_resources == []


@pytest.mark.parametrize("explicit", [False, True])
def test_consumer_supported_socket_inspects_before_forwarding(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    no_real_resources: list[str],
    explicit: bool,
) -> None:
    import json

    target = configure(monkeypatch, isolation.SOCKET) if explicit else isolation.IsolationTarget()
    expected_argv = ["tb60.py", "--socket-dir", target.socket]

    def inspect(args: list[str], *, text: bool) -> str:
        assert text
        if args == ["docker", "ps", "-aq"]:
            no_real_resources.append("ps")
            return "synthetic-id"
        assert args[:2] == ["docker", "inspect"]
        assert args[-1] == "synthetic-id"
        no_real_resources.append("inspect")
        return json.dumps(metadata(target))

    def synthetic_main() -> int:
        assert no_real_resources == ["ps", "inspect"]
        assert sys.argv == expected_argv
        no_real_resources.append("synthetic-main")
        # Supply the original wrapper's output contract; this is not a real 45-check run.
        print("SYNTHETIC ONLY: 45 passed, 0 failed; 所有DDL/合成数据最终回滚")
        return 0

    monkeypatch.setattr(isolation.subprocess, "check_output", inspect)
    monkeypatch.setattr(consumer.tb60, "main", synthetic_main)
    consumer.test_isolated_pg_guard_writes_and_savepoint(monkeypatch, capsys)
    assert no_real_resources == ["ps", "inspect", "synthetic-main"]
