# ruff: noqa: BLE001
"""T-B81 opt-in evidence probe. No environment credential fallback or exception rendering."""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import http.client
import json
import logging
import os
import re
import signal
import stat
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
import urllib3.connection
import urllib3.connectionpool
from requests.adapters import HTTPAdapter

HERE = Path(__file__).resolve().parent
SECRET = Path("/workspace/team/runtime/mairui-T-B81.tmp")
STOP = HERE / "results/STOP"
PLAN = [
    (
        "daily_star",
        "daily",
        "/hsstock/history/688018.SH/d/n/",
        {"st": "20260928", "et": "20261106"},
    ),
    (
        "daily_chinext",
        "daily",
        "/hsstock/history/300364.SZ/d/n/",
        {"st": "20260928", "et": "20261106"},
    ),
    (
        "flow_star",
        "flow",
        "/hsstock/history/transaction/688018/",
        {"st": "20260928", "et": "20261106"},
    ),
    (
        "flow_chinext",
        "flow",
        "/hsstock/history/transaction/300364/",
        {"st": "20260928", "et": "20261106"},
    ),
    ("flow_day", "flow_day", "/hsstock/history/transaction/20261106/688018/", {}),
    (
        "factor20",
        "factor",
        "/factor/history/main_20d_net/688018/",
        {"st": "20261106", "et": "20261106"},
    ),
    ("index_catalog", "index_catalog", "/hsindex/list/", {}),
    (
        "index300",
        "index_history",
        "/hsindex/history/000300.SH/d/",
        {"st": "20260801", "et": "20261106"},
    ),
    ("sector_catalog", "sector_catalog", "/hszg/list/", {}),
    ("class_star", "classification", "/hszg/zg/688018/", {}),
    ("class_chinext", "classification", "/hszg/zg/300364/", {}),
]


class HaltError(Exception):
    """Fixed nonsecret reason only."""


class Budget:
    def __init__(self) -> None:
        self.calls = 0
        self.connections = 0
        self.families: dict[str, int] = {}

    def reserve(self, family: str, stop: Path) -> None:
        if stop.exists():
            raise HaltError("STOP_present")
        if self.calls >= 30 or self.families.get(family, 0) >= 2:
            raise HaltError("budget_exhausted")
        self.calls += 1
        self.families[family] = self.families.get(family, 0) + 1

    def connect(self) -> None:
        if self.connections:
            raise HaltError("single_connection_closed_no_reconnect")
        self.connections += 1


def business_limit(value: Any) -> bool:  # noqa: ANN401
    if isinstance(value, dict):
        return any(
            (str(k).lower() in {"code", "error_code", "status"} and str(v) in {"103", "429"})
            or business_limit(v)
            for k, v in value.items()
        )
    if isinstance(value, list):
        return any(business_limit(v) for v in value)
    return isinstance(value, str) and bool(re.search(r"(?<!\d)(?:103|429)\s*[:：]", value))


