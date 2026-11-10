# ruff: noqa: ANN401, E501
"""``/watchlist`` 列表、添加、删除（T-B126，裁定见 T-A129）。"""

from __future__ import annotations

import datetime as dt
import re
import uuid
from typing import Any, Final

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from app.api.v1.trades import SECURITY_CODE_PATTERN, normalize_code, security_names
from app.auth.deps import AuthDep, EngineDep, RedisDep, SettingsDep
from app.common import idempotency
from app.common.errors import AppError, ErrorCode
from app.config import Settings
from app.db.tables.market import securities, security_code_history
from app.db.tables.realtime import user_realtime_prefs
from app.db.tables.research import watchlist_items
from app.db.tables.users import users
from app.entitlements import positive_int_entitlement

router = APIRouter()

# T-A129 §4 产品未决项的保守默认，集中于此便于改。
ALLOW_INDEX_IN_WATCHLIST: Final = False  # U1
ALLOW_DELISTED_IN_WATCHLIST: Final = False  # U2
# U3：上限不写死，回落 config/realtime.yaml 的 watchlist.per_user_cap / focus_cap。
READD_RESTORES_GROUP_NOTE: Final = False  # U4：删后再加插入新行，不恢复分组/备注。

GROUP_MAX: Final = 32
NOTE_MAX: Final = 500
_CODE_RE: Final = re.compile(SECURITY_CODE_PATTERN)
INDEX_NAME: Final = "uq_watchlist_items_user_code_active"


class WatchlistCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    # OpenAPI 使用与 trades 相同的 SECURITY_CODE_PATTERN；运行时在 _qualify 映射为 issue=invalid。
    security_code: str = Field(json_schema_extra={"pattern": SECURITY_CODE_PATTERN})
    group: str | None = None
    note: str | None = None


def _bad(field: str, issue: str, **extra: object) -> AppError:
    item: dict[str, object] = {"field": field, "issue": issue}
    item.update(extra)
    return AppError(ErrorCode.VALIDATION_ERROR, details={"fields": [item]})


def _clip(value: str | None, field: str, limit: int) -> str | None:
    if value is None:
        return None
    if len(value) > limit:
        raise _bad(field, "too_long")
    return value or None


def _caps(conn: Connection, user_id: uuid.UUID, settings: Settings, now: dt.datetime) -> dict[str, int]:
    cfg = settings.business.realtime.watchlist
    return {
        "watchlist": positive_int_entitlement(
            conn, user_id, "watchlist.per_user_cap", now, int(cfg.per_user_cap)
        ),
        "focus": positive_int_entitlement(
            conn, user_id, "intraday.focus_cap", now, int(cfg.focus_cap)
        ),
    }


def _focus_codes(conn: Connection, user_id: uuid.UUID) -> set[str]:
    row = conn.execute(
        select(user_realtime_prefs.c.focus_codes).where(user_realtime_prefs.c.user_id == user_id)
    ).scalar_one_or_none()
    return set(row or ())


def _item(row: Any, names: dict[str, str], focus: set[str]) -> dict[str, Any]:
    code = str(row.security_code)
    return {
        "security_code": code,
        "name": names.get(code, code),
        "focus": code in focus,
        "group": row.group_name,
        "note": row.note,
        "added_at": row.added_at.isoformat() if hasattr(row.added_at, "isoformat") else row.added_at,
        "refresh_tier": None,
    }


def _active(conn: Connection, user_id: uuid.UUID, code: str) -> Any | None:
    return conn.execute(
        select(watchlist_items).where(
            watchlist_items.c.user_id == user_id,
            watchlist_items.c.security_code == code,
            watchlist_items.c.removed_at.is_(None),
        )
    ).first()


def _duplicate(existing: Any | None) -> AppError:
    return AppError(
        ErrorCode.CONFLICT,
        details={
            "field": "security_code",
            "existing_id": str(existing.id) if existing is not None else None,
        },
    )


def _qualify(conn: Connection, raw: str) -> str:
    if not isinstance(raw, str) or _CODE_RE.fullmatch(raw) is None:
        raise _bad("security_code", "invalid")
    code = normalize_code(conn, raw)
    successor = conn.execute(
        select(security_code_history.c.code).where(security_code_history.c.old_code == code)
    ).scalar_one_or_none()
    if successor is not None:
        raise _bad("security_code", "superseded", superseded_by=str(successor))
    sec = conn.execute(select(securities).where(securities.c.code == code)).first()
    if sec is None:
        raise _bad("security_code", "unknown_security")
    if sec.type == "index" and not ALLOW_INDEX_IN_WATCHLIST:
        raise _bad("security_code", "security_type_not_supported")
    if sec.listing_status == "delisted" and not ALLOW_DELISTED_IN_WATCHLIST:
        raise _bad("security_code", "delisted")
    return code


