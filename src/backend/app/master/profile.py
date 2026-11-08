"""SecurityProfile public master projection; unavailable owned fields stay explicit gaps."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import Connection, select

from app.common.errors import AppError, ErrorCode
from app.db.tables.market import securities, security_code_history, security_name_history
from app.licences.service import live_row
from app.master.search import _MASTER_DATE
from app.master.sync import BEIJING
from app.master.vendor import licence_available

ATTRIBUTION = "证券列表来自上交所、深交所、北交所公开信息；巨潮仅补缺。"


def profile(conn: Connection, owner: uuid.UUID, code: str) -> dict[str, Any]:
    successor = conn.execute(
        select(security_code_history.c.code).where(security_code_history.c.old_code == code)
    ).scalar_one_or_none()
    if successor is not None:
        raise AppError(ErrorCode.NOT_FOUND, details={"superseded_by": successor})
    row = conn.execute(select(securities).where(securities.c.code == code)).first()
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND)
    if row.listing_status is None:
        raise AppError(
            ErrorCode.INTERNAL_ERROR, details={"issue": "security_master_bootstrap_required"}
        )
    if row.master_as_of is not None:
        master_day = row.master_as_of.astimezone(BEIJING).date()
    else:
        dates = conn.execute(_MASTER_DATE).all()
        if len(dates) != 3:
            raise AppError(
                ErrorCode.INTERNAL_ERROR, details={"issue": "security_master_bootstrap_required"}
            )
        master_day = min(item.day for item in dates)
    former_names = [
        {"name": item.name, "until": item.valid_until.isoformat() if item.valid_until else None}
        for item in conn.execute(
            select(security_name_history)
            .where(security_name_history.c.code == code, security_name_history.c.name != row.name)
            .order_by(security_name_history.c.valid_from.desc(), security_name_history.c.name)
        )
    ]
    code_history = [
        {
            "security_code": item.old_code,
            # Current storage does not prove an old-code end date; never infer a switch date.
            "until": item.valid_until.isoformat() if item.valid_until else None,
        }
        for item in conn.execute(
            select(security_code_history)
            .where(security_code_history.c.code == code)
            .order_by(security_code_history.c.valid_from.desc())
        )
    ]
    licence = live_row(conn, owner)
    usable = licence is not None and licence_available(conn, licence.id, dt.datetime.now(dt.UTC))
    reason = "not_yet_published" if usable else "data_licence_unavailable"
    private_fields = (
        ["suspended"]
        if row.type in {"etf", "index"}
        else ["industry", "concepts", "total_shares", "float_shares", "suspended"]
    )
    sources = [
        {
            "provider": "exchange",
            "endpoint": None,
            "fetched_at": row.master_as_of.isoformat() if row.master_as_of else None,
        }
    ]
    return {
        "security_code": row.code,
        "name": row.name,
        "type": row.type,
        "exchange": row.exchange,
        "board": None if row.type in {"etf", "index"} else row.board,
        "list_date": row.list_date,
        "list_date_basis": None if row.type in {"etf", "index"} else row.list_date_basis,
        "delist_date": row.delist_date,
        "listing_status": row.listing_status,
        "risk_flag": None if row.type == "etf" else row.risk_flag,
        "former_names": former_names,
        "code_history": code_history,
        "master_as_of": master_day.isoformat(),
        "attribution": ATTRIBUTION,
        "industry": None,
        "concepts": [],
        "total_shares": None,
        "float_shares": None,
        "suspended": None,
        "sources": sources,
        # No owned profile dataset has been ingested yet; the public date is not market freshness.
        "data_status": "partial",
        "data_as_of": None,
        "gaps": [
            {
                "key": key,
                "reason": reason,
                "message": "本人证书资料尚未取得" if usable else "本人数据证书不可用",
            }
            for key in private_fields
        ],
    }
