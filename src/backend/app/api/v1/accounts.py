"""券商账户（契约 v0.2.8 §7.2 ``GET/POST /accounts``；T-B46）。

库表 ``app.accounts`` 与契约字段的对应：``name → alias``、``broker_label → broker_name``。
``shareholder_code_masked`` 取本账户最近一条带股东代码的成交或快照明细的掩码值（库里只存
HMAC + 掩码）；``fund_account_masked`` 恒为 ``null``（资金账号导入时丢弃，不落库）。
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import Connection, Row, and_, insert, or_, select, union_all

from app.auth import service as auth_service
from app.auth.abuse import RateLimiter, Window
from app.auth.deps import AuthContext, AuthDep, EngineDep, RedisDep, SettingsDep, client_ip, ip_hash
from app.common import idempotency
from app.common.errors import AppError, ErrorCode
from app.common.pagination import Page, PageParams, build_page, decode_cursor, page_params
from app.db.tables.accounts import (
    accounts,
    broker_position_snapshot_items,
    broker_position_snapshots,
    trades,
)

router = APIRouter(tags=["accounts"])

SCOPE_LIST: Final = "accounts:list"
CREATE_PER_HOUR: Final = 20
NAME_MAX: Final = 32


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


_Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=NAME_MAX)]


class AccountCreate(_Body):
    alias: _Name
    broker_name: _Name


class Account(BaseModel):
    id: uuid.UUID
    broker_name: str | None
    alias: str
    shareholder_code_masked: str | None
    fund_account_masked: str | None
    created_at: dt.datetime


def owned_account(conn: Connection, auth: AuthContext, account_id: uuid.UUID) -> Row[Any]:
    """本人未归档的账户；不存在或不属于本人 → ``404 NOT_FOUND``（不区分）。"""
    row = conn.execute(
        select(accounts).where(
            accounts.c.id == account_id,
            accounts.c.user_id == auth.user_id,
            accounts.c.archived_at.is_(None),
        )
    ).first()
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND)
    return row


def user_account_ids(conn: Connection, auth: AuthContext) -> list[uuid.UUID]:
    return list(
        conn.execute(
            select(accounts.c.id)
            .where(accounts.c.user_id == auth.user_id, accounts.c.archived_at.is_(None))
            .order_by(accounts.c.created_at, accounts.c.id)
        ).scalars()
    )


def _masked_codes(conn: Connection, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    q1 = select(
        trades.c.account_id.label("account_id"),
        trades.c.shareholder_code_masked.label("masked"),
        trades.c.created_at.label("at"),
    ).where(
        trades.c.account_id.in_(ids),
        trades.c.voided_at.is_(None),
        trades.c.shareholder_code_masked.is_not(None),
    )
    q2 = (
        select(
            broker_position_snapshots.c.account_id.label("account_id"),
            broker_position_snapshot_items.c.shareholder_code_masked.label("masked"),
            broker_position_snapshots.c.created_at.label("at"),
        )
        .join(
            broker_position_snapshots,
            broker_position_snapshots.c.id == broker_position_snapshot_items.c.snapshot_id,
        )
        .where(
            broker_position_snapshots.c.account_id.in_(ids),
            broker_position_snapshot_items.c.shareholder_code_masked.is_not(None),
        )
    )
    u = union_all(q1, q2).subquery()
    out: dict[uuid.UUID, str] = {}
    for acc, masked, _ in conn.execute(select(u).order_by(u.c.at.desc())).all():
        out.setdefault(acc, masked)
    return out


def account_out(row: Row[Any], masked: str | None) -> dict[str, Any]:
    return {
        "id": row.id,
        "broker_name": row.broker_label,
        "alias": row.name,
        "shareholder_code_masked": masked,
        "fund_account_masked": None,
        "created_at": row.created_at,
    }


@router.get("/accounts", response_model=Page[Account])
def list_accounts(
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
    page: Annotated[PageParams, Depends(page_params)],
) -> Page[dict[str, Any]]:
    cond = [accounts.c.user_id == auth.user_id, accounts.c.archived_at.is_(None)]
    if page.cursor:
        keys = decode_cursor(page.cursor, scope=SCOPE_LIST, settings=settings)
        if len(keys) != 2 or not all(isinstance(k, str) for k in keys):
            raise AppError(ErrorCode.INVALID_CURSOR)
        try:
            at, aid = dt.datetime.fromisoformat(str(keys[0])), uuid.UUID(str(keys[1]))
        except ValueError:
            raise AppError(ErrorCode.INVALID_CURSOR) from None
        cond.append(
            or_(
                accounts.c.created_at < at,
                and_(accounts.c.created_at == at, accounts.c.id < aid),
            )
        )
    with engine.connect() as conn:
        rows = conn.execute(
            select(accounts)
            .where(*cond)
            .order_by(accounts.c.created_at.desc(), accounts.c.id.desc())
            .limit(page.limit + 1)
        ).all()
        masked = _masked_codes(conn, [r.id for r in rows[: page.limit]])
    built = build_page(
        rows,
        limit=page.limit,
        key=lambda r: [r.created_at.isoformat(), str(r.id)],
        scope=SCOPE_LIST,
        settings=settings,
    )
    return Page[dict[str, Any]](
        items=[account_out(r, masked.get(r.id)) for r in built.items],
        next_cursor=built.next_cursor,
    )


@router.post("/accounts", status_code=201, response_model=Account)
def create_account(
    body: AccountCreate,
    request: Request,
    response: Response,
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
    rds: RedisDep,
    idempotency_key: idempotency.KeyHeader = None,
) -> object:
    RateLimiter(rds).enforce(
        f"user:{auth.user_id}", [Window("accounts:create", CREATE_PER_HOUR, 3600)]
    )

    def _do() -> tuple[int, Any]:
        aid = uuid.uuid4()
        with engine.begin() as conn:
            conn.execute(
                insert(accounts).values(
                    id=aid, user_id=auth.user_id, name=body.alias, broker_label=body.broker_name
                )
            )
            row = conn.execute(select(accounts).where(accounts.c.id == aid)).one()
            auth_service.audit(
                conn,
                action="account.created",
                actor_id=auth.user_id,
                actor_role=auth.user.role,
                target_type="account",
                target_id=str(aid),
                detail={},
                ip_hash=ip_hash(settings, client_ip(request, settings)),
            )
        out = Account.model_validate(account_out(row, None)).model_dump(mode="json")
        return 201, out

    status, out = idempotency.run(
        rds,
        user_id=auth.user_id,
        scope="accounts:create",
        key=idempotency_key,
        payload=body.model_dump(mode="json"),
        fn=_do,
    )
    response.status_code = status
    return out