@router.get("/watchlist")
def list_watchlist(auth: AuthDep, engine: EngineDep, settings: SettingsDep) -> dict[str, Any]:
    now = dt.datetime.now(dt.UTC)
    with engine.connect() as conn:
        rows = conn.execute(
            select(watchlist_items)
            .where(
                watchlist_items.c.user_id == auth.user_id,
                watchlist_items.c.removed_at.is_(None),
            )
            .order_by(watchlist_items.c.added_at.asc(), watchlist_items.c.id.asc())
        ).all()
        names = security_names(conn, [r.security_code for r in rows])
        focus = _focus_codes(conn, auth.user_id)
        caps = _caps(conn, auth.user_id, settings, now)
    return {"items": [_item(r, names, focus) for r in rows], "caps": caps}


@router.post("/watchlist", status_code=201)
def add_watchlist(
    body: WatchlistCreate,
    response: Response,
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
    rds: RedisDep,
    idempotency_key: idempotency.KeyHeader = None,
) -> object:
    group = _clip(body.group, "group", GROUP_MAX)
    note = _clip(body.note, "note", NOTE_MAX)
    if READD_RESTORES_GROUP_NOTE:
        # 保守默认关闭；打开时由后续单改为恢复旧行。本单始终插入新行。
        pass

    def _do() -> tuple[int, Any]:
        now = dt.datetime.now(dt.UTC)
        new_id = uuid.uuid4()
        try:
            with engine.begin() as conn:
                conn.execute(
                    select(users.c.id).where(users.c.id == auth.user_id).with_for_update()
                ).scalar_one()
                code = _qualify(conn, body.security_code)
                existing = _active(conn, auth.user_id, code)
                if existing is not None:
                    raise _duplicate(existing)
                caps = _caps(conn, auth.user_id, settings, now)
                current = int(
                    conn.execute(
                        select(func.count())
                        .select_from(watchlist_items)
                        .where(
                            watchlist_items.c.user_id == auth.user_id,
                            watchlist_items.c.removed_at.is_(None),
                        )
                    ).scalar_one()
                )
                limit = caps["watchlist"]
                if current >= limit:
                    raise AppError(
                        ErrorCode.ENTITLEMENT_LIMIT_REACHED,
                        details={
                            "key": "watchlist.per_user_cap",
                            "limit": limit,
                            "current": current,
                        },
                    )
                conn.execute(
                    insert(watchlist_items).values(
                        id=new_id,
                        user_id=auth.user_id,
                        security_code=code,
                        group_name=group,
                        note=note,
                        added_at=now,
                    )
                )
                row = conn.execute(select(watchlist_items).where(watchlist_items.c.id == new_id)).one()
                names = security_names(conn, [code])
                focus = _focus_codes(conn, auth.user_id)
                out = _item(row, names, focus)
        except IntegrityError as exc:
            orig = getattr(exc, "orig", exc)
            if INDEX_NAME not in str(orig):
                raise
            with engine.connect() as conn:
                code = _qualify(conn, body.security_code)
                existing = _active(conn, auth.user_id, code)
            raise _duplicate(existing) from None
        return 201, out

    status, out = idempotency.run(
        rds,
        user_id=auth.user_id,
        scope="watchlist:add",
        key=idempotency_key,
        payload=body.model_dump(mode="json"),
        fn=_do,
    )
    response.status_code = status
    return out


@router.delete("/watchlist/{security_code}", status_code=204)
def delete_watchlist(security_code: str, auth: AuthDep, engine: EngineDep) -> Response:
    now = dt.datetime.now(dt.UTC)
    with engine.begin() as conn:
        if not isinstance(security_code, str) or _CODE_RE.fullmatch(security_code) is None:
            raise _bad("security_code", "invalid")
        code = normalize_code(conn, security_code)
        row = _active(conn, auth.user_id, code)
        if row is None:
            raise AppError(ErrorCode.NOT_FOUND)
        conn.execute(
            update(watchlist_items)
            .where(watchlist_items.c.id == row.id)
            .values(removed_at=now)
        )
    return Response(status_code=204)
