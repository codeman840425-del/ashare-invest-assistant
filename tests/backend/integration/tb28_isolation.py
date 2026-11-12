"""Inspect-only PG identity guard. Explicit overrides never create/connect resources."""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath

# Legacy identity is retained for the old runner; new fixtures must override all three.
PG = "/tb58-isolated-pg3"
SOCKET = "/tmp/tb58-pg3-socket"
VOLUME = "cb74ac8b598dc70429ffc2081fae178a80cf6cad138e58e9d7cf93d100b1487d"
ENV_KEYS = ("AIA_TB28_PG_CONTAINER", "AIA_TB28_PG_SOCKET", "AIA_TB28_PG_VOLUME")


@dataclass(frozen=True)
class IsolationTarget:
    container: str = PG
    socket: str = SOCKET
    volume: str = VOLUME

    def __post_init__(self) -> None:
        if not re.fullmatch(r"/[a-zA-Z0-9][a-zA-Z0-9_.-]*", self.container):
            raise ValueError("invalid isolated container name")
        path = PurePosixPath(self.socket)
        if (
            not self.socket.startswith("/")
            or self.socket.startswith("//")
            or str(path) != self.socket
            or self.socket == "/"
            or ".." in path.parts
        ):
            raise ValueError("isolated socket must be a normalized absolute POSIX directory")
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", self.volume):
            raise ValueError("invalid dedicated volume name")


def isolation_target(env: Mapping[str, str] | None = None) -> IsolationTarget:
    values = os.environ if env is None else env
    supplied = [key in values for key in ENV_KEYS]
    if any(supplied) and not all(supplied):
        raise ValueError("override container, socket and volume together; no partial identity")
    if not any(supplied):
        return IsolationTarget()
    return IsolationTarget(*(values[key] for key in ENV_KEYS))


def verify_isolated_pg(target: IsolationTarget | None = None) -> None:
    target = isolation_target() if target is None else target
    fmt = (
        '{"name":{{json .Name}},"network":{{json .HostConfig.NetworkMode}},'
        '"ports":{{json .NetworkSettings.Ports}},"mounts":{{json .Mounts}},'
        '"running":{{json .State.Running}}}'
    )
    try:
        ids = subprocess.check_output(
            ["docker", "ps", "-aq"], text=True
        ).split()
        rows = [
            json.loads(
                subprocess.check_output(
                    ["docker", "inspect", "--format", fmt, identifier], text=True
                )
            )
            for identifier in ids
        ]
    except Exception:  # noqa: BLE001 -- any inspect failure must prevent PG connection
        raise RuntimeError("无法验证固定隔离容器；禁止连接PG") from None
    pg = next((row for row in rows if row["name"] == target.container), None)
    if not pg or not pg["running"] or pg["network"] != "none" or pg["ports"]:
        raise RuntimeError("隔离PG身份/网络不符；禁止连接")
    expected = {
        (target.socket, target.socket),
        (f"/var/lib/docker/volumes/{target.volume}/_data", "/var/lib/postgresql/data"),
    }
    if {(mount["Source"], mount["Destination"]) for mount in pg["mounts"]} != expected:
        raise RuntimeError("隔离PG挂载不符；禁止连接")
    for other in rows:
        if other["name"] == target.container:
            continue
        for mine in pg["mounts"]:
            for theirs in other["mounts"]:
                first, second = PurePosixPath(mine["Source"]), PurePosixPath(theirs["Source"])
                if first == second or first in second.parents or second in first.parents:
                    raise RuntimeError("隔离PG与其他容器共享挂载；禁止连接")
