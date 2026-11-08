"""Trusted ingest completion adapter: licence-scoped raw quotes, never network IO.

Called with normalized facts by the server-side ingest completion pipeline; no HTTP
write endpoint and no caller-supplied owner/expiry or sharing fallback.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from decimal import Decimal

from sqlalchemy import Connection, select
from sqlalchemy.dialects.postgresql import insert

from app.config import Settings
from app.db.tables.licences import user_data_licences
from app.db.tables.market import securities
from app.db.tables.reviews import data_snapshots
from app.db.tables.users import users
from app.workers.assembly import canonical

SCHEMA = "owned-unadjusted-quote-v1"


def record_quote(
    conn: Connection,
    settings: Settings,
    *,
    licence_id: uuid.UUID,
    code: str,
    observed_at: dt.datetime,
    fetched_at: dt.datetime,
    now: dt.datetime,
    price: Decimal,
    prev_close: Decimal | None,
    is_suspended: bool | None,
) -> uuid.UUID:
    """Persist source facts only; unknown suspension/previous close stays unknown."""
    if any(t.tzinfo is None for t in (observed_at, fetched_at, now)) or not (
        observed_at <= fetched_at <= now
    ):
        raise ValueError("invalid_quote_clock")
    if (
        not price.is_finite()
        or price <= 0
        or (prev_close is not None and (not prev_close.is_finite() or prev_close <= 0))
    ):
        raise ValueError("invalid_quote_prices")
    if is_suspended is not None and type(is_suspended) is not bool:
        raise ValueError("invalid_suspension_fact")
    licence = conn.execute(
        select(user_data_licences.c.id, user_data_licences.c.user_id)
        .join(users, users.c.id == user_data_licences.c.user_id)
        .where(
            users.c.status == "approved",
            user_data_licences.c.id == licence_id,
            user_data_licences.c.status == "active",
            user_data_licences.c.deleted_at.is_(None),
            user_data_licences.c.created_at <= now,
        )
    ).first()
    if licence is None:
        raise ValueError("owned_quote_licence_unavailable")
    if not conn.execute(select(securities.c.code).where(securities.c.code == code)).first():
        raise ValueError("unknown_quote_security")
    expiry = observed_at + dt.timedelta(
        seconds=settings.business.realtime.intervals.effective_stale_threshold_s
    )
    body = {
        "schema_version": SCHEMA,
        "security_code": code,
        "adj_type": "none",
        "data_as_of": observed_at.isoformat(),
        "available_at": fetched_at.isoformat(),
        "expires_at": expiry.isoformat(),
        "price": str(price),
        "prev_close": str(prev_close) if prev_close is not None else None,
        "is_suspended": is_suspended,
        "data_status": "fresh" if now <= expiry else "stale",
    }
    digest = hashlib.sha256(canonical(body).encode()).hexdigest()
    identifier = uuid.uuid5(licence_id, digest)
    prior = conn.execute(select(data_snapshots).where(data_snapshots.c.id == identifier)).first()
    if prior is not None:
        if (
            prior.user_id != licence.user_id
            or prior.licence_id != licence.id
            or prior.hash != digest
        ):
            raise ValueError("owned_quote_identity_conflict")
        return identifier
    conn.execute(
        insert(data_snapshots)
        .values(
            id=identifier,
            user_id=licence.user_id,
            licence_id=licence.id,
            purpose="signal",
            hash=digest,
            items=body,
            created_at=fetched_at,
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    return identifier