def write(path: Path, value: Any) -> None:  # noqa: ANN401
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def main() -> int:
    logging.disable(logging.CRITICAL)
    http.client.HTTPConnection.debuglevel = 0

    def interrupted(_signal: int, _frame: Any) -> None:  # noqa: ANN401
        raise KeyboardInterrupt

    for watched in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(watched, interrupted)
    os.umask(0o077)
    budget = Budget()
    run = HERE / "results" / ("run-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-T-B81")
    outcome = "not_started"
    session = None
    secret = ""
    cleared = False
    original = urllib3.connectionpool.HTTPSConnectionPool.ConnectionCls
    try:
        run.mkdir(parents=True, exist_ok=False)
        write(
            run / "plan.json",
            {
                "max_calls": 30,
                "planned_calls": len(PLAN),
                "max_per_family": 2,
                "secret_source": "explicit_task_temporary_file",
                "single_connection": True,
                "retry": 0,
                "redirect": False,
                "requests": [
                    {"id": a, "family": b, "path_without_secret": c, "params": d}
                    for a, b, c, d in PLAN
                ],
            },
        )
        if STOP.exists():
            raise HaltError("STOP_present")
        info = SECRET.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.getuid()
        ):
            raise HaltError("secret_file_permissions_invalid")
        with SECRET.open("r", encoding="utf-8") as source:
            secret = source.read(4097).strip()
        if not secret or len(secret) > 4096 or any(c.isspace() for c in secret):
            raise HaltError("secret_file_format_invalid")

        class SingleConnection(urllib3.connection.HTTPSConnection):
            def connect(self) -> None:
                budget.connect()
                super().connect()

        urllib3.connectionpool.HTTPSConnectionPool.ConnectionCls = SingleConnection
        session = requests.Session()
        session.trust_env = False
        session.proxies = {}
        session.mount(
            "https://",
            HTTPAdapter(max_retries=0, pool_connections=1, pool_maxsize=1, pool_block=True),
        )
        for identifier, family, path, params in PLAN:
            budget.reserve(family, STOP)
            # Count durably before dispatch; a failure consumes its reservation, never a retry.
            with (run / "calls.jsonl").open("a", encoding="utf-8") as ledger:
                ledger.write(
                    json.dumps(
                        {
                            "call": budget.calls,
                            "id": identifier,
                            "state": "reserved",
                            "at": dt.datetime.now(dt.UTC).isoformat(),
                        }
                    )
                    + "\n"
                )
            if STOP.exists():
                raise HaltError("STOP_present")
            try:
                response = session.get(
                    "https://api.mairuiapi.com" + path + quote(secret, safe=""),
                    params=params,
                    timeout=(8, 25),
                    allow_redirects=False,
                )
            except HaltError:
                raise
            except BaseException:
                raise HaltError("transport_failure_no_retry") from None
            raw = response.content
            status = response.status_code
            if secret.encode() in raw or quote(secret, safe="").encode() in raw:
                raise HaltError("credential_echo_response_not_saved")
            try:
                data = response.json()
            except ValueError:
                data = None
            entry = {
                "call": budget.calls,
                "id": identifier,
                "http_status": status,
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
            with (run / "calls.jsonl").open("a", encoding="utf-8") as ledger:
                ledger.write(json.dumps(entry) + "\n")
            with (run / (identifier + ".raw")).open("xb") as target:
                target.write(raw)
            if status == 429 or business_limit(data) or re.search(rb"(?<!\d)103\s*[:\xef]", raw):
                raise HaltError("rate_limit_103_or_429")
            if not 200 <= status < 300:
                raise HaltError("http_failure_" + str(status))
            if data is None:
                raise HaltError("non_json_response_no_retry")
            if isinstance(data, dict) and any(
                str(data.get(k, "")) not in {"", "0", "200", "None", "True"}
                for k in ["code", "error_code"]
            ):
                raise HaltError("business_error_no_retry")
            print(json.dumps({"id": identifier, "http_status": status, "bytes": len(raw)}))
            time.sleep(1)
        outcome = "completed"
    except HaltError as reason:
        outcome = reason.args[0]
    except BaseException:
        outcome = "local_precondition_or_execution_failure"
    finally:
        urllib3.connectionpool.HTTPSConnectionPool.ConnectionCls = original
        try:
            SECRET.unlink(missing_ok=True)
            cleared = not SECRET.exists()
        except BaseException:
            cleared = False
        secret = ""
        if session is not None:
            with contextlib.suppress(BaseException):
                session.close()
        result = {
            "outcome": outcome,
            "reserved_calls": budget.calls,
            "tcp_connection_attempts": budget.connections,
            "temporary_secret_deleted": cleared,
            "STOP_present": STOP.exists(),
        }
        with contextlib.suppress(BaseException):
            write(run / "summary.json", result)
        print(json.dumps(result))
    return 0 if outcome == "completed" and cleared else 2


if __name__ == "__main__":
    raise SystemExit(main())
