"""成交记录（契约 v0.2.8 §7.2 ``/trades*``；T-B46）。

手工录入 ``source=manual``；更正 = 同一事务内作废原记录 + 写新记录（``replaces_trade_id``）。
任何写入后按账户重放流水重建 ``holdings``。规则复用 :mod:`app.domain.trades`。
"""

from __future__ import annotations

import datetime as dt
import re
import uuid
from collections.abc import Iterable
from decimal import Decimal
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints
from sqlalchemy import Connection, Row, insert, select, tuple_, update

from app.api.v1.accounts import owned_account
from app.auth import service as auth_service
from app.auth.abuse import RateLimiter, Window
from app.auth.deps import AuthContext, AuthDep, EngineDep, RedisDep, SettingsDep, client_ip, ip_hash
from app.common import idempotency
from app.common.errors import AppError, ErrorCode
from app.common.pagination import Page, PageParams, build_page, decode_cursor, page_params
from app.config import Settings
from app.db.tables.accounts import import_rows, trades
from app.db.tables.market import securities
from app.domain import trades as dtr
from app.importing.pipeline import rebuild_holdings
from app.importing.preview import infer_market
from app.schemas.enums import TradeSide

router = APIRouter(tags=["trades"])

SCOPE_LIST: Final = "trades:list"
WRITES_PER_HOUR: Final = 120
BEIJING: Final = dtr.BEIJING
_CODE_RE: Final = re.compile(r"^(?:(SH|SZ|BJ)(\d{6})|(\d{6})(?:\.(SH|SZ|BJ))?)$")
_Dec = Annotated[Decimal, Field(max_digits=24, decimal_places=8)]
#: 契约 #27 ② / §7.6：security_code 格式（查询参数与请求体；大小写都接受，服务端转大写规范化）。
#: schema 与服务端一致：不做去空白（带空白 → 400 VALIDATION_ERROR），避免 schemathesis 负例误判。
SECURITY_CODE_PATTERN: Final = (
    r"^(?:(?:SH|SZ|BJ|sh|sz|bj)[0-9]{6}|[0-9]{6}(?:\.(?:SH|SZ|BJ|sh|sz|bj))?)$"
)
#: 契约 #27 ④ / §7.6：请求体 decimal 一律是带 pattern 的字符串（JSON 数字、空串 → 400）
QTY_PATTERN: Final = r"^(?!0+(?:\.0+)?$)\d{1,16}(?:\.\d{1,4})?$"
PRICE_PATTERN: Final = r"^(?!0+(?:\.0+)?$)\d{1,16}(?:\.\d{1,8})?$"
FEE_PATTERN: Final = r"^\d{1,16}(?:\.\d{1,4})?$"

_QtyStr = Annotated[str, StringConstraints(strict=True, pattern=QTY_PATTERN)]
_PriceStr = Annotated[str, StringConstraints(strict=True, pattern=PRICE_PATTERN)]
_FeeStr = Annotated[str, StringConstraints(strict=True, pattern=FEE_PATTERN)]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Trade(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    trade_date: dt.date
    trade_time: str | None
    security_code: str
    name: str
    side: TradeSide
    qty: str
    price: str
    amount: str
    fee_total: str | None
    net_amount: str | None
    source: Literal["manual", "import"]
    batch_id: uuid.UUID | None
    voided: bool
    void_reason: str | None
    voided_at: dt.datetime | None
    corrects_trade_id: uuid.UUID | None
    created_at: dt.datetime


# 契约：reason 去首尾空白后 1–200 字；schema 声明 1–200 且至少一个非空白字符，
# 服务端仍按去空白后的长度再校验一次（dtr._reason）。
_ReasonStr = Annotated[
    str, StringConstraints(min_length=1, max_length=dtr.REASON_MAX, pattern=r"\S")
]


class TradeCreate(_Body):
    # 带前瞻的 decimal pattern 需要 python-re 引擎（rust regex 不支持 lookaround）
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, regex_engine="python-re")

    account_id: uuid.UUID
    trade_date: dt.date
    trade_time: Annotated[str, StringConstraints(pattern=r"^\d{2}:\d{2}(:\d{2})?$")] | None = None
    security_code: Annotated[str, StringConstraints(pattern=SECURITY_CODE_PATTERN)]
    side: TradeSide
    qty: _QtyStr
    price: _PriceStr
    fee_total: _FeeStr | None = None

    @property
    def qty_dec(self) -> Decimal:
        return Decimal(self.qty)

    @property
    def price_dec(self) -> Decimal:
        return Decimal(self.price)

    @property
    def fee_dec(self) -> Decimal | None:
        return None if self.fee_total is None else Decimal(self.fee_total)

    corrects_trade_id: uuid.UUID | None = None
    reason: _ReasonStr | None = None


