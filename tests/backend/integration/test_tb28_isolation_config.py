"""Synthetic Docker metadata paths only: no daemon/PG/filesystem access."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

import pytest

from . import tb28_isolation as isolation


@pytest.fixture(autouse=True)
def no_real_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    def deny(*_args: object, **_kwargs: object) -> None:
        pytest.fail("real Docker is forbidden in identity unit checks")

    monkeypatch.setattr(isolation.subprocess, "check_output", deny)
    for key in isolation.ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def target() -> isolation.IsolationTarget:
    return isolation.IsolationTarget(
        "/synthetic-isolated-pg", "/tmp/synthetic-pg", "synthetic-volume"
    )


def metadata(selected: isolation.IsolationTarget) -> dict[str, Any]:
    return {
        "name": selected.container,
        "network": "none",
        "ports": {},
        "running": True,
        "mounts": [
            {"Source": selected.socket, "Destination": selected.socket},
            {
                "Source": f"/var/lib/docker/volumes/{selected.volume}/_data",
                "Destination": "/var/lib/postgresql/data",
            },
        ],
    }


def mock_inspect(monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, Any]]) -> list[list[str]]:
    calls: list[list[str]] = []

    def output(args: list[str], *, text: bool) -> str:
        calls.append(args)
        assert text
        if args == ["docker", "ps", "-aq"]:
            return " ".join(str(i) for i in range(len(rows)))
        assert args[:2] == ["docker", "inspect"]
        return json.dumps(rows[int(args[-1])])

    monkeypatch.setattr(isolation.subprocess, "check_output", output)
    return calls


def test_legacy_defaults_are_unchanged() -> None:
    assert asdict(isolation.isolation_target({})) == {
        "container": isolation.PG,
        "socket": isolation.SOCKET,
        "volume": isolation.VOLUME,
    }


def test_all_explicit_overrides_are_used() -> None:
    selected = target()
    env = dict(zip(isolation.ENV_KEYS, asdict(selected).values(), strict=True))
    assert isolation.isolation_target(env) == selected


@pytest.mark.parametrize("keys", [(0,), (1,), (2,), (0, 1), (0, 2), (1, 2)])
def test_partial_override_rejected_before_inspect(
    monkeypatch: pytest.MonkeyPatch,
    keys: tuple[int, ...],
) -> None:
    values = asdict(target()).values()
    for i, value in enumerate(values):
        if i in keys:
            monkeypatch.setenv(isolation.ENV_KEYS[i], value)
    with pytest.raises(ValueError, match="together"):
        isolation.verify_isolated_pg()


@pytest.mark.parametrize(
    "changes",
    [
        {"container": "synthetic-no-slash"},
        {"container": "/synthetic;command"},
        {"socket": "C:/synthetic"},
        {"socket": "/"},
        {"socket": "/tmp/../shared"},
        {"socket": "//tmp/synthetic"},
        {"socket": "/tmp//synthetic"},
        {"volume": "../shared"},
        {"volume": ""},
    ],
)
def test_invalid_identity_is_rejected(changes: dict[str, str]) -> None:
    values = {**asdict(target()), **changes}
    with pytest.raises(ValueError, match=r"invalid|normalized absolute"):
        isolation.IsolationTarget(**values)


def test_valid_custom_identity_is_inspect_only(monkeypatch: pytest.MonkeyPatch) -> None:
    selected = target()
    calls = mock_inspect(monkeypatch, [metadata(selected)])
    isolation.verify_isolated_pg(selected)
    assert len(calls) == 2
    assert all(call[1] in ("ps", "inspect") for call in calls)


@pytest.mark.parametrize(
    "change",
    [
        {"name": "/other"},
        {"running": False},
        {"network": "bridge"},
        {"ports": {"5432/tcp": [{"HostPort": "5432"}]}},
    ],
)
def test_wrong_identity_or_network_rejected(
    monkeypatch: pytest.MonkeyPatch,
    change: dict[str, Any],
) -> None:
    selected = target()
    mock_inspect(monkeypatch, [{**metadata(selected), **change}])
    with pytest.raises(RuntimeError, match="身份/网络"):
        isolation.verify_isolated_pg(selected)


@pytest.mark.parametrize("change", ["socket", "volume", "extra"])
def test_mount_identity_must_match_exactly(monkeypatch: pytest.MonkeyPatch, change: str) -> None:
    selected = target()
    row = metadata(selected)
    if change == "extra":
        row["mounts"].append({"Source": "/tmp/foreign", "Destination": "/foreign"})
    else:
        row["mounts"][0 if change == "socket" else 1]["Source"] = "/tmp/foreign"
    mock_inspect(monkeypatch, [row])
    with pytest.raises(RuntimeError, match="挂载不符"):
        isolation.verify_isolated_pg(selected)


@pytest.mark.parametrize("shared", ["/tmp/synthetic-pg", "/tmp", "/tmp/synthetic-pg/subdir"])
def test_shared_or_overlapping_mount_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    shared: str,
) -> None:
    selected = target()
    other = {"name": "/synthetic-other", "mounts": [{"Source": shared, "Destination": "/foreign"}]}
    mock_inspect(monkeypatch, [metadata(selected), other])
    with pytest.raises(RuntimeError, match="共享挂载"):
        isolation.verify_isolated_pg(selected)


def test_verify_uses_complete_environment_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    selected = target()
    for key, value in zip(isolation.ENV_KEYS, asdict(selected).values(), strict=True):
        monkeypatch.setenv(key, value)
    mock_inspect(monkeypatch, [metadata(selected)])
    isolation.verify_isolated_pg()


def test_disjoint_other_mount_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    selected = target()
    other = {
        "name": "/synthetic-other",
        "mounts": [{"Source": "/tmp/unrelated", "Destination": "/foreign"}],
    }
    mock_inspect(monkeypatch, [metadata(selected), other])
    isolation.verify_isolated_pg(selected)


def test_docker_unavailable_fails_closed_without_echo(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(*_args: object, **_kwargs: object) -> None:
        raise OSError("synthetic-details-not-to-echo")

    monkeypatch.setattr(isolation.subprocess, "check_output", unavailable)
    with pytest.raises(RuntimeError, match="禁止连接PG") as error:
        isolation.verify_isolated_pg(target())
    assert "synthetic-details" not in str(error.value)
