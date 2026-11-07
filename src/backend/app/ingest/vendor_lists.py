"""§4.6.5A ingest 交接入口；只接收已有采集调度器给出的规范化结果。

fetch_results 是外呼/离线注入边界，应由 ingest 的 IngestCore P1 令牌桶、逐项重试
和既有失败策略驱动；这里不另造外呼器、不解密证书、不在 worker 采集。
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import redis
from sqlalchemy import Engine, insert, select, update

from app.db.tables.vendor import DATASETS
from app.db.tables.vendor import master_vendor_batches as batches
from app.db.tables.vendor import master_vendor_list_rows as rows_table
from app.ingest.intents import VendorIntent, parse_intent
from app.master.vendor import APPLY_TASK, licence_available


@dataclass(frozen=True)
class VendorRow:
    security_code: str
    vendor_name: str | None
    dup_conflict: bool = False


@dataclass(frozen=True)
class DatasetResult:
    dataset: str
    rows: tuple[VendorRow, ...] = ()
    raw_payload_id: UUID | None = None
    error_code: str | None = None


def _normalize(
    results: Sequence[DatasetResult],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    mapped = {r.dataset: r for r in results}
    if len(mapped) != len(results) or set(mapped) - set(DATASETS):
        raise ValueError("invalid dataset results")
    summaries, rows = [], []
    failed = False
    for dataset in DATASETS:
        result = mapped.get(dataset)
        ok = result is not None and result.error_code is None
        summary = {
            "dataset": dataset,
            "status": "ok" if ok else "failed",
            "row_count": 0,
            "raw_payload_id": str(result.raw_payload_id)
            if result and isinstance(result.raw_payload_id, UUID)
            else None,
            "error_code": None if ok else "fetch_failed",
        }
        if not ok:
            failed |= dataset != "hsrl_real"
        else:
            seen = set()
            if result is None:
                raise ValueError("missing successful result")
            for row in result.rows:
                if (
                    not re.fullmatch(r"[0-9]{6}[.](SH|SZ|BJ)", row.security_code)
                    or row.security_code in seen
                    or type(row.dup_conflict) is not bool
                    or (
                        row.vendor_name is not None
                        and (not isinstance(row.vendor_name, str) or len(row.vendor_name) > 128)
                    )
                    or (row.dup_conflict and dataset != "hsrl_real")
                ):
                    raise ValueError("invalid normalized public rows")
                seen.add(row.security_code)
                rows.append(
                    {
                        "dataset": dataset,
                        "security_code": row.security_code,
                        "vendor_name": row.vendor_name,
                        "dup_conflict": row.dup_conflict,
                    }
                )
            summary["row_count"] = len(result.rows)
        summaries.append(summary)
    return summaries, rows, failed


def process_vendor_intent(
    engine: Engine,
    rds: redis.Redis,
    fields: Mapping[bytes | str, bytes | str],
    *,
    fetch_results: Callable[[VendorIntent], Sequence[DatasetResult]],
    clock: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
) -> str:
    """先检查批次/期限/自身作用域，再调用采集边界；提交后才通知 apply。

    此入口可离线注入规范化采集结果，但不假称已经验收真实外呼循环。
    """
    intent = parse_intent(fields)
    if not isinstance(intent, VendorIntent):
        raise ValueError("not a vendor_lists intent")
    with engine.begin() as conn:
        batch = (
            conn.execute(select(batches).where(batches.c.id == intent.batch_id).with_for_update())
            .mappings()
            .one_or_none()
        )
        if (
            batch is None
            or batch["source_licence_id"] != intent.licence_id
            or batch["deadline_at"] != intent.deadline_at
        ):
            raise ValueError("vendor_lists metadata mismatch")
        if batch["status"] != "requested":
            return "noop"
        if clock() >= batch["deadline_at"]:
            conn.execute(
                update(batches)
                .where(batches.c.id == intent.batch_id)
                .values(status="expired", error_code="deadline_exceeded")
            )
            return "expired"
        usable = licence_available(conn, intent.licence_id, clock())
    try:
        results = fetch_results(intent) if usable else []
        summaries, rows, failed = _normalize(results)
    except Exception:  # noqa: BLE001  不把异常原文/上游 URL/证书回显带入批次或队列
        summaries, rows, failed = _normalize([])
    if not usable:
        failed = True
    status = "failed" if failed else "fetched"
    with engine.begin() as conn:
        batch = (
            conn.execute(select(batches).where(batches.c.id == intent.batch_id).with_for_update())
            .mappings()
            .one()
        )
        if batch["status"] != "requested":
            return "noop"
        if rows:
            conn.execute(insert(rows_table), [{"batch_id": intent.batch_id, **row} for row in rows])
        conn.execute(
            update(batches)
            .where(batches.c.id == intent.batch_id)
            .values(
                status=status,
                fetched_at=clock(),
                datasets=summaries,
                error_code=("licence_unavailable" if not usable else "list_failed")
                if failed
                else None,
            )
        )
    rds.lpush(
        "jobs:worker", json.dumps({"task": APPLY_TASK, "args": {"batch_id": str(intent.batch_id)}})
    )
    return status
