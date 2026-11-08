# ruff: noqa: BLE001
"""Explicitly authorized T-B86 history only. Never auto-run from workers/tests.

Public-notice evidence is required BEFORE reading the authorized environment.
No official-source fetches here: an upstream restriction must not cause fallback.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import hashlib
import http.client
import json
import logging
import os
import re
import signal
import socket
import stat
import subprocess
import time
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from app.ingest.shared_gate import SharedGate, limit_code, map_legacy_stop, public_egress
from probes.tb86_offline import (
    COUNTER,
    STOP,
    TEMP_SECRET,
    HaltError,
    business_limit,
    reservation,
    validate_response,
    validate_state,
)

HERE = Path(__file__).resolve().parent
ROOT = HERE / "results/T-B86"
NOTICES = {
    "cash_600519": (
        "",  # No reviewed official 600519 notice URL; do not substitute another issuer.
        ("600519",),
    ),
    "bonus_301310": (
        "https://disc.static.szse.cn/download/disc/disk03/finalpage/2026-05-13/be86e959-b7d9-4a20-94cb-47d547845a91.PDF",
        ("301310", "2026年5月19"),
    ),
    "suspension_300451": (
        "https://disc.static.szse.cn/disc/disk03/finalpage/2025-11-10/e477880b-8a08-474a-afe6-045b0a0a7fc6.PDF",
        ("300451", "2025年11月10"),
    ),
}
# Public announcement-driven candidates, not formal strategy contents. The cash
# Window spans conflicting dates; dispatch stays blocked pending a reviewed notice.
PLAN = (
    (
        "cash_daily",
        "history_actions",
        "daily",
        "/hsstock/history/600519.SH/d/n/",
        "?st=20260624&et=20260629",
    ),
    ("cash_jnfh", "history_actions", "jnfh", "/hscp/jnfh/600519/", ""),
    (
        "bonus_daily",
        "history_actions",
        "daily",
        "/hsstock/history/301310.SZ/d/n/",
        "?st=20260515&et=20260520",
    ),
    ("bonus_jnfh", "history_actions", "jnfh", "/hscp/jnfh/301310/", ""),
    (
        "suspended_daily",
        "history_suspension",
        "daily",
        "/hsstock/history/300451.SZ/d/n/",
        "?st=20251107&et=20251112",
    ),
    (
        "control_daily",
        "history_suspension",
        "daily",
        "/hsstock/history/600519.SH/d/n/",
        "?st=20251107&et=20251112",
    ),
)


def inspect_counter(path: Path) -> dict[str, Any]:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
        ):
            raise HaltError("counter_permissions_invalid")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return validate_state(json.loads(os.read(fd, 131073)))
    finally:
        os.close(fd)


def validate_notices(root: Path) -> None:
    manifest = json.loads((root / "official/manifest.json").read_text())
    if not isinstance(manifest, list) or len(manifest) != len(NOTICES):
        raise HaltError("official_notice_evidence_incomplete")
    rows = {r["id"]: r for r in manifest}
    if set(rows) != set(NOTICES):
        raise HaltError("official_notice_evidence_incomplete")
    for identifier, (url, tokens) in NOTICES.items():
        if not url:
            candidate = urlsplit(rows[identifier]["url"])
            if (
                candidate.scheme != "https"
                or candidate.hostname != "static.sse.com.cn"
                or not candidate.path.startswith("/disclosure/listedinfo/announcement/")
                or "600519" not in candidate.path
                or not candidate.path.lower().endswith(".pdf")
                or candidate.query
                or candidate.fragment
                or candidate.username
            ):
                raise HaltError("cash_official_notice_url_unverified")
            url = rows[identifier]["url"]
        path = root / "official" / (identifier + ".pdf")
        raw = path.read_bytes()
        row = rows[identifier]
        if (
            row["url"] != url
            or row["http_status"] != 200
            or row["sha256"] != hashlib.sha256(raw).hexdigest()
            or not raw.startswith(b"%PDF-")
        ):
            raise HaltError("official_notice_provenance_invalid")
        text = subprocess.run(  # noqa: S603 - fixed executable, fixed public-evidence filename
            ["/usr/bin/pdftotext", str(path), "-"], capture_output=True, check=True, timeout=20
        ).stdout.decode("utf-8")
        compact = "".join(unicodedata.normalize("NFKC", text).split())
        if any(token not in compact for token in tokens):
            raise HaltError("official_notice_facts_unverified")
        if identifier == "cash_600519":
            # Read the announcement's A-share record-date / last-trade / ex-date row;
            # never confuse registration day with ex-date from a search snippet.
            match = re.search(r"A股(2026/6/\d{1,2})[-－](2026/6/\d{1,2})", compact)
            if match is None or match[2] not in {"2026/6/25", "2026/6/26"}:
                raise HaltError("cash_ex_date_not_verified_in_small_window")


class SingleConnection(http.client.HTTPSConnection):
    def __init__(self) -> None:
        super().__init__("api.mairuiapi.com", timeout=25)
        self.connect_attempts = 0

    def connect(self) -> None:
        if self.connect_attempts:
            raise HaltError("single_connection_no_reconnect")
        self.connect_attempts += 1

        # One resolved address / socket attempt; no fallback across DNS addresses.
        def create(address: Any, timeout: Any = None, source_address: Any = None) -> socket.socket:  # noqa: ANN401
            info = socket.getaddrinfo(address[0], address[1], type=socket.SOCK_STREAM)[0]
            sock = socket.socket(info[0], info[1], info[2])
            try:
                sock.settimeout(timeout)
                if source_address:
                    sock.bind(source_address)
                sock.connect(info[4])
                return sock
            except BaseException:
                sock.close()
                raise HaltError("connection_failure_no_retry") from None

        self._create_connection = create
        super().connect()


def execute(
    *,
    counter: Path = COUNTER,
    stop: Path = STOP,
    secret_path: Path = TEMP_SECRET,
    root: Path = ROOT,
) -> dict[str, Any]:
    logging.disable(logging.CRITICAL)
    http.client.HTTPConnection.debuglevel = 0
    result: dict[str, Any] = {
        "task": "T-B86",
        "outcome": "preflight",
        "new_reserved_calls": 0,
        "batch_total": None,
        "temporary_secret_created": False,
        "temporary_secret_deleted": None,
    }
    secret = ""
    created_inode = None
    connection = None
    gate = None
    run = None
    initial_ids: set[str] | None = None
    previous_umask = os.umask(0o077)
    try:
        if map_legacy_stop(stop):
            raise HaltError("STOP_present")
        state = inspect_counter(counter)
        result["batch_total"] = state["total"]
        initial_ids = {row["id"] for row in state["records"]}
        if state["halted"]:
            raise HaltError("batch_halted")
        ids = {"b86-" + row[0].replace("_", "-") for row in PLAN}
        if any(row["id"] in ids for row in state["records"]):
            raise HaltError("history_already_started_no_automatic_resume")
        validate_notices(root)
        gate = SharedGate.from_environment(None, "probe_tb86")
        gate.acquire()
        gate.confirm_egress(public_egress())
        # Only this explicitly authorized env name. No fallback path/key search.
        secret = os.environ.get("MAIRUI_LICENCE", "").strip()
        if not secret:
            raise HaltError("authorized_environment_missing")
        if len(secret) > 4096 or any(c.isspace() for c in secret):
            raise HaltError("authorized_environment_format_invalid")
        gate.bind_certificate(secret)
        fd = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        created_inode = os.fstat(fd).st_ino
        result["temporary_secret_created"] = True
        with os.fdopen(fd, "w") as stream:
            stream.write(secret)
            stream.flush()
            os.fsync(stream.fileno())
        if stat.S_IMODE(secret_path.lstat().st_mode) != 0o600:
            raise HaltError("temporary_secret_permissions_invalid")
        run = root / ("history-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S"))
        run.mkdir(parents=True, exist_ok=False)
        connection = SingleConnection()
        for identifier, segment, interface, path, query in PLAN:
            with reservation(
                counter,
                stop,
                segment,
                interface,
                "b86-" + identifier.replace("_", "-"),
                enabled_segments=frozenset({"history_actions", "history_suspension"}),
            ) as number:
                result["new_reserved_calls"] += 1
                result["batch_total"] = number
                if stop.exists():
                    result["outcome"] = "STOP_present"
                    raise HaltError("STOP_present")
                gate.check()
                gate.reserve()
                try:
                    connection.request(
                        "GET",
                        path + quote(secret, safe="") + query,
                        headers={"Connection": "keep-alive"},
                    )
                    response = connection.getresponse()
                    result["last_http_status"] = response.status
                    if response.status in {103, 429}:
                        gate.trip(str(response.status))
                        gate.complete()
                        result["outcome"] = "rate_limit_103_or_429"
                        raise HaltError("rate_limit_103_or_429")
                    raw = response.read(16 * 1024 * 1024 + 1)
                except HaltError:
                    raise
                except BaseException:
                    result["outcome"] = "transport_failure_no_retry"
                    raise HaltError("transport_failure_no_retry") from None
                needles = [
                    secret.encode(),
                    quote(secret, safe="").encode(),
                    json.dumps(secret)[1:-1].encode(),
                ]
                if any(needle.lower() in raw.lower() for needle in needles):
                    result["outcome"] = "credential_echo_not_saved"
                    raise HaltError("credential_echo_not_saved")
                if len(raw) > 16 * 1024 * 1024:
                    raise HaltError("response_too_large")
                try:
                    body = json.loads(raw)
                except ValueError:
                    body = None
                result["last_http_status"] = response.status
                shared_code = limit_code(response.status, body) or limit_code(
                    None, raw.decode("utf-8", errors="replace")
                )
                if shared_code:
                    gate.trip(shared_code)
                gate.complete()
                if (
                    response.status in {103, 429}
                    or business_limit(body)
                    or business_limit(raw.decode("utf-8", errors="replace"))
                ):
                    result["outcome"] = "rate_limit_103_or_429"
                    raise HaltError("rate_limit_103_or_429")
                try:
                    validate_response(response.status, body)
                except HaltError:
                    result["outcome"] = "http_or_business_failure_no_retry"
                    raise
                with (run / (identifier + ".raw")).open("xb") as target:
                    target.write(raw)
                (run / (identifier + ".meta.json")).write_text(
                    json.dumps(
                        {
                            "id": identifier,
                            "http_status": response.status,
                            "sha256": hashlib.sha256(raw).hexdigest(),
                            "bytes": len(raw),
                            "batch_reservation": number,
                        }
                    )
                )
            time.sleep(2)
        result["outcome"] = "completed_history_collection_only"
    except HaltError as exc:
        if result["outcome"] == "preflight":
            result["outcome"] = exc.args[0]
    except BaseException:
        if result["outcome"] == "preflight":
            result["outcome"] = "precondition_or_execution_failure_no_retry"
    finally:
        with contextlib.suppress(BaseException):
            map_legacy_stop(stop)
        if connection is not None:
            with contextlib.suppress(BaseException):
                connection.close()
        if created_inode is not None:
            try:
                if secret_path.lstat().st_ino != created_inode:
                    raise HaltError("temporary_secret_replaced")
                secret_path.unlink()
                result["temporary_secret_deleted"] = not secret_path.exists()
            except BaseException:
                result["temporary_secret_deleted"] = False
        if gate is not None:
            with contextlib.suppress(BaseException):
                gate.release()
        secret = ""
        os.umask(previous_umask)
        result["STOP_present"] = stop.exists()
        with contextlib.suppress(BaseException):
            final_state = inspect_counter(counter)
            planned_ids = {"b86-" + row[0].replace("_", "-") for row in PLAN}
            result["batch_total"] = final_state["total"]
            result["new_reserved_calls"] = (
                sum(
                    row["id"] in planned_ids and row["id"] not in initial_ids
                    for row in final_state["records"]
                )
                if initial_ids is not None
                else 0
            )
        if run is not None:
            with contextlib.suppress(BaseException):
                (run / "summary.json").write_text(json.dumps(result))
    return result


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="T-B86 explicit history runner / offline control check"
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--execute-authorized-history", action="store_true")
    modes.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--counter", type=Path, default=COUNTER)
    parser.add_argument("--secret-path", type=Path, default=TEMP_SECRET)
    args = parser.parse_args(argv)
    if args.preflight_only:
        # POSIX permissions/lock/state only. No credential access, files or HTTP requests.
        try:
            if STOP.exists():
                raise HaltError("STOP_present")
            state = inspect_counter(args.counter)
            if state["halted"]:
                raise HaltError("batch_halted")
            if args.secret_path.exists():
                raise HaltError("temporary_secret_already_exists")
            result = {
                "task": "T-B86",
                "outcome": "offline_controls_ready",
                "batch_total": state["total"],
                "new_calls": 0,
                "official_notices_checked": False,
                "credential_read": False,
            }
            code = 0
        except (HaltError, OSError, ValueError):
            result = {"task": "T-B86", "outcome": "offline_controls_not_ready", "new_calls": 0}
            code = 2
        print(json.dumps(result))
        return code
    if not args.execute_authorized_history:
        print(
            json.dumps(
                {
                    "task": "T-B86",
                    "outcome": "explicit_authorized_history_flag_required",
                    "new_calls": 0,
                }
            )
        )
        return 2

    def interrupted(_sig: int, _frame: Any) -> None:  # noqa: ANN401
        raise KeyboardInterrupt

    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, interrupted)
    result = execute(counter=args.counter, secret_path=args.secret_path)
    print(json.dumps(result))
    return (
        0
        if result["outcome"] == "completed_history_collection_only"
        and result["temporary_secret_deleted"]
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
