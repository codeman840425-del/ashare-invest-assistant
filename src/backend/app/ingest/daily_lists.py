"""T-B90 serial daily adapter; invoked only after a server-side approval receipt.

No network/secret access on import. Real I/O is isolated to wire() and the
existing HPKE vault. Tests substitute only the upstream and credential boundary,
never persisted batches/history or their results. No retries or redirects.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import stat
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote

from sqlalchemy import Engine, insert, select, text, update

from app.db.tables.licences import user_data_licences
from app.db.tables.market import master_runs, securities
from app.db.tables.vendor import master_vendor_batches as batches
from app.db.tables.vendor import master_vendor_list_rows as rows
from app.ingest.vault import LicenceVault, SealedLicence
from app.master.daily_delivery import (
    APPLY,
    KIND,
    LISTS,
    STREAM,
    Grant,
    eligible,
    live_budget_issue,
    read_grant,
)

PATHS = dict(zip(LISTS, ("/hslt/list/", "/bj/list/all/", "/kc/list/all/"), strict=True))
TEMP = Path("/run/aia/tmp/mairui-daily.tmp")
STOP = Path(__file__).resolve().parents[2] / "probes/results/STOP"
HALT = Path("/run/aia/state/halt/mairui-daily.HALTED")
GROUP = "mairui-daily-v1"


class DailyHaltError(RuntimeError):
    """Fixed diagnostic only; never chain an upstream exception or URL."""


def wire(path: str, secret: str) -> tuple[int, object]:
    """Compatibility shim: real sockets live only in ``app.ingest.egress._https_get``."""
    if live_budget_issue():
        raise DailyHaltError("daily_http_budget_unresolved")
    from app.ingest.egress import _https_get

    return _https_get(path, secret)


def limited(status: int, body: object) -> bool:
    if status in (103, 429):
        return True
    if isinstance(body, dict):
        for key, value in body.items():
            if str(key).lower() in {"code", "error_code", "status"} and (
                str(value) in {"103", "429"}
                or (isinstance(value, (int, float)) and value in (103, 429))
            ):
                return True
            if (
                isinstance(value, (dict, list)) or str(key).lower() in {"error", "msg", "message"}
            ) and limited(200, value):
                return True
        return False
    if isinstance(body, list):
        return any(limited(200, item) for item in body)
    if isinstance(body, str):
        return bool(re.search(r"(?<!\d)(103|429)(?!\d)", body))
    return False


def credential(engine: Engine, lid: uuid.UUID) -> str:
    with engine.connect() as conn:
        row = conn.execute(
            select(
                user_data_licences.c.id,
                user_data_licences.c.user_id,
                user_data_licences.c.seal_key_version,
                user_data_licences.c.ciphertext,
            ).where(user_data_licences.c.id == lid)
        ).one()
    return LicenceVault.from_secrets().open(
        SealedLicence(row.id, row.user_id, row.ciphertext, row.seal_key_version)
    )


def temporary(path: Path, value: str) -> tuple[int, int]:
    """Create an exclusive 0600 regular file for credential material.

    O_EXCL + O_NOFOLLOW refuse clobbering a live peer or following a symlink.
    T-A85 B-2: a leftover *regular* file after SIGKILL is unlinked without reading
    or logging its contents, then recreated — so residue cannot permanently halt
    collection. Non-regular leftovers are refused. Halt flags are never cleared here.
    """
    try:
        info = path.lstat()
    except FileNotFoundError:
        info = None
    if info is not None:
        if not stat.S_ISREG(info.st_mode):
            raise DailyHaltError("temp_path_not_regular")
        try:
            path.unlink()  # discard residue; never read/print contents
        except FileNotFoundError:
            pass
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    identity = os.fstat(fd)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(value.encode())
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        remove_owned(path, (identity.st_dev, identity.st_ino))
        raise
    return identity.st_dev, identity.st_ino


def remove_owned(path: Path, identity: tuple[int, int]) -> None:
    try:
        info = path.lstat()
        if stat.S_ISREG(info.st_mode) and (info.st_dev, info.st_ino) == identity:
            path.unlink()
    except FileNotFoundError:
        pass


def normalize(body: object, known: dict[str, list[str]]) -> list[tuple[str, str]]:
    if not isinstance(body, list) or not body:
        raise DailyHaltError("empty_or_invalid_list")
    found: dict[str, str] = {}
    for item in body:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("dm"), str)
            or not isinstance(item.get("mc"), str)
            or not item["mc"].strip()
        ):
            raise DailyHaltError("list_schema_invalid")
        code, name = item["dm"], item["mc"].strip()
        if re.fullmatch(r"\d{6}", code):
            matches = known.get(code, [])
            if len(matches) != 1:
                continue  # Never infer exchange or create a security.
            code = matches[0]
        elif code not in {x for group in known.values() for x in group}:
            continue
        if code in found and found[code] != name:
            raise DailyHaltError("duplicate_name_conflict")
        found[code] = name
    return sorted(found.items())


def process(
    engine: Engine,
    bid: uuid.UUID,
    grant: Grant | None,
    *,
    clock: Callable[[], dt.datetime],
    upstream: Callable[[str, str], tuple[int, object]] = wire,
    secret_loader: Callable[[Engine, uuid.UUID], str] = credential,
    temp: Path = TEMP,
    stop: Path = STOP,
    halt: Path = HALT,
    pause: Callable[[float], None] = time.sleep,
) -> str:
    if live_budget_issue():
        return "budget_contract_unresolved"
    identity = None
    secret = None
    # T-A87: STOP/HALT before taking single-egress (outermost lock).
    if stop.exists() or halt.exists():
        with engine.begin() as conn:
            b = conn.execute(select(batches).where(batches.c.id == bid).with_for_update()).first()
            if b is not None and b.status == "requested":
                conn.execute(
                    update(batches)
                    .where(batches.c.id == bid)
                    .values(status="failed", error_code="STOP_or_halt_present")
                )
        return "failed"
    from app.ingest.egress import EgressDenied, mairui_get, single_egress
    from app.ingest.runtime import get_ingest_core
    from app.ingest.state import Priority
    from app.ingest.upstream import Signal

    # Session lock spans reservation commits and every HTTP request. No retry.
    with single_egress(engine) as lease:
        if lease is None:
            return "busy"
        try:
            with engine.begin() as conn:
                b = conn.execute(
                    select(batches).where(batches.c.id == bid).with_for_update()
                ).first()
                if b is None:
                    return "missing"
                p = conn.execute(
                    select(master_runs).where(master_runs.c.id == b.master_run_id).with_for_update()
                ).one()
                if p.stats.get("task") != KIND:
                    return "not_daily"
                if b.status != "requested":
                    return "noop"
                issue = None
                current_grant = read_grant()
                if (
                    current_grant != grant
                    or grant is None
                    or grant.digest != p.stats.get("receipt_digest")
                    or grant.licence_id != b.source_licence_id
                    or not eligible(conn, grant, clock())
                ):
                    issue = "authorization_unavailable"
                elif stop.exists() or halt.exists():
                    issue = "STOP_or_halt_present"
                elif clock() >= b.deadline_at:
                    issue = "deadline_exceeded"
                elif p.stats.get("attempted"):
                    issue = "uncertain_prior_attempt_no_retry"
                if issue:
                    conn.execute(
                        update(batches)
                        .where(batches.c.id == bid)
                        .values(status="failed", error_code=issue)
                    )
                    return "failed"
                known: dict[str, list[str]] = {}
                for code in conn.execute(select(securities.c.code)).scalars():
                    known.setdefault(code[:6], []).append(code)
                lid = b.source_licence_id
                parent_id = p.id
            if grant is None:
                raise DailyHaltError("authorization_unavailable")
            secret = secret_loader(engine, lid)
            identity = temporary(temp, secret)
            all_rows: list[dict[str, Any]] = []
            summaries = []
            for index, dataset in enumerate(LISTS):
                if index:
                    pause(60)  # At most one request/minute, even override=1.
                if stop.exists() or halt.exists():
                    raise DailyHaltError("STOP_or_halt_present")
                # Durable write-ahead reservation: a restarted process never repeats
                # an uncertain external request, even after a response/commit crash.
                with engine.begin() as conn:
                    parent = conn.execute(
                        select(master_runs).where(master_runs.c.id == parent_id).with_for_update()
                    ).one()
                    current = read_grant()
                    if (
                        current is None
                        or current.digest != grant.digest
                        or clock() >= b.deadline_at
                        or not eligible(conn, grant, clock())
                    ):
                        raise DailyHaltError("authorization_expired_or_licence_paused")
                    attempts = list(parent.stats.get("attempted", []))
                    if dataset in attempts or len(attempts) >= 3:
                        raise DailyHaltError("daily_budget_exhausted")
                    attempts.append(dataset)
                    conn.execute(
                        update(master_runs)
                        .where(master_runs.c.id == parent_id)
                        .values(stats={**parent.stats, "attempted": attempts})
                    )
                if stop.exists() or halt.exists():
                    raise DailyHaltError("STOP_or_halt_present")
                # HTTP only via egress; must not hold an open transaction here.
                try:
                    result = mairui_get(
                        lease=lease,
                        core=get_ingest_core(),
                        engine=engine,
                        licence_id=lid,
                        user_id=grant.user_id,
                        path=PATHS[dataset],
                        secret=secret,
                        priority=Priority.P1,
                        clock=clock,
                        stop=stop,
                        halt=halt,
                        transport=upstream,
                    )
                except EgressDenied as denied:
                    raise DailyHaltError(denied.code) from None
                status, body = result.status, result.body
                if result.signal == Signal.IP_LIMITED or limited(status, body):
                    with engine.begin() as conn:
                        parent = conn.execute(
                            select(master_runs)
                            .where(master_runs.c.id == parent_id)
                            .with_for_update()
                        ).one()
                        conn.execute(
                            update(master_runs)
                            .where(master_runs.c.id == parent_id)
                            .values(
                                stats={
                                    **parent.stats,
                                    "upstream_halted": True,
                                    "halt_reason": "limit_103_or_429",
                                }
                            )
                        )
                    raise DailyHaltError("limit_103_or_429")
                if status != 200 or isinstance(body, dict):
                    raise DailyHaltError("upstream_failed_no_retry")
                encoded = json.dumps(body, ensure_ascii=False)
                if secret in encoded or quote(secret, safe="") in encoded:
                    raise DailyHaltError("credential_echo_rejected")
                normalized = normalize(body, known)
                all_rows.extend(
                    {
                        "batch_id": bid,
                        "dataset": dataset,
                        "security_code": code,
                        "vendor_name": name,
                        "dup_conflict": False,
                    }
                    for code, name in normalized
                )
                summaries.append({"dataset": dataset, "status": "ok", "row_count": len(normalized)})
            with engine.begin() as conn:
                if all_rows:
                    conn.execute(insert(rows), all_rows)
                conn.execute(
                    update(batches)
                    .where(batches.c.id == bid)
                    .values(
                        status="fetched", fetched_at=clock(), datasets=summaries, error_code=None
                    )
                )
            return "fetched"
        except Exception:  # noqa: BLE001 - sanitize upstream/credential exceptions, never log them
            with engine.begin() as conn:
                conn.execute(
                    update(batches)
                    .where(batches.c.id == bid, batches.c.status == "requested")
                    .values(status="failed", error_code="daily_collection_failed_no_retry")
                )
            return "failed"
        finally:
            secret = None
            if identity is not None:
                remove_owned(temp, identity)


def tick(
    engine: Engine,
    rds: Any,  # noqa: ANN401 - Redis sync response type varies by client version
    *,
    clock: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
    grant: Grant | None = None,
    pause: Callable[[float], None] = time.sleep,
) -> int:
    """Own consumer group on existing stream; other intent consumers unaffected."""
    if live_budget_issue():
        return 0
    from redis.exceptions import ResponseError

    try:
        rds.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise RuntimeError("daily_stream_unavailable") from None
    pending = rds.xautoclaim(
        STREAM, GROUP, "daily-single", min_idle_time=60000, start_id="0-0", count=1
    )[1]
    messages = (
        pending
        or (rds.xreadgroup(GROUP, "daily-single", {STREAM: ">"}, count=1) or [(None, [])])[0][1]
    )
    count = 0
    for mid, fields in messages:
        if fields.get(b"kind") == KIND.encode():
            try:
                bid = uuid.UUID(fields[b"batch_id"].decode())
                result = process(
                    engine,
                    bid,
                    grant if grant is not None else read_grant(),
                    clock=clock,
                    pause=pause,
                )
                if result == "busy":
                    continue
                rds.lpush(
                    "jobs:worker", json.dumps({"task": APPLY, "args": {"batch_id": str(bid)}})
                )
            except (ValueError, KeyError):
                pass
            count += 1
        rds.xack(STREAM, GROUP, mid)
    return count
