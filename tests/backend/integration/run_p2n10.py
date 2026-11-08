"""Offline targeted runner. Services must be provisioned/recorded explicitly first.

Example: P2N10_ARTIFACTS=/path/to/task-logs python run_p2n10.py
Uses only tests/backend/integration/test_p2n10_loop.py, never full/coverage.
"""

from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(os.environ["P2N10_ARTIFACTS"]).resolve()
allowed = {"PATH", "HOME", "LANG", "LC_ALL", "P2N10_ARTIFACTS"}
for key in list(os.environ):
    if key not in allowed:
        del os.environ[key]
os.environ.update(
    APP_ENV="test",
    MAIRUI_MODE="replay",
    MAIRUI_LICENCE="",
    PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
    PYTHONDONTWRITEBYTECODE="1",
    NO_PROXY="127.0.0.1,localhost",
)
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "src/backend"))
records = []
pg_socket = json.loads((OUT / "isolation.json").read_text())[0]["mounts"][0]["Source"]


def audit(event, args):
    if event == "open":
        path = str(args[0])
        if any(
            x in path
            for x in [
                "/private-samples/",
                "/docs/strategies/cards/",
                "/H-01",
                "/W-01",
                "/aia-t01-deploy/",
                "/aia-t01-deploy-o11/",
                "/team/runtime/",
            ]
        ) or path.endswith("/.env"):
            records.append({"denied": "forbidden-file"})
            raise PermissionError("P2N10 forbidden formal/private/runtime source")
    if event == "socket.getaddrinfo" and args[0] not in {
        "127.0.0.1",
        "::1",
        "localhost",
        None,
    }:
        records.append({"denied": "external-dns"})
        raise PermissionError("P2N10 external DNS denied")
    if event == "socket.connect":
        sock, address = args
        if sock.family == socket.AF_UNIX:
            if not (
                str(address).startswith(str(OUT / "runtime") + "/")
                or str(address).startswith(pg_socket + "/")
            ):
                raise PermissionError("P2N10 foreign Unix service denied")
        elif not (
            address[0] in {"127.0.0.1", "::1"} and address[1] in {15580, 18580, 15582}
        ):
            records.append({"denied": "foreign-network"})
            raise PermissionError("P2N10 non-test connection denied")


sys.addaudithook(audit)
import pytest

try:
    code = pytest.main(
        [
            str(ROOT / "tests/backend/integration/test_p2n10_loop.py"),
            "-q",
            "--tb=short",
            "--junitxml="
            + str(
                OUT
                / (
                    "pytest-"
                    + __import__("datetime").datetime.now().strftime("%H%M%S")
                    + ".xml"
                )
            ),
            *sys.argv[1:],
        ]
    )
finally:
    (OUT / "audit-denials.json").write_text(json.dumps(records, indent=2))
raise SystemExit(code)
