"""研究候选（契约 v0.2.9 §7.7A ``/candidates*`` 🔒 ⚖；T-A11 / T-B10）。

- 只看本人：他人的或不存在的 id 一律 ``404 NOT_FOUND``；引用他人建议与不存在的建议同为
  ``400{field:"suggestion_id", issue:"not_found"}``。
- 头表只有 ``status`` 与 ``current_version_id`` 会变；版本不可变（库中触发器），修改 = 新建版本；
  没有删除，``PUT``/``PATCH``/``DELETE`` 由全局 405 处理（带 ``Allow``）。
- 系统内容（``reasons``、``counter_evidence``、``fit_assessment``、``evidence`` 与数据状态）在
  新建版本时由 :mod:`app.research.content` 生成一次并写入快照（``purpose='candidate'``、本人
  ``user_id``），回看只读快照；事实另存 ``claims``（本人 ``user_id``）+ ``claim_links``。
- 重复：本人同一证券至多一条 ``researching``/``watching``（部分唯一索引，迁移 0016）；并发时
  插入撞索引 → ``409 CONFLICT{field, existing_id}``。
- 无通知、无 SSE 事件；⚖ 只表示前端展示免责提示（§1.3），服务端不拦截。
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection, Row, func, insert, select, tuple_, update
from sqlalchemy.exc import IntegrityError

from app.api.v1.trades import normalize_code
from app.auth.abuse import RateLimiter, Window
from app.auth.deps import AuthContext, AuthDep, EngineDep, RedisDep, SettingsDep
from app.common import idempotency
from app.common.errors import AppError, ErrorCode
from app.common.pagination import Page, PageParams, build_page, decode_cursor, page_params
from app.config import Settings
from app.db.tables.market import securities
from app.db.tables.realtime import suggestions
from app.db.tables.research import candidate_versions, research_candidates
from app.db.tables.reviews import data_snapshots
from app.research import content as rc
from app.schemas.enums import (
    CandidateDecision,
    ConfidenceLevel,
    ResearchCandidateOrigin,
    ResearchCandidateStatus,
    SecurityType,
)

router = APIRouter(tags=["candidates"])

SCOPE_LIST: Final = "candidates:list"
SCOPE_VERSIONS: Final = "candidates:versions"
WRITES_PER_HOUR: Final = 120
THESIS_MAX: Final = 2000
TEXT_MAX: Final = 200
CONDITIONS_MAX: Final = 10
OPEN: Final = (ResearchCandidateStatus.RESEARCHING.value, ResearchCandidateStatus.WATCHING.value)
DEFAULT_STATUSES: Final = (*OPEN, ResearchCandidateStatus.PLANNED.value)
TERMINAL: Final = (ResearchCandidateStatus.DROPPED.value, ResearchCandidateStatus.PLANNED.value)
DECISION_STATUS: Final = {
    CandidateDecision.CONTINUE: ResearchCandidateStatus.RESEARCHING.value,
    CandidateDecision.WATCH: ResearchCandidateStatus.WATCHING.value,
    CandidateDecision.DROP: ResearchCandidateStatus.DROPPED.value,
}
NOT_SUPPORTED_TYPES: Final = (SecurityType.ETF.value, SecurityType.INDEX.value)


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ConditionIn(_Body):
    text: str
    verify_by: dt.date | None = None
    verify_method: str | None = None
    confidence: ConfidenceLevel | None = None


class CandidateCreate(_Body):
    origin: ResearchCandidateOrigin
    security_code: str | None = None
    suggestion_id: uuid.UUID | None = None
    thesis: str | None = None
    conditions_to_hold: list[ConditionIn]


class VersionCreate(_Body):
    base_version_no: int
    thesis: str | None = None
    conditions_to_hold: list[ConditionIn]
    decision: CandidateDecision | None = None
    decision_reason: str | None = None


# ------------------------------------------------------------------ 校验
class _Issues:
    def __init__(self) -> None:
        self.fields: list[dict[str, str]] = []

    def add(self, field: str, issue: str) -> None:
        self.fields.append({"field": field, "issue": issue})

    def raise_if_any(self) -> None:
        if self.fields:
            raise AppError(ErrorCode.VALIDATION_ERROR, details={"fields": self.fields})


def _bad(field: str, issue: str) -> AppError:
    return AppError(
        ErrorCode.VALIDATION_ERROR, details={"fields": [{"field": field, "issue": issue}]}
    )


def _text(
    v: str | None, field: str, limit: int, iss: _Issues, *, required: bool = False
) -> str | None:
    """去首尾空白；空串按 null；超长 → ``too_long``；必填缺 → ``required``。"""
    s = v.strip() if v is not None else None
    if not s:
        if required:
            iss.add(field, "required")
        return None
    if len(s) > limit:
        iss.add(field, "too_long")
    return s


def _thesis(v: str | None, iss: _Issues) -> str | None:
    return _text(v, "thesis", THESIS_MAX, iss)


def _conditions(items: list[ConditionIn], iss: _Issues) -> list[dict[str, Any]]:
    """``CandidateConditionInput`` → 存库 / 输出的 ``CandidateCondition``（``hypothesis``）。"""
    if len(items) > CONDITIONS_MAX:
        iss.add("conditions_to_hold", "too_many")
    out: list[dict[str, Any]] = []
    for i, c in enumerate(items):
        f = f"conditions_to_hold[{i}]"
        text = _text(c.text, f"{f}.text", TEXT_MAX, iss, required=True)
        method = _text(c.verify_method, f"{f}.verify_method", TEXT_MAX, iss)
        if c.verify_by is None and method is None:
            iss.add(f, "verification_required")
        out.append(
            {
                "text": text,
                "verify_by": c.verify_by.isoformat() if c.verify_by else None,
                "verify_method": method,
                "confidence": c.confidence.value if c.confidence else None,
                "epistemic_type": "hypothesis",
            }
        )
    return out


def _security(conn: Connection, code: str) -> Row[Any]:
    sec = conn.execute(select(securities).where(securities.c.code == code)).first()
    if sec is None:
        raise _bad("security_code", "unknown_security")
    if sec.type in NOT_SUPPORTED_TYPES:
        raise _bad("security_code", "security_type_not_supported")
    return sec


# ------------------------------------------------------------------ 读取 / 输出
def _owned(conn: Connection, auth: AuthContext, cid: uuid.UUID, *, lock: bool = False) -> Row[Any]:
    q = select(research_candidates).where(
        research_candidates.c.id == cid, research_candidates.c.user_id == auth.user_id
    )
    if lock:
        q = q.with_for_update()
    row = conn.execute(q).first()
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND)
    return row


def _version_out(v: Row[Any], items: dict[str, Any], code: str) -> dict[str, Any]:
    return {
        "id": str(v.id),
        "candidate_id": str(v.candidate_id),
        "version_no": v.version_no,
        "security_code": code,
        "name": items.get("name") or code,
        "thesis": v.thesis,
        "reasons": items.get("reasons", []),
        "conditions_to_hold": v.conditions_to_hold or [],
        "counter_evidence": items.get("counter_evidence", []),
        "fit_assessment": items.get("fit_assessment")
        or {"profile_filled": False, "holdings_available": False, "hints": [], "warnings": []},
        "decision": v.decision,
        "decision_reason": v.decision_reason,
        "snapshot_id": str(v.snapshot_id) if v.snapshot_id else None,
        "evidence": items.get("evidence", []),
        "data_status": items.get("data_status", "unavailable"),
        "data_as_of": items.get("data_as_of"),
        "gaps": items.get("gaps", []),
        "created_at": v.created_at.isoformat(),
    }


def _versions_out(conn: Connection, rows: Sequence[Row[Any]], code: str) -> list[dict[str, Any]]:
    """版本行 + 各自快照（一次查询）→ ``CandidateVersion[]``。"""
    sids = [r.snapshot_id for r in rows if r.snapshot_id is not None]
    snaps: dict[Any, dict[str, Any]] = {}
    if sids:
        snaps = {
            s.id: dict(s.snap_items or {})
            for s in conn.execute(
                select(data_snapshots.c.id, data_snapshots.c["items"].label("snap_items")).where(
                    data_snapshots.c.id.in_(sids)
                )
            )
        }
    return [_version_out(r, snaps.get(r.snapshot_id, {}), code) for r in rows]


def _candidate_out(conn: Connection, c: Row[Any]) -> dict[str, Any]:
    cur = conn.execute(
        select(candidate_versions).where(candidate_versions.c.id == c.current_version_id)
    ).one()
    version = _versions_out(conn, [cur], c.security_code)[0]
    n = conn.execute(
        select(func.count()).where(candidate_versions.c.candidate_id == c.id)
    ).scalar_one()
    sec = conn.execute(
        select(securities.c.name, securities.c.type).where(securities.c.code == c.security_code)
    ).first()
    return {
        "id": str(c.id),
        "security_code": c.security_code,
        "name": sec.name if sec else version["name"],
        "security_type": sec.type if sec else SecurityType.STOCK.value,
        "origin": c.origin,
        "strategy_run_id": None,  # 本版恒为 null（没有策略筛选入口）
        "suggestion_id": str(c.suggestion_id) if c.suggestion_id else None,
        "status": c.status,
        "plan_ids": [],  # /plans 结构未定（问题 59），本版恒为 []
        "version_count": int(n),
        "current_version": version,
        "created_at": c.created_at.isoformat(),
    }


# ------------------------------------------------------------------ 写入
def _new_version(
    conn: Connection,
    settings: Settings,
    *,
    auth: AuthContext,
    candidate_id: uuid.UUID,
    version_no: int,
    code: str,
    sec: Row[Any] | None,
    suggestion: Row[Any] | None,
    thesis: str | None,
    conditions: list[dict[str, Any]],
    decision: CandidateDecision | None,
    reason: str | None,
) -> uuid.UUID:
    sec_row = sec if sec is not None else _security_row_or_stub(conn, code)
    body = rc.generate(
        conn, settings, user_id=auth.user_id, code=code, sec=sec_row, suggestion=suggestion
    )
    items = body.items()
    snap = rc.write_snapshot(conn, auth.user_id, items)
    vid = uuid.uuid4()
    conn.execute(
        insert(candidate_versions).values(
            id=vid,
            candidate_id=candidate_id,
            version_no=version_no,
            thesis=thesis,
            conditions_to_hold=conditions,
            counter_evidence=items["counter_evidence"],
            fit_assessment=items["fit_assessment"],
            decision=decision.value if decision else None,
            decision_reason=reason,
            snapshot_id=snap,
            created_by=auth.user_id,
        )
    )
    rc.write_claims(
        conn, user_id=auth.user_id, code=code, version_id=vid, content=body, snapshot_id=snap
    )
    return vid


def _security_row_or_stub(conn: Connection, code: str) -> Row[Any] | rc.SecStub:
    """已建候选的证券后来从主数据消失时仍能新建版本（名称退回代码，不列风险因子）。"""
    row = conn.execute(select(securities).where(securities.c.code == code)).first()
    return row if row is not None else rc.SecStub(name=code)


def _open_existing(conn: Connection, user_id: uuid.UUID, code: str) -> uuid.UUID | None:
    return conn.execute(
        select(research_candidates.c.id).where(
            research_candidates.c.user_id == user_id,
            research_candidates.c.security_code == code,
            research_candidates.c.status.in_(OPEN),
        )
    ).scalar()


def _duplicate(existing: uuid.UUID | None) -> AppError:
    return AppError(
        ErrorCode.CONFLICT,
        details={"field": "security_code", "existing_id": str(existing) if existing else None},
    )


def _limit_writes(rds: RedisDep, auth: AuthContext) -> None:
    RateLimiter(rds).enforce(
        f"user:{auth.user_id}", [Window("candidates:write", WRITES_PER_HOUR, 3600)]
    )


# ------------------------------------------------------------------ 端点
def _parse_statuses(raw: str | None) -> list[str] | None:
    if raw is None or not raw.strip():
        return list(DEFAULT_STATUSES)
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if parts == ["all"]:
        return None
    valid = {m.value for m in ResearchCandidateStatus}
    if not parts or any(p not in valid for p in parts):
        raise _bad("status", "invalid")
    return parts


@router.get("/candidates", response_model=Page[dict[str, Any]])
def list_candidates(
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
    page: Annotated[PageParams, Depends(page_params)],
    status: Annotated[str | None, Query(max_length=200)] = None,
    security_code: Annotated[str | None, Query(max_length=16)] = None,
    origin: Annotated[str | None, Query(max_length=32)] = None,
    suggestion_id: uuid.UUID | None = None,
) -> Page[dict[str, Any]]:
    t, v = research_candidates, candidate_versions
    cond: list[Any] = [t.c.user_id == auth.user_id]
    statuses = _parse_statuses(status)
    if statuses is not None:
        cond.append(t.c.status.in_(statuses))
    if origin is not None:
        if origin not in {m.value for m in ResearchCandidateOrigin}:
            raise _bad("origin", "invalid")
        cond.append(t.c.origin == origin)
    if suggestion_id is not None:
        cond.append(t.c.suggestion_id == suggestion_id)
    with engine.connect() as conn:
        if security_code:
            cond.append(t.c.security_code == normalize_code(conn, security_code))
        if page.cursor:
            keys = decode_cursor(page.cursor, scope=SCOPE_LIST, settings=settings)
            try:
                at = dt.datetime.fromisoformat(str(keys[0]))
                cid = uuid.UUID(str(keys[1]))
            except (ValueError, IndexError):
                raise AppError(ErrorCode.INVALID_CURSOR) from None
            cond.append(tuple_(t.c.created_at, t.c.id) < tuple_(at, cid))
        rows = conn.execute(
            select(
                t,
                v.c.version_no.label("cur_no"),
                v.c.decision.label("cur_decision"),
                v.c.created_at.label("cur_at"),
                v.c.snapshot_id.label("cur_snapshot_id"),
            )
            .join(v, v.c.id == t.c.current_version_id)
            .where(*cond)
            .order_by(t.c.created_at.desc(), t.c.id.desc())
            .limit(page.limit + 1)
        ).all()
        built = build_page(
            rows,
            limit=page.limit,
            key=lambda r: [r.created_at.isoformat(), str(r.id)],
            scope=SCOPE_LIST,
            settings=settings,
        )
        codes = {r.security_code for r in built.items}
        names: dict[str, str] = {}
        if codes:
            names = {
                s.code: s.name
                for s in conn.execute(
                    select(securities.c.code, securities.c.name).where(securities.c.code.in_(codes))
                )
            }
    return Page[dict[str, Any]](
        items=[
            {
                "id": str(r.id),
                "security_code": r.security_code,
                "name": names.get(r.security_code, r.security_code),
                "origin": r.origin,
                "status": r.status,
                "suggestion_id": str(r.suggestion_id) if r.suggestion_id else None,
                "current_version_no": r.cur_no,
                "decision": r.cur_decision,
                "last_version_at": r.cur_at.isoformat(),
                "created_at": r.created_at.isoformat(),
            }
            for r in built.items
        ],
        next_cursor=built.next_cursor,
    )


@router.post("/candidates", status_code=201)
def create_candidate(
    body: CandidateCreate,
    response: Response,
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
    rds: RedisDep,
    idempotency_key: idempotency.KeyHeader = None,
) -> object:
    # ① 请求体
    iss = _Issues()
    origin = body.origin
    if origin is ResearchCandidateOrigin.STRATEGY_SCREEN:
        iss.add("origin", "not_supported")
    elif origin is ResearchCandidateOrigin.SUGGESTION:
        if body.suggestion_id is None:
            iss.add("suggestion_id", "required")
    else:
        if body.security_code is None or not body.security_code.strip():
            iss.add("security_code", "required")
        if body.suggestion_id is not None:
            iss.add("suggestion_id", "not_allowed")
    thesis = _thesis(body.thesis, iss)
    conditions = _conditions(body.conditions_to_hold, iss)
    iss.raise_if_any()
    _limit_writes(rds, auth)

    def _do() -> tuple[int, Any]:
        new_id = uuid.uuid4()
        try:
            with engine.begin() as conn:
                # ② 证券（请求带了代码时先校验）
                code: str | None = None
                sec: Row[Any] | None = None
                if body.security_code is not None and body.security_code.strip():
                    code = normalize_code(conn, body.security_code)
                    sec = _security(conn, code)
                # ③ 来源建议（他人的与不存在的同样响应）
                sug: Row[Any] | None = None
                if origin is ResearchCandidateOrigin.SUGGESTION:
                    sug = conn.execute(
                        select(suggestions).where(
                            suggestions.c.id == body.suggestion_id,
                            suggestions.c.user_id == auth.user_id,
                        )
                    ).first()
                    if sug is None:
                        raise _bad("suggestion_id", "not_found")
                    if code is None:
                        code = str(sug.security_code)
                        sec = _security(conn, code)
                    elif code != sug.security_code:
                        raise _bad("security_code", "mismatch")
                if code is None or sec is None:  # 上面各分支已保证；防御
                    raise _bad("security_code", "required")
                # ④ 重复
                existing = _open_existing(conn, auth.user_id, code)
                if existing is not None:
                    raise _duplicate(existing)
                conn.execute(
                    insert(research_candidates).values(
                        id=new_id,
                        user_id=auth.user_id,
                        security_code=code,
                        origin=origin.value,
                        suggestion_id=sug.id if sug is not None else None,
                        status=ResearchCandidateStatus.RESEARCHING.value,
                    )
                )
                vid = _new_version(
                    conn,
                    settings,
                    auth=auth,
                    candidate_id=new_id,
                    version_no=1,
                    code=code,
                    sec=sec,
                    suggestion=sug,
                    thesis=thesis,
                    conditions=conditions,
                    decision=None,
                    reason=None,
                )
                conn.execute(
                    update(research_candidates)
                    .where(research_candidates.c.id == new_id)
                    .values(current_version_id=vid)
                )
                out = _candidate_out(conn, _owned(conn, auth, new_id))
        except IntegrityError as exc:
            # 并发：另一请求先插入了同一证券的进行中候选（部分唯一索引）
            if "uq_research_candidates_user_security_open" not in str(exc.orig):
                raise
            with engine.connect() as conn:
                code2 = (
                    normalize_code(conn, body.security_code)
                    if body.security_code and body.security_code.strip()
                    else conn.execute(
                        select(suggestions.c.security_code).where(
                            suggestions.c.id == body.suggestion_id
                        )
                    ).scalar()
                )
                existing = _open_existing(conn, auth.user_id, str(code2)) if code2 else None
            raise _duplicate(existing) from None
        return 201, out

    status, out = idempotency.run(
        rds,
        user_id=auth.user_id,
        scope="candidates:create",
        key=idempotency_key,
        payload=body.model_dump(mode="json"),
        fn=_do,
    )
    response.status_code = status
    return out


@router.get("/candidates/{candidate_id}")
def get_candidate(candidate_id: uuid.UUID, auth: AuthDep, engine: EngineDep) -> dict[str, Any]:
    with engine.connect() as conn:
        return _candidate_out(conn, _owned(conn, auth, candidate_id))


@router.get("/candidates/{candidate_id}/versions", response_model=Page[dict[str, Any]])
def list_versions(
    candidate_id: uuid.UUID,
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
    page: Annotated[PageParams, Depends(page_params)],
) -> Page[dict[str, Any]]:
    v = candidate_versions
    with engine.connect() as conn:
        c = _owned(conn, auth, candidate_id)
        cond: list[Any] = [v.c.candidate_id == c.id]
        if page.cursor:
            keys = decode_cursor(page.cursor, scope=SCOPE_VERSIONS, settings=settings)
            try:
                before = int(str(keys[0]))
            except (ValueError, IndexError):
                raise AppError(ErrorCode.INVALID_CURSOR) from None
            cond.append(v.c.version_no < before)
        rows = conn.execute(
            select(v).where(*cond).order_by(v.c.version_no.desc()).limit(page.limit + 1)
        ).all()
        built = build_page(
            rows,
            limit=page.limit,
            key=lambda r: [str(r.version_no)],
            scope=SCOPE_VERSIONS,
            settings=settings,
        )
        items = _versions_out(conn, built.items, c.security_code)
    return Page[dict[str, Any]](items=items, next_cursor=built.next_cursor)


@router.get("/candidates/{candidate_id}/versions/{version_no}")
def get_version(
    candidate_id: uuid.UUID, version_no: int, auth: AuthDep, engine: EngineDep
) -> dict[str, Any]:
    with engine.connect() as conn:
        c = _owned(conn, auth, candidate_id)
        row = conn.execute(
            select(candidate_versions).where(
                candidate_versions.c.candidate_id == c.id,
                candidate_versions.c.version_no == version_no,
            )
        ).first()
        if row is None:
            raise AppError(ErrorCode.NOT_FOUND)
        return _versions_out(conn, [row], c.security_code)[0]


@router.post("/candidates/{candidate_id}/versions", status_code=201)
def create_version(
    candidate_id: uuid.UUID,
    body: VersionCreate,
    response: Response,
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
    rds: RedisDep,
    idempotency_key: idempotency.KeyHeader = None,
) -> object:
    # ① 请求体
    iss = _Issues()
    if body.decision is None:
        if body.decision_reason is not None:
            iss.add("decision_reason", "not_allowed")
        reason = None
    else:
        reason = _text(body.decision_reason, "decision_reason", TEXT_MAX, iss, required=True)
    thesis = _thesis(body.thesis, iss)
    conditions = _conditions(body.conditions_to_hold, iss)
    iss.raise_if_any()
    _limit_writes(rds, auth)

    def _do() -> tuple[int, Any]:
        with engine.begin() as conn:
            c = _owned(conn, auth, candidate_id, lock=True)  # ② 本人，且串行化同一候选的写入
            to = DECISION_STATUS[body.decision] if body.decision else c.status
            if c.status in TERMINAL:  # ③
                raise AppError(
                    ErrorCode.INVALID_STATE_TRANSITION,
                    details={"from": c.status, "to": to, "allowed": []},
                )
            cur_no = conn.execute(
                select(candidate_versions.c.version_no).where(
                    candidate_versions.c.id == c.current_version_id
                )
            ).scalar_one()
            if body.base_version_no != cur_no:  # ④
                raise AppError(ErrorCode.VERSION_CONFLICT, details={"current_version_no": cur_no})
            sug = None
            if c.suggestion_id is not None:
                sug = conn.execute(
                    select(suggestions).where(suggestions.c.id == c.suggestion_id)
                ).first()
            vid = _new_version(
                conn,
                settings,
                auth=auth,
                candidate_id=c.id,
                version_no=cur_no + 1,
                code=c.security_code,
                sec=None,
                suggestion=sug,
                thesis=thesis,
                conditions=conditions,
                decision=body.decision,
                reason=reason,
            )
            conn.execute(
                update(research_candidates)
                .where(research_candidates.c.id == c.id)
                .values(current_version_id=vid, status=to)
            )
            out = _candidate_out(conn, _owned(conn, auth, c.id))
        return 201, out

    status, out = idempotency.run(
        rds,
        user_id=auth.user_id,
        scope=f"candidates:version:{candidate_id}",
        key=idempotency_key,
        payload=body.model_dump(mode="json"),
        fn=_do,
    )
    response.status_code = status
    return out
