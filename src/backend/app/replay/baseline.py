"""T-B70 deterministic, user-scoped daily input job (no vendor/network imports).

Only generated inputs are accepted. Synthetic sessions are an explicit test calendar,
not a claim about the exchange calendar or the real securities' status/prices.
The caller owns the transaction; no migrations, credentials or production market writes.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, select, text
from sqlalchemy.dialects.postgresql import insert

from app.common.errors import AppError, ErrorCode
from app.db.tables.reviews import data_snapshots
from app.importing.parsers.tdx import POSITIONS
from app.importing.text import display_width

VERSION = "tb70-synthetic-v1"
CLOCK = dt.datetime(2026, 10, 30, 8, tzinfo=dt.UTC)
# Codes/boards were explicitly supplied for this test. Never infer issuer facts.
INSTRUMENTS = (
    ("688018.SH", "star", "normal"),
    ("688073.SH", "star", "suspension"),
    ("300364.SZ", "chinext", "delisted"),
    ("301218.SZ", "chinext", "missing"),
)


def positions_file(encoding: str = "utf-8") -> bytes:
    """Purely invented TDX quantities/costs/holder IDs; no sample file access."""
    if encoding not in {"utf-8", "gbk"}:
        raise ValueError("unsupported synthetic encoding")
    widths = (8, 14, 24, 14, 14, 14, 14, 20, 18, 18, 22)

    def line(values: tuple[str, ...]) -> str:
        return "".join(
            value + " " * (width - display_width(value))
            for value, width in zip(values, widths, strict=True)
        ).rstrip()

    lines = [
        "人民币: 余额:100000.00  可用:100000.00",
        "-" * 80,
        "",
        line(tuple(column.name for column in POSITIONS.columns)),
    ]
    for index, (code, _, _) in enumerate(INSTRUMENTS, 1):
        lines.append(
            line(
                (
                    str(index),
                    code[:6],
                    f"模拟证券{index}",
                    "200",
                    "200",
                    "10.00",
                    "10.00",
                    "2000.00",
                    "0.00",
                    "0.00",
                    f"SYNTHETIC{index}",
                )
            )
        )
    return ("\r\n".join(lines) + "\r\n").encode(encoding)


def payload() -> dict[str, Any]:
    """100 invented sessions, >=90 valid bars per code, plus explicit gaps.

    Normal 20% price band is explicit test input. No ST/new-listing exception is
    inferred from a code. Such exceptions require separate explicit rule inputs.
    All bars are unadjusted CNY/share, volume shares, amount CNY; no fake factors.
    """
    days: list[dt.date] = []
    day = dt.date(2026, 1, 5)
    while len(days) < 100:
        if day.weekday() < 5:
            days.append(day)
        day += dt.timedelta(days=1)
    instruments: list[dict[str, Any]] = []
    for code, board, scenario in INSTRUMENTS:
        bars: list[dict[str, str | bool]] = []
        gaps: list[dict[str, str]] = []
        previous = Decimal("10.00")
        for index, session in enumerate(days):
            reason = (
                "suspended"
                if scenario == "suspension" and index == 50
                else "delisted"
                if scenario == "delisted" and index >= 90
                else "no_source"
                if scenario == "missing" and index == 50
                else None
            )
            if reason is not None:
                gaps.append({"trade_date": session.isoformat(), "reason": reason})
                continue
            close = Decimal("10.00") + Decimal(index % 10) / 100
            high, low = (
                max(previous, close) + Decimal("0.01"),
                min(previous, close) - Decimal("0.01"),
            )
            if not (previous * Decimal("0.8") <= low <= high <= previous * Decimal("1.2")):
                raise ValueError("synthetic normal 20% band violated")
            bars.append(
                {
                    "trade_date": session.isoformat(),
                    "open": str(previous),
                    "high": str(high),
                    "low": str(low),
                    "close": str(close),
                    "pre_close": str(previous),
                    "volume": "10000",
                    "amount": str(close * 10000),
                    "is_final": True,
                    "first_seen_at": f"{session.isoformat()}T08:00:00+00:00",
                }
            )
            previous = close
        instruments.append(
            {
                "security_code": code,
                "board": board,
                "scenario": scenario,
                "normal_limit_pct": "20",
                "limit_exception": None,
                "adjust": "none",
                "currency": "CNY",
                "price_unit": "CNY/share",
                "volume_unit": "share",
                "amount_unit": "CNY",
                "bars": bars,
                "gaps": gaps,
            }
        )
    return {
        "schema_version": VERSION,
        "simulation": True,
        "label": "模拟回放",
        "provider": "system",
        "epistemic_type": "hypothesis",
        "data_as_of": CLOCK.isoformat(),
        "calendar_basis": "synthetic_sessions_not_exchange_calendar",
        "sessions": [day.isoformat() for day in days],
        "instruments": instruments,
        "positions_sha256": hashlib.sha256(positions_file()).hexdigest(),
    }


def manifest_hash(items: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            items,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def require_isolated(conn: Connection, *, app_env: str) -> None:
    """Fail closed before writes; dedicated networkless UNIX-socket DB only.

    Deliberately does not consult Settings, environment secrets or licence tables.
    This is a local job, not an HTTP endpoint or a production task registration.
    """
    url = conn.engine.url
    host = str(url.query.get("host", ""))
    if (
        app_env != "test"
        or url.get_backend_name() != "postgresql"
        or not (url.database or "").startswith("tb70_")
        or url.host is not None
        or not host.startswith("/tmp/tb70-")  # noqa: S108
        or conn.execute(text("select current_database()")).scalar_one() != url.database
    ):
        raise ValueError("replay requires a dedicated tb70_ test database and UNIX socket")


def load(conn: Connection, user_id: uuid.UUID, *, app_env: str) -> uuid.UUID:
    """Repeatable job: deterministic per-user ID + PK conflict handling (race safe)."""
    require_isolated(conn, app_env=app_env)
    items = payload()
    digest = manifest_hash(items)
    snapshot_id = uuid.uuid5(uuid.NAMESPACE_URL, f"{VERSION}:{user_id}:{digest}")
    conn.execute(
        insert(data_snapshots)
        .values(
            id=snapshot_id,
            user_id=user_id,
            licence_id=None,
            purpose="report",
            items=items,
            hash=digest,
            created_at=CLOCK,
        )
        .on_conflict_do_nothing(index_elements=[data_snapshots.c.id])
    )
    return snapshot_id


def read(conn: Connection, user_id: uuid.UUID, snapshot_id: uuid.UUID) -> dict[str, Any]:
    """Both ID and owner required; unknown and foreign snapshots are identical 404."""
    row = conn.execute(
        select(data_snapshots.c["items"]).where(
            data_snapshots.c.id == snapshot_id,
            data_snapshots.c.user_id == user_id,
            data_snapshots.c.licence_id.is_(None),
            data_snapshots.c.purpose == "report",
        )
    ).first()
    from app.marketdata.daily_snapshot import OWNED_VERSION

    if row is None or row[0].get("schema_version") not in {VERSION, OWNED_VERSION}:
        raise AppError(ErrorCode.NOT_FOUND)
    return dict(row[0])
