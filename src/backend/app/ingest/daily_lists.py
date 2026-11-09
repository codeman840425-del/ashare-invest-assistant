"""T-B90 serial daily adapter; invoked only after a server-side approval receipt.

No network/secret access on import. Real I/O is isolated to wire() and the
existing HPKE vault. Tests substitute only the upstream and credential boundary,
never persisted batches/history or their results. No retries or redirects.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import http.client
import json
import os
import re
import stat
import time
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from pathlib import Path
from typing import Any
from urllib.parse import quote

from sqlalchemy import Engine, insert, select, update

from app.config import Settings
from app.db.tables.licences import user_data_licence_status, user_data_licences
from app.db.tables.market import master_runs, securities
from app.db.tables.vendor import master_vendor_batches as batches
from app.db.tables.vendor import master_vendor_list_rows as rows
from app.ingest.live import check_egress, feedback
from app.ingest.send_cleanup import CleanupPendingError, UnsentCleanup, recover_daily
from app.ingest.send_control import (
    begin_wire,
    check_product,
    critical,
    root_from_environment,
    transport,
)
from app.ingest.send_governance import LIST_PATHS, Governance, Permit, expected_egress
from app.ingest.send_response import ResponseBodyError, read_body
from app.ingest.send_state import MinuteLedger
from app.ingest.shared_gate import (
    GateClosedError,
    SharedGate,
    _write_stop_unlocked,
    limit_code,
)
from app.ingest.upstream import Signal, classify
from app.ingest.vault import LicenceVault, SealedLicence
from app.licences.service import per_minute_limit
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
from app.master.sync import BEIJING
from app.reports.service import covered

HOST = "api.mairuiapi.com"
PATHS = dict(LIST_PATHS)
TEMP = Path("/run/aia/mairui-daily.tmp")
STOP = Path(__file__).resolve().parents[2] / "probes/results/STOP"
HALT = Path("/run/aia/mairui-daily.HALTED")
GROUP = "mairui-daily-v1"
WIRE_GATE: ContextVar[SharedGate | Permit | None] = ContextVar("mairui_wire_gate", default=None)


class DailyHaltError(RuntimeError):
    """Fixed diagnostic only; never chain an upstream exception or URL."""


class LimitResponseError(DailyHaltError):
    """Oversized response failed, with durable 103/429 evidence rather than a network error."""

    def __init__(self, code: str) -> None:
        super().__init__("transport_or_response_failed_no_retry")
        self.code = code


def wire(path: str, secret: str) -> tuple[int, object]:
    gate = WIRE_GATE.get()
    if (
        os.environ.get("MAIRUI_MODE", "replay") != "live"
        or live_budget_issue()
        or gate is None
        or not gate.inflight
    ):
        raise DailyHaltError("live_transport_closed")
    transport(
        gate.governance.root if isinstance(gate, Permit) else gate.root,
        own_token=gate.token if isinstance(gate, SharedGate) else None,
    )
    if isinstance(gate, SharedGate):
        check_product(gate)
    else:
        gate.check()
    begin_wire(gate.governance.root if isinstance(gate, Permit) else gate.root)
    if isinstance(gate, Permit):
        gate.sent = True  # The final pre-connect checks passed; outcome can now be uncertain.
    conn = http.client.HTTPSConnection(HOST, timeout=20)
    conn.set_debuglevel(0)
    try:
        conn.request("GET", path + quote(secret, safe=""))
        response = conn.getresponse()
        if response.status in (103, 429):
            return response.status, None
        return response.status, read_body(response)
    except ResponseBodyError as exc:
        if exc.code is not None:
            # The oversized response is a failure, but its limit evidence must
            # survive the business error while the dispatch mutex is still held.
            _write_stop_unlocked(
                (gate.governance.root if isinstance(gate, Permit) else gate.root) / "STOP"
            )
            raise LimitResponseError(exc.code) from None
        raise DailyHaltError("transport_or_response_failed_no_retry") from None
    except Exception:  # noqa: BLE001 - sanitize upstream/credential exceptions, never log them
        raise DailyHaltError("transport_or_response_failed_no_retry") from None
    finally:
        conn.close()


def send(
    gate: SharedGate | Permit,
    upstream: Callable[[str, str], tuple[int, object]],
    path: str,
    secret: str,
    *,
    dispatch_locked: bool = False,
) -> tuple[int, object]:
    with contextlib.ExitStack() as stack:
        if isinstance(gate, Permit):
            gate.claim(path)  # List dispatch already owns the governance critical section.
            if upstream is not wire:
                gate.sent = True  # Synthetic/alternate transport starts at this exact boundary.
        else:
            # Existing verification also uses this one transport mouth. Its old
            # authorization/accounting stays intact; only the physical mutex is shared.
            if not dispatch_locked:
                stack.enter_context(critical(gate.root, blocking=False))
            transport(gate.root, own_token=gate.token)
            check_product(gate)
        token = WIRE_GATE.set(gate)
        try:
            if upstream is not wire:
                begin_wire(gate.governance.root if isinstance(gate, Permit) else gate.root)
            return upstream(path, secret)
        finally:
            WIRE_GATE.reset(token)


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
    """O_EXCL prevents overwriting even an existing symlink or another process."""
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
    settings: Settings | None = None,
    egress: Callable[[], str] = check_egress,
) -> str:
    if os.environ.get("MAIRUI_MODE", "replay") != "live" or live_budget_issue():
        return "live_transport_closed"
    identity = None
    secret = None
    active_permit: Permit | None = None
    try:
        root = root_from_environment()
        recover_daily(engine, root, bid)
        with engine.begin() as conn:
            b = conn.execute(select(batches).where(batches.c.id == bid).with_for_update()).first()
            if b is None:
                return "missing"
            p = conn.execute(
                select(master_runs).where(master_runs.c.id == b.master_run_id).with_for_update()
            ).one()
            if p.stats.get("task") != KIND:
                return "not_daily"
            if b.status != "requested":
                return "noop"
            summaries = list(b.datasets or [])
            completed = [row["dataset"] for row in summaries if row.get("status") == "ok"]
            issue = None
            now = clock().astimezone(BEIJING)
            if (
                clock() >= b.deadline_at
                or str(now.date()) != p.stats.get("trade_date")
                or not dt.time(18) <= now.time() < dt.time(23, 59, 59)
                or not covered(conn, now.date())
            ):
                issue = "daily_window_expired"
            elif (
                grant is None
                or read_grant() != grant
                or grant.digest != p.stats.get("receipt_digest")
                or grant.licence_id != b.source_licence_id
                or not eligible(conn, grant, clock())
            ):
                issue = "authorization_unavailable"
            elif list(p.stats.get("attempted", [])) != completed:
                issue = "uncertain_prior_attempt_no_retry"
            if issue:
                outcome = "failed"
                conn.execute(
                    update(batches)
                    .where(batches.c.id == bid)
                    .values(
                        status=outcome,
                        error_code=issue,
                    )
                )
                return outcome
            if grant is None:
                raise DailyHaltError("authorization_unavailable")
            if settings is None:
                from app.config import get_settings

                settings = get_settings()
            policy = settings.business.ingest.licences.product_daily
            known: dict[str, list[str]] = {}
            for code in conn.execute(select(securities.c.code)).scalars():
                known.setdefault(code[:6], []).append(code)
            lid, parent_id = b.source_licence_id, p.id
            day = dt.date.fromisoformat(p.stats["trade_date"])
            licence = conn.execute(
                select(user_data_licence_status).where(user_data_licence_status.c.id == lid)
            ).one()
            minute_limit = per_minute_limit(settings, licence)
        governance = Governance(
            root,
            enforce=settings.business.ingest.send_governance.enforce,
            clock=clock,
            licence_id=lid,
            minute_limit=minute_limit,
            legacy_stops=(stop, halt),
        )
        # Existing egress/receipt/HPKE boundaries are mandatory in either mode.
        if egress() != expected_egress(root, lid):
            raise DailyHaltError("shared_egress_mismatch")
        secret = secret_loader(engine, lid)
        identity = temporary(temp, secret)
        for index, dataset in enumerate(LISTS):
            active_permit = None
            if dataset in completed:
                continue  # Resume only durably completed results; never resend those endpoints.
            if index:
                pause(policy.min_interval_s)
            if clock() >= b.deadline_at:
                raise GateClosedError("daily_window_expired")
            with engine.begin() as conn:
                parent = conn.execute(
                    select(master_runs).where(master_runs.c.id == parent_id).with_for_update()
                ).one()
                current = read_grant()
                if (
                    current is None
                    or current.digest != grant.digest
                    or not eligible(conn, grant, clock())
                ):
                    raise DailyHaltError("authorization_expired_or_licence_paused")
                attempts = list(parent.stats.get("attempted", []))
                if dataset in attempts:
                    raise DailyHaltError("uncertain_prior_attempt_no_retry")
                trading_day = covered(conn, clock().astimezone(BEIJING).date())

            def unsent(
                minute: MinuteLedger, refund: Callable[[], None], dataset: str = dataset
            ) -> None:
                cleanup = UnsentCleanup(root, uuid.uuid5(bid, dataset))
                cleanup.create(
                    minute,
                    kind="daily",
                    owner=bid,
                    dataset=dataset,
                    temporary=(temp, identity) if identity is not None else None,
                )
                cleanup.run(engine, refund=refund)

            with governance.dispatch(
                token=uuid.uuid5(bid, dataset),
                dataset=dataset,
                expected_day=day,
                trading_day=trading_day,
                deadline_at=b.deadline_at,
                on_unsent=unsent,
            ) as permit:
                active_permit = permit
                # Acquiring the physical lock precedes any business attempted flag.
                # Busy leaves the requested message untouched for tick retry.
                with engine.begin() as conn:
                    parent = conn.execute(
                        select(master_runs).where(master_runs.c.id == parent_id).with_for_update()
                    ).one()
                    if read_grant() != grant or not eligible(conn, grant, clock()):
                        raise DailyHaltError("authorization_expired_or_licence_paused")
                    attempts = list(parent.stats.get("attempted", []))
                    if dataset in attempts:
                        raise DailyHaltError("uncertain_prior_attempt_no_retry")
                    attempts.append(dataset)
                    conn.execute(
                        update(master_runs)
                        .where(master_runs.c.id == parent_id)
                        .values(
                            stats={**parent.stats, "attempted": attempts},
                        )
                    )
                try:
                    status, body = send(permit, upstream, PATHS[dataset], secret)
                except LimitResponseError as exc:
                    # Preserve the regular limit feedback/notification/business
                    # halt path without retaining the oversized upstream body.
                    status, body = 200, {"code": exc.code}
                except GateClosedError:
                    raise
                except Exception:  # noqa: BLE001 - transport may contain the secret URL
                    feedback(
                        engine,
                        settings,
                        lid,
                        Signal.NETWORK,
                        token=uuid.uuid5(bid, dataset),
                        at=clock(),
                        code="network",
                    )
                    raise DailyHaltError("transport_failed_no_retry") from None
                # Keep the existing response rules. Parser redesign is outside T-B102.
                code = limit_code(status, body)
                if limited(status, body):
                    _write_stop_unlocked(root / "STOP")
                signal = Signal.IP_LIMITED if code else classify(status, body)
                if signal != Signal.OK:
                    error_code = code or {
                        Signal.INVALID: "102",
                        Signal.QUOTA: "101",
                        Signal.RATE_LIMITED: "503",
                        Signal.SERVER_ERROR: "http_5xx",
                    }.get(signal)
                    feedback(
                        engine,
                        settings,
                        lid,
                        signal,
                        token=uuid.uuid5(bid, dataset),
                        at=clock(),
                        code=error_code,
                    )
                if limited(status, body):
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
                                },
                            )
                        )
                    raise DailyHaltError("limit_103_or_429")
                if status != 200 or isinstance(body, dict):
                    raise DailyHaltError("upstream_failed_no_retry")
                encoded = json.dumps(body, ensure_ascii=False)
                if secret in encoded or quote(secret, safe="") in encoded:
                    raise DailyHaltError("credential_echo_rejected")
                normalized = normalize(body, known)
                dataset_rows = [
                    {
                        "batch_id": bid,
                        "dataset": dataset,
                        "security_code": code,
                        "vendor_name": name,
                        "dup_conflict": False,
                    }
                    for code, name in normalized
                ]
                summaries.append({"dataset": dataset, "status": "ok", "row_count": len(normalized)})
                with engine.begin() as conn:
                    if dataset_rows:
                        conn.execute(insert(rows), dataset_rows)
                    conn.execute(
                        update(batches).where(batches.c.id == bid).values(datasets=summaries)
                    )
                completed.append(dataset)
        with engine.begin() as conn:
            conn.execute(
                update(batches)
                .where(batches.c.id == bid)
                .values(
                    status="fetched",
                    fetched_at=clock(),
                    datasets=summaries,
                    error_code=None,
                )
            )
        return "fetched"
    except Exception as exc:  # noqa: BLE001 - fixed diagnostics, no upstream/secret/DSN text
        if isinstance(exc, (CleanupPendingError, FileExistsError)) or (
            isinstance(exc, GateClosedError)
            and str(exc) == "shared_control_busy"
            and (active_permit is None or not active_permit.sent)
        ):
            return "busy"
        with engine.begin() as conn:
            conn.execute(
                update(batches)
                .where(batches.c.id == bid, batches.c.status == "requested")
                .values(
                    status="failed",
                    error_code=(
                        "daily_window_expired"
                        if isinstance(exc, GateClosedError) and str(exc) == "daily_window_expired"
                        else "daily_collection_failed_no_retry"
                    ),
                )
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
    settings: Settings | None = None,
) -> int:
    """Own consumer group on existing stream; other intent consumers unaffected."""
    if os.environ.get("MAIRUI_MODE", "replay") != "live" or live_budget_issue():
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
                    settings=settings,
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
