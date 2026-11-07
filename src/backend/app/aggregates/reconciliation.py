"""One T-A16 reconciliation reader for reports, today and the item read endpoint."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import Connection, select

from app.db.tables.accounts import reconciliation_items, reconciliation_runs
from app.db.tables.market import securities

IMPORTANT = frozenset({"quantity_mismatch", "missing_in_broker", "missing_in_ours"})


def read(conn: Connection, account_id: uuid.UUID | None, at: dt.datetime) -> dict[str, Any]:
    run = (
        conn.execute(
            select(reconciliation_runs)
            .where(
                reconciliation_runs.c.account_id == account_id,
                reconciliation_runs.c.created_at <= at,
            )
            .order_by(reconciliation_runs.c.created_at.desc(), reconciliation_runs.c.id.desc())
            .limit(1)
        ).first()
        if account_id
        else None
    )
    if run is None:
        return {
            "status": "not_imported",
            "as_of": None,
            "diff_count": 0,
            "important_count": 0,
            "items": [],
        }
    rows = conn.execute(
        select(reconciliation_items, securities.c.name)
        .outerjoin(securities, securities.c.code == reconciliation_items.c.security_code)
        .where(reconciliation_items.c.run_id == run.id)
        .order_by(reconciliation_items.c.id)
    ).all()
    items = [
        {
            "kind": r.kind,
            "security_code": r.security_code,
            "name": (r.name or r.security_code) if r.security_code else None,
            "ours": r.ours.get("value") if isinstance(r.ours, dict) else r.ours,
            "broker": r.broker.get("value") if isinstance(r.broker, dict) else r.broker,
            "diff": r.diff.get("value") if isinstance(r.diff, dict) else r.diff,
            "important": r.kind in IMPORTANT,
            "note": "；".join(r.possible_causes or []),
        }
        for r in rows
        if r.resolution is None
    ]
    return {
        "status": run.status,
        "as_of": run.created_at,
        "items": items,
        "diff_count": len(items),
        "important_count": sum(i["important"] for i in items),
    }
