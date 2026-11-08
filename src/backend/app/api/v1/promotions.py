"""T-A18/T-A20 promotion reviews: trusted origin, CSRF and request-local password proof."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import select

from app.auth.deps import (
    AdminDep,
    AuthContext,
    AuthDep,
    EngineDep,
    PasswordsDep,
    RedisDep,
    SettingsDep,
    StoreDep,
    client_ip,
    current_admin,
)
from app.auth.reauth import transaction
from app.auth.service import audit
from app.auth.sessions import SESSION_COOKIE
from app.common.errors import AppError, ErrorCode
from app.common.pagination import Page, PageParams, build_page, decode_cursor, page_params
from app.db.tables.strategy import strategy_promotion_reviews as reviews
from app.strategy import reviews as service

router = APIRouter(tags=["promotions"])
Gate = Literal["G1", "G2", "G3", "G4", "G5", "G6"]


class PromotionRequest(BaseModel):
    version_id: uuid.UUID


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")  # reviewer_id is never accepted from input
    decision: Literal["approved", "rejected", "changes_requested"]
    comment: str = Field(min_length=1, max_length=500)
    ack_warn_gates: list[Gate]
    password: SecretStr = Field(repr=False, exclude=True)


class LifecycleRequest(BaseModel):
    to: Literal["draft", "simulating", "published", "observing", "retired"]
    reason: str
    review_id: uuid.UUID | None = None
    password: SecretStr = Field(repr=False, exclude=True)


def human_admin(request: Request, engine: EngineDep, store: StoreDep) -> AuthContext:
    # Preserve cookie/account/admin/CSRF precedence; never reveal admin routes to others.
    auth = current_admin(request, engine, store)
    if "authorization" in request.headers:
        raise AppError(ErrorCode.HUMAN_SESSION_REQUIRED)
    if auth.session.origin != "password_login":
        with engine.begin() as conn:
            audit(
                conn,
                action="promotion.human_session_required",
                actor_id=auth.user_id,
                actor_role="admin",
                target_type="promotion",
                detail={"issue": "untrusted_session_origin"},
            )
        raise AppError(ErrorCode.HUMAN_SESSION_REQUIRED)
    return auth


HumanDep = Annotated[AuthContext, Depends(human_admin)]


def coarse_ip(request: Request, settings: SettingsDep) -> str | None:
    import ipaddress

    try:
        address = ipaddress.ip_address(client_ip(request, settings))
        return str(
            ipaddress.ip_network(f"{address}/{24 if address.version == 4 else 64}", strict=False)
        )
    except ValueError:
        return None


@router.post("/strategy-cards/{card_id}/promotion-requests", status_code=202)
def submit(
    card_id: uuid.UUID,
    body: PromotionRequest,
    background: BackgroundTasks,
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
) -> dict[str, str]:
    with engine.begin() as conn:
        identifier, created = service.request_review(
            conn, auth.user_id, card_id, body.version_id, settings
        )
    if created:
        background.add_task(service.execute_review, engine, auth.user_id, identifier, settings)
    return {"review_id": str(identifier)}


@router.get("/promotion-requests/{review_id}")
def get_review(review_id: uuid.UUID, auth: AuthDep, engine: EngineDep) -> dict[str, Any]:
    with engine.connect() as conn:
        return service.detail(conn, auth.user_id, review_id)


@router.get("/admin/promotions")
def promotion_list(
    auth: AdminDep,
    engine: EngineDep,
    settings: SettingsDep,
    page: Annotated[PageParams, Depends(page_params)],
    decision: str | None = None,
    card_id: str | None = None,
    version_id: str | None = None,
    stale: str = "false",
) -> Page[dict[str, Any]]:
    decisions = decision.split(",") if decision is not None else []
    try:
        if any(d not in service.DECISIONS for d in decisions) or stale not in {"true", "false"}:
            raise ValueError("filter")
        cid = uuid.UUID(card_id) if card_id is not None else None
        vid = uuid.UUID(version_id) if version_id is not None else None
    except ValueError:
        raise AppError(ErrorCode.VALIDATION_ERROR) from None
    scope = f"promotions:{auth.user_id}:{sorted(decisions)}:{cid}:{vid}:{stale}"
    cursor = None
    if page.cursor:
        try:
            keys = decode_cursor(page.cursor, scope=scope, settings=settings)
            if len(keys) != 2:
                raise ValueError("cursor")
            cursor = (dt.datetime.fromisoformat(str(keys[0])), uuid.UUID(str(keys[1])))
            if cursor[0].tzinfo is None:
                raise ValueError("cursor")
        except ValueError:
            raise AppError(ErrorCode.INVALID_CURSOR) from None
    query = select(reviews).order_by(reviews.c.created_at.desc(), reviews.c.id.desc())
    if decisions:
        query = query.where(reviews.c.decision.in_(decisions))
    if vid:
        query = query.where(reviews.c.target_strategy_version_id == vid)
    if cursor:
        query = query.where(
            (reviews.c.created_at < cursor[0])
            | ((reviews.c.created_at == cursor[0]) & (reviews.c.id < cursor[1]))
        )
    items = []
    with engine.connect() as conn:
        for row in conn.execute(query):
            try:
                ctx = service.review_context(conn, auth.user_id, row.id)
            except AppError as error:
                if error.code == ErrorCode.NOT_FOUND:
                    continue
                raise
            item = service.summary(conn, *ctx)
            if (cid is None or item["card_id"] == str(cid)) and item["stale"] == (stale == "true"):
                items.append(item)
                if len(items) > page.limit:
                    break
    return build_page(
        items,
        limit=page.limit,
        key=lambda item: [item["submitted_at"].isoformat(), item["review_id"]],
        scope=scope,
        settings=settings,
    )


@router.post("/admin/promotions/{review_id}/decision")
def decision(
    review_id: uuid.UUID,
    body: DecisionRequest,
    request: Request,
    auth: HumanDep,
    engine: EngineDep,
    store: StoreDep,
    settings: SettingsDep,
    passwords: PasswordsDep,
    rds: RedisDep,
) -> dict[str, Any]:
    with transaction(
        engine,
        auth,
        store,
        body.password,
        passwords,
        rds,
        settings,
        request.cookies.get(SESSION_COOKIE),
    ) as conn:
        return service.decide(
            conn,
            auth.user_id,
            review_id,
            body.decision,
            body.comment,
            list(body.ack_warn_gates),
            coarse_ip(request, settings),
        )


@router.post("/admin/strategies/{strategy_id}/versions/{version_id}/lifecycle")
def lifecycle(
    strategy_id: uuid.UUID,
    version_id: uuid.UUID,
    body: LifecycleRequest,
    request: Request,
    auth: HumanDep,
    engine: EngineDep,
    store: StoreDep,
    settings: SettingsDep,
    passwords: PasswordsDep,
    rds: RedisDep,
) -> dict[str, str]:
    with transaction(
        engine,
        auth,
        store,
        body.password,
        passwords,
        rds,
        settings,
        request.cookies.get(SESSION_COOKIE),
    ) as conn:
        return service.change_lifecycle(
            conn,
            auth.user_id,
            strategy_id,
            version_id,
            body.to,
            body.reason,
            body.review_id,
            coarse_ip(request, settings),
        )