class VoidIn(_Body):
    reason: _ReasonStr


def _bad(field: str, issue: str) -> AppError:
    return AppError(
        ErrorCode.VALIDATION_ERROR, details={"fields": [{"field": field, "issue": issue}]}
    )


def normalize_code(conn: Connection, raw: str, *, field: str = "security_code") -> str:
    """``600000`` / ``600000.SH`` / ``SH600000`` → ``600000.SH``（系统统一格式）。

    只给 6 位时先查证券主数据（不含指数），查不到按代码段推断（可转债也能推断）。
    """
    m = _CODE_RE.match(raw.strip().upper())
    if m is None:
        raise _bad(field, "invalid")
    if m.group(1):
        return f"{m.group(2)}.{m.group(1)}"
    bare, market = m.group(3), m.group(4)
    if market:
        return f"{bare}.{market}"
    hit = conn.execute(
        select(securities.c.code)
        .where(
            securities.c.code.in_([f"{bare}.SH", f"{bare}.SZ", f"{bare}.BJ"]),
            securities.c.type != "index",
        )
        .order_by(securities.c.code)
        .limit(1)
    ).scalar()
    if hit is not None:
        return str(hit)
    inferred = infer_market(bare)
    if inferred is None:
        raise _bad(field, "invalid")
    return f"{bare}.{inferred}"


def security_names(
    conn: Connection, codes: Iterable[str], trade_ids: Iterable[uuid.UUID] = ()
) -> dict[str, str]:
    """代码 → 名称：证券主数据优先；没有时取导入行（已提交）里交割单给的名称。"""
    codes = set(codes)
    out: dict[str, str] = {}
    if codes:
        for code, name in conn.execute(
            select(securities.c.code, securities.c.name).where(securities.c.code.in_(codes))
        ).all():
            if name:
                out[code] = name
    ids = list(trade_ids)
    missing = codes - out.keys()
    if missing and ids:
        q = (
            select(trades.c.security_code, import_rows.c.normalized)
            .join(import_rows, import_rows.c.committed_trade_id == trades.c.id)
            .where(trades.c.id.in_(ids), trades.c.security_code.in_(missing))
        )
        for code, norm in conn.execute(q).all():
            name = (norm or {}).get("name")
            if name and code not in out:
                out[code] = str(name)
    return out


def names_from_imports(
    conn: Connection, account_ids: list[uuid.UUID], codes: set[str]
) -> dict[str, str]:
    """持仓页用：本人账户已提交成交对应导入行里的名称。"""
    if not codes or not account_ids:
        return {}
    q = (
        select(trades.c.security_code, import_rows.c.normalized)
        .join(import_rows, import_rows.c.committed_trade_id == trades.c.id)
        .where(trades.c.account_id.in_(account_ids), trades.c.security_code.in_(codes))
        .order_by(trades.c.created_at.desc())
    )
    out: dict[str, str] = {}
    for code, norm in conn.execute(q).all():
        name = (norm or {}).get("name")
        if name and code not in out:
            out[code] = str(name)
    return out


def _out(conn: Connection, row: Row[Any]) -> dict[str, Any]:
    names = security_names(conn, [row.security_code], [row.id])
    return dtr.trade_out(dict(row._mapping), name=names.get(row.security_code, row.security_code))


