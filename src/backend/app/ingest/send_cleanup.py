"""Durable proof for a known pre-HTTP busy; never refunds an unknown send.

A small private cleanup intent makes the existing DB/file compensation restartable.
It is not a budget source. Only the matching request UUID and recorded lease token
may be repaired; unrecorded unfinished sends/leases remain closed.
"""

from __future__ import annotations

import math
import os
import stat
import uuid
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import Engine, delete, select, update

from app.db.tables.market import master_runs
from app.db.tables.ops import ingest_request_log
from app.db.tables.vendor import master_vendor_batches as batches
from app.ingest import send_control
from app.ingest.send_state import MinuteLedger, private_json
from app.ingest.shared_gate import GateClosedError, _sync_directory, _write


class CleanupPendingError(GateClosedError):
    pass


class UnsentCleanup:
    def __init__(self, root: Path, request_id: uuid.UUID) -> None:
        self.root, self.request_id = root, request_id
        self.path = root / f"unsent-{request_id}.json"

    def exists(self) -> bool:
        try:
            self.path.lstat()
            return True
        except FileNotFoundError:
            return False

    def create(
        self,
        minute: MinuteLedger,
        *,
        kind: str,
        owner: uuid.UUID,
        dataset: str | None = None,
        lease_token: str | None = None,
        temporary: tuple[Path, tuple[int, int]] | None = None,
    ) -> None:
        if not send_control.owned(self.root) or send_control.wire_started(self.root):
            raise CleanupPendingError("unsent_cleanup_proof_required")
        if minute.pending is None:
            raise CleanupPendingError("unsent_cleanup_reservation_required")
        value = {
            "schema": "product-unsent/v1",
            "request_id": str(self.request_id),
            "kind": kind,
            "owner": str(owner),
            "dataset": dataset,
            "minute_file": minute.path.name,
            "pending": minute.pending,
            "prior_inflight": minute.original["inflight"],
            "lease_token": lease_token,
            "temporary": (
                {"path": str(temporary[0]), "device": temporary[1][0], "inode": temporary[1][1]}
                if temporary is not None
                else None
            ),
        }
        if not self.exists():
            _write(self.path, value, exclusive=True)

    def run(self, engine: Engine, *, refund: Callable[[], None] | None = None) -> None:
        if not send_control.owned(self.root):
            raise CleanupPendingError("unsent_cleanup_lock_required")
        try:
            value = private_json(self.path)
            if (
                value.get("schema") != "product-unsent/v1"
                or value.get("request_id") != str(self.request_id)
                or value.get("kind") not in {"daily", "verify"}
                or Path(value["minute_file"]).name != value["minute_file"]
                or not value["minute_file"].endswith(".requests.json")
                or type(value["prior_inflight"]) is not bool
            ):
                raise ValueError
            owner = uuid.UUID(value["owner"])
            dataset = value["dataset"]
            if value["kind"] == "daily" and (
                dataset not in {"hslt_list", "bj_list", "kc_list"}
                or uuid.uuid5(owner, dataset) != self.request_id
            ):
                raise ValueError
            minute = MinuteLedger(self.root, owner)
            minute.path = self.root / value["minute_file"]
            minute.pending = value["pending"]
            minute.original = {"inflight": value["prior_inflight"]}
            if (
                not isinstance(minute.pending, dict)
                or not minute.pending.get("calls")
                or type(minute.pending["calls"][-1]) not in {int, float}
                or not math.isfinite(minute.pending["calls"][-1])
            ):
                raise ValueError
            identity = self.path.lstat()
            # 1: clear the business attempt marker. The durable proof stays until
            # every refund and the final queued-row deletion has committed.
            with engine.begin() as conn:
                if value["kind"] == "daily":
                    batch = conn.execute(select(batches).where(batches.c.id == owner)).one()
                    parent = conn.execute(
                        select(master_runs)
                        .where(master_runs.c.id == batch.master_run_id)
                        .with_for_update()
                    ).one()
                    attempts = list(parent.stats.get("attempted", []))
                    if dataset in attempts:
                        attempts.remove(dataset)
                        conn.execute(
                            update(master_runs)
                            .where(master_runs.c.id == parent.id)
                            .values(stats={**parent.stats, "attempted": attempts})
                        )
                else:
                    conn.execute(
                        update(ingest_request_log)
                        .where(
                            ingest_request_log.c.id == self.request_id,
                            ingest_request_log.c.status == "queued",
                        )
                        .values(status="dropped")
                    )
            # 2: refund only our known unsent minute entry and daily reservation.
            minute.cancel_unsent()
            if value["kind"] == "daily":
                if refund is not None:
                    refund()
                else:
                    from app.ingest.send_governance import _ledger, _persist

                    path = self.root / "daily_lists.count"
                    with _ledger(path) as (fd, state):
                        state["records"] = [
                            r for r in state["records"] if r["id"] != str(self.request_id)
                        ]
                        _persist(fd, path, state)
            # SIGKILL does not execute the caller's finally. Remove only the
            # exact temporary inode recorded by this known-unsent operation.
            temporary = value.get("temporary")
            if temporary is not None:
                path = Path(temporary["path"])
                try:
                    info = path.lstat()
                except FileNotFoundError:
                    info = None
                if (
                    info is not None
                    and stat.S_ISREG(info.st_mode)
                    and stat.S_IMODE(info.st_mode) == 0o600
                    and info.st_uid == os.geteuid()
                    and info.st_nlink == 1
                    and (info.st_dev, info.st_ino) == (temporary["device"], temporary["inode"])
                ):
                    path.unlink()
                    _sync_directory(path.parent)
            # A known verification lease is not an unknown/crashed probe lease.
            if value["lease_token"] is not None:
                lease = self.root / "single-egress.lease.json"
                if os.path.lexists(lease):
                    current = private_json(lease)
                    if (
                        current.get("token") == value["lease_token"]
                        and current.get("source") == "product_verify"
                    ):
                        lease.unlink()
                        _sync_directory(self.root)
            # 3: remove only this known unsent queued/dropped verification row.
            if value["kind"] == "verify":
                with engine.begin() as conn:
                    conn.execute(
                        delete(ingest_request_log).where(
                            ingest_request_log.c.id == self.request_id,
                            ingest_request_log.c.status.in_(["queued", "dropped"]),
                        )
                    )
            current_info = self.path.lstat()
            if (identity.st_dev, identity.st_ino) != (current_info.st_dev, current_info.st_ino):
                raise ValueError
            self.path.unlink()
            _sync_directory(self.root)
        except Exception:  # noqa: BLE001 - persist the fixed pending classification, never a DSN
            # No business failure/ACK while compensation is incomplete or unknown.
            raise CleanupPendingError("unsent_cleanup_pending") from None


def recover_daily(engine: Engine, root: Path, bid: uuid.UUID) -> None:
    from app.ingest.send_governance import DATASETS

    for dataset in DATASETS:
        cleanup = UnsentCleanup(root, uuid.uuid5(bid, dataset))
        if cleanup.exists():
            with send_control.critical(root, blocking=False):
                cleanup.run(engine)
