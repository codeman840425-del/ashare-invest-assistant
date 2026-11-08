"""T-A18 read/request routes and fail-closed G7 boundary.

Existing password sessions carry no server-attested human/credential provenance.
Cookies, CSRF and browser-looking headers are not proof of a human interaction.
Do not add a client opt-in, environment switch, or token-to-human conversion here.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Any, Literal, NoReturn

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.auth.deps import AdminDep, AuthDep, EngineDep, SettingsDep, StoreDep, current_admin
from app.auth.service import audit
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


class LifecycleRequest(BaseModel):
    to: Literal["draft", "simulating", "published", "observing", "retired"]
    reason: str
    review_id: uuid.UUID | None = None


def human_admin(request: Request, engine: EngineDep, store: StoreDep) -> NoReturn:
    if request.headers.get("authorization"):
        raise AppError(ErrorCode.HUMAN_SESSION_REQUIRED)
    auth = current_admin(request, engine, store)
    # Genuine admin session + CSRF still cannot establish human provenance in this
    # repository. Audit denial, then stop before any decision/lifecycle DB mutation.
    with engine.begin() as conn:
        audit(
            conn,
            action="promotion.human_session_required",
            actor_id=auth.user_id,
            actor_role="admin",
            target_type="promotion",
            detail={"issue": "trusted_interaction_provenance_unavailable"},
        )
    raise AppError(ErrorCode.HUMAN_SESSION_REQUIRED)


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


@router.post(
    "/admin/promotions/{review_id}/decision",
    dependencies=[Depends(human_admin)],
    response_model=None,
)
def decision(review_id: uuid.UUID, body: DecisionRequest) -> NoReturn:
    # No trusted interaction mechanism exists yet. Even dependency overrides may
    # not turn this scaffold into a live approval route.
    raise AppError(ErrorCode.HUMAN_SESSION_REQUIRED)


@router.post(
    "/admin/strategies/{strategy_id}/versions/{version_id}/lifecycle",
    dependencies=[Depends(human_admin)],
    response_model=None,
)
def lifecycle(strategy_id: uuid.UUID, version_id: uuid.UUID, body: LifecycleRequest) -> NoReturn:
    raise AppError(ErrorCode.HUMAN_SESSION_REQUIRED)