def _owned_trade(
    conn: Connection, auth: AuthContext, trade_id: uuid.UUID, *, lock: bool = False
) -> Row[Any]:
    q = select(trades).where(trades.c.id == trade_id, trades.c.user_id == auth.user_id)
    if lock:
        q = q.with_for_update()
    row = conn.execute(q).first()
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND)
    return row


def _audit(
    conn: Connection,
    request: Request,
    settings: Settings,
    auth: AuthContext,
    action: str,
    trade_id: uuid.UUID,
    detail: dict[str, Any],
) -> None:
    auth_service.audit(
        conn,
        action=action,
        actor_id=auth.user_id,
        actor_role=auth.user.role,
        target_type="trade",
        target_id=str(trade_id),
        detail=detail,
        ip_hash=ip_hash(settings, client_ip(request, settings)),
    )


_ISO_DATE_RE: Final = re.compile(r"\d{4}-\d{2}-\d{2}")


def _iso_date_only(v: object) -> object:
    """Query dates must be YYYY-MM-DD; pydantic's lax mode would accept "0.0" as epoch."""
    if isinstance(v, str) and not _ISO_DATE_RE.fullmatch(v):
        raise ValueError("expected YYYY-MM-DD")
    return v


IsoDateQuery = Annotated[dt.date, BeforeValidator(_iso_date_only)]


@router.get("/trades", response_model=Page[Trade])
def list_trades(
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
    page: Annotated[PageParams, Depends(page_params)],
    account_id: uuid.UUID | None = None,
    security_code: Annotated[str | None, Query(pattern=SECURITY_CODE_PATTERN)] = None,
    date_from: Annotated[IsoDateQuery | None, Query(alias="from")] = None,
    date_to: Annotated[IsoDateQuery | None, Query(alias="to")] = None,
    include_voided: bool = False,
) -> Page[dict[str, Any]]:
    t = trades
    cond: list[Any] = [t.c.user_id == auth.user_id]
    with engine.connect() as conn:
        if account_id is not None:
            # G-7 / 契约 §7.6（v0.2.9 #27 ⑦）：不是本人账户（含不存在、已归档）→ 404
            owned_account(conn, auth, account_id)
            cond.append(t.c.account_id == account_id)
        if security_code:
            cond.append(t.c.security_code == normalize_code(conn, security_code))
        if date_from is not None:
            cond.append(t.c.trade_date >= date_from)
        if date_to is not None:
            cond.append(t.c.trade_date <= date_to)
        if not include_voided:
            cond.append(t.c.voided_at.is_(None))
        if page.cursor:
            keys = decode_cursor(page.cursor, scope=SCOPE_LIST, settings=settings)
            try:
                d = dt.date.fromisoformat(str(keys[0]))
                at = dt.datetime.fromisoformat(str(keys[1]))
                tid = uuid.UUID(str(keys[2]))
            except (ValueError, IndexError):
                raise AppError(ErrorCode.INVALID_CURSOR) from None
            cond.append(tuple_(t.c.trade_date, t.c.created_at, t.c.id) < tuple_(d, at, tid))
        rows = conn.execute(
            select(t)
            .where(*cond)
            .order_by(t.c.trade_date.desc(), t.c.created_at.desc(), t.c.id.desc())
            .limit(page.limit + 1)
        ).all()
        built = build_page(
            rows,
            limit=page.limit,
            key=lambda r: [r.trade_date.isoformat(), r.created_at.isoformat(), str(r.id)],
            scope=SCOPE_LIST,
            settings=settings,
        )
        names = security_names(
            conn, {r.security_code for r in built.items}, [r.id for r in built.items]
        )
    return Page[dict[str, Any]](
        items=[
            dtr.trade_out(dict(r._mapping), name=names.get(r.security_code, r.security_code))
            for r in built.items
        ],
        next_cursor=built.next_cursor,
    )


@router.get("/trades/{trade_id}", response_model=Trade)
def get_trade(trade_id: uuid.UUID, auth: AuthDep, engine: EngineDep) -> dict[str, Any]:
    with engine.connect() as conn:
        return _out(conn, _owned_trade(conn, auth, trade_id))


def _traded_at(day: dt.date, hhmm: str | None) -> dt.datetime | None:
    if hhmm is None:
        return None
    try:
        t = dt.time.fromisoformat(hhmm)
    except ValueError:
        raise _bad("trade_time", "invalid") from None
    return dt.datetime.combine(day, t, tzinfo=BEIJING)


@router.post("/trades", status_code=201, response_model=Trade)
def create_trade(
    body: TradeCreate,
    request: Request,
    response: Response,
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
    rds: RedisDep,
    idempotency_key: idempotency.KeyHeader = None,
) -> object:
    RateLimiter(rds).enforce(
        f"user:{auth.user_id}", [Window("trades:write", WRITES_PER_HOUR, 3600)]
    )
    reason = dtr.validate_correction_reason(body.corrects_trade_id, body.reason)
    if body.trade_date > dt.datetime.now(BEIJING).date():
        raise _bad("trade_date", "in_future")
    traded_at = _traded_at(body.trade_date, body.trade_time)

    def _do() -> tuple[int, Any]:
        new_id = uuid.uuid4()
        now = dt.datetime.now(dt.UTC)
        with engine.begin() as conn:
            owned_account(conn, auth, body.account_id)
            code = normalize_code(conn, body.security_code)
            if body.corrects_trade_id is not None:
                orig = _owned_trade(conn, auth, body.corrects_trade_id, lock=True)
                if orig.account_id != body.account_id:
                    raise _bad("corrects_trade_id", "account_mismatch")
                dtr.ensure_voidable(orig.voided_at)
                conn.execute(
                    update(trades)
                    .where(trades.c.id == orig.id)
                    .values(voided_at=now, void_reason=reason)
                )
            conn.execute(
                insert(trades).values(
                    id=new_id,
                    account_id=body.account_id,
                    user_id=auth.user_id,
                    security_code=code,
                    side=body.side.value,
                    quantity=body.qty_dec,
                    price=body.price_dec,
                    amount=(body.qty_dec * body.price_dec).quantize(Decimal("0.0001")),
                    other_fee=body.fee_dec,
                    traded_at=traded_at,
                    trade_date=body.trade_date,
                    source="manual",
                    replaces_trade_id=body.corrects_trade_id,
                )
            )
            rebuild_holdings(conn, body.account_id)
            _audit(
                conn,
                request,
                settings,
                auth,
                "trade.corrected" if body.corrects_trade_id else "trade.created",
                new_id,
                {"corrects_trade_id": str(body.corrects_trade_id)}
                if body.corrects_trade_id
                else {},
            )
            row = conn.execute(select(trades).where(trades.c.id == new_id)).one()
            out = Trade.model_validate(_out(conn, row)).model_dump(mode="json")
        return 201, out

    status, out = idempotency.run(
        rds,
        user_id=auth.user_id,
        scope="trades:create",
        key=idempotency_key,
        payload=body.model_dump(mode="json"),
        fn=_do,
    )
    response.status_code = status
    return out


@router.post(
    "/trades/{trade_id}/void",
    response_model=Trade,
    responses={409: {"description": "INVALID_STATE_TRANSITION：已作废"}},
)
def void_trade(
    trade_id: uuid.UUID,
    body: VoidIn,
    request: Request,
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
    rds: RedisDep,
) -> dict[str, Any]:
    RateLimiter(rds).enforce(
        f"user:{auth.user_id}", [Window("trades:write", WRITES_PER_HOUR, 3600)]
    )
    reason = dtr.validate_void_reason(body.reason)
    with engine.begin() as conn:
        row = _owned_trade(conn, auth, trade_id, lock=True)
        dtr.ensure_voidable(row.voided_at)
        conn.execute(
            update(trades)
            .where(trades.c.id == trade_id)
            .values(voided_at=dt.datetime.now(dt.UTC), void_reason=reason)
        )
        rebuild_holdings(conn, row.account_id)
        _audit(conn, request, settings, auth, "trade.voided", trade_id, {"reason": reason})
        return _out(conn, conn.execute(select(trades).where(trades.c.id == trade_id)).one())
