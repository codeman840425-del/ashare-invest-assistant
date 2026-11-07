"""T-B71 read surfaces; reviewed nullable health/catalog metadata; never guessed."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import or_, select

from app.auth.deps import AuthDep, EngineDep, SettingsDep
from app.common.errors import AppError, ErrorCode
from app.common.pagination import Page, PageParams, build_page, decode_cursor, page_params
from app.db.tables.strategy import (
    feature_catalog,
    strategies,
)
from app.db.tables.strategy import (
    strategy_card_versions as cv,
)
from app.db.tables.strategy import (
    strategy_cards as cards,
)
from app.db.tables.strategy import (
    strategy_health_daily as health,
)
from app.db.tables.strategy import (
    strategy_versions as versions,
)
from app.schemas.enums import CardCompleteness, CardRiskLevel, Horizon, Lifecycle
from app.strategy.cards.models import FeatureCatalogItem

router = APIRouter(tags=["strategy-cards"])


def visible(owner: Any, user_id: uuid.UUID) -> Any:  # noqa: ANN401
    return or_(owner.is_(None), owner == user_id)


@router.get("/strategy-cards")
def card_list(
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
    page: Annotated[PageParams, Depends(page_params)],
    completeness: CardCompleteness | None = None,
    horizon: Horizon | None = None,
    category: str | None = None,
) -> Page[dict[str, Any]]:
    scope = f"cards:{auth.user_id}:{completeness}:{horizon}:{category}"
    query = (
        select(cards, cv.c.fields)
        .join(cv, cv.c.id == cards.c.current_version_id)
        .where(visible(cards.c.owner_user_id, auth.user_id))
    )
    if completeness:
        query = query.where(cards.c.completeness == completeness.value)
    if horizon:
        query = query.where(cv.c.fields["horizons"].contains([horizon.value]))
    if category:
        query = query.where(cv.c.fields["category"].astext == category)
    if page.cursor:
        keys = decode_cursor(page.cursor, scope=scope, settings=settings)
        try:
            if len(keys) != 1:
                raise ValueError("cursor")
            query = query.where(cards.c.id > uuid.UUID(str(keys[0])))
        except ValueError:
            raise AppError(ErrorCode.INVALID_CURSOR) from None
    with engine.connect() as conn:
        rows = conn.execute(query.order_by(cards.c.id).limit(page.limit + 1)).all()
    items = [
        {
            "id": str(row.id),
            "key": row.key,
            "name": row.title,
            "category": row.fields["category"],
            "horizons": row.fields["horizons"],
            "completeness": row.completeness,
            "current_version_no": row.fields["version_no"],
            "source_kind": row.source_kind,
            "performance": None,
        }
        for row in rows
    ]
    return build_page(
        items, limit=page.limit, key=lambda item: [item["id"]], scope=scope, settings=settings
    )


@router.get("/strategy-cards/{card_id}")
@router.get("/strategy-cards/{card_id}/versions/{number}")
def card_detail(
    card_id: uuid.UUID, auth: AuthDep, engine: EngineDep, number: int | None = None
) -> dict[str, Any]:
    query = (
        select(cv, cards.c.current_version_id)
        .join(cards, cards.c.id == cv.c.card_id)
        .where(cards.c.id == card_id, visible(cards.c.owner_user_id, auth.user_id))
    )
    query = (
        query.where(cv.c.version_no == number)
        if number is not None
        else query.where(cv.c.id == cards.c.current_version_id)
    )
    with engine.connect() as conn:
        row = conn.execute(query).first()
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND)
    return {
        **row.fields,
        "field_epistemic": row.field_epistemic,
        "refs": row.references or [],
        "validation_summary": row.fields.get("validation_summary"),
        "risk_level": row.fields.get("risk_level", "normal"),
        "gates_missing": [f"G{n}:promotion_review_pending" for n in range(1, 8)],
    }


@router.get("/strategy-cards/{card_id}/versions")
def card_history(card_id: uuid.UUID, auth: AuthDep, engine: EngineDep) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        owned = conn.execute(
            select(cards.c.id).where(
                cards.c.id == card_id, visible(cards.c.owner_user_id, auth.user_id)
            )
        ).first()
        if owned is None:
            raise AppError(ErrorCode.NOT_FOUND)
        rows = conn.execute(
            select(cv.c.id, cv.c.version_no, cv.c.created_at)
            .where(cv.c.card_id == card_id)
            .order_by(cv.c.version_no.desc())
        ).all()
    return [dict(row._mapping) for row in rows]


@router.get("/feature-catalog", response_model=list[FeatureCatalogItem])
def catalog(auth: AuthDep, engine: EngineDep) -> list[FeatureCatalogItem]:
    with engine.connect() as conn:
        rows = conn.execute(select(feature_catalog).order_by(feature_catalog.c.feature_key)).all()
    result = []
    for row in rows:
        result.append(
            FeatureCatalogItem(
                feature_key=row.feature_key,
                description=row.description,
                dimension=row.dimension,
                frequency=row.frequency,
                adjust=row.adjust,
                unit=row.unit,
                warmup_bars=row.warmup_bars,
                available_at=row.pit_rule,
                status=row.status,
                epistemic_type=row.epistemic_type,
            )
        )
    return result


@router.get("/strategies/{strategy_id}/versions/{version_id}")
def version_detail(
    strategy_id: uuid.UUID, version_id: uuid.UUID, auth: AuthDep, engine: EngineDep
) -> dict[str, Any]:
    with engine.connect() as conn:
        row = conn.execute(
            select(versions, cv.c.fields)
            .join(strategies, strategies.c.id == versions.c.strategy_id)
            .outerjoin(cv, cv.c.id == versions.c.card_version_id)
            .where(
                versions.c.id == version_id,
                versions.c.strategy_id == strategy_id,
                visible(strategies.c.owner_user_id, auth.user_id),
            )
        ).first()
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND)
    return {
        **row.config,
        "lifecycle": row.lifecycle,
        "card_version_id": row.card_version_id,
        "risk_level": (row.fields or {}).get("risk_level", "normal"),
        "param_hash": row.param_hash,
        "parent_version_id": row.parent_version_id,
        "internal_check": {"done": False, "method_types": [], "checked_on": None},
    }


@router.get("/strategies")
def strategy_list(
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
    page: Annotated[PageParams, Depends(page_params)],
    horizon: Horizon | None = None,
    lifecycle: Lifecycle | None = None,
    security_code: str | None = None,
    risk_level: CardRiskLevel | None = None,
) -> Page[dict[str, Any]]:
    if security_code is not None:
        raise AppError(ErrorCode.MAINTENANCE, details={"issue": "applicability_evaluator_pending"})
    scope = f"strategies:{auth.user_id}:{horizon}:{lifecycle}:{risk_level}"
    query = (
        select(strategies, versions.c.version_no, versions.c.lifecycle, cv.c.fields)
        .join(versions, versions.c.id == strategies.c.current_version_id)
        .outerjoin(cv, cv.c.id == versions.c.card_version_id)
        .where(visible(strategies.c.owner_user_id, auth.user_id))
    )
    if horizon:
        query = query.where(strategies.c.horizons.contains([horizon.value]))
    if lifecycle:
        query = query.where(versions.c.lifecycle == lifecycle.value)
    if risk_level:
        query = query.where(cv.c.fields["risk_level"].astext == risk_level.value)
    if page.cursor:
        keys = decode_cursor(page.cursor, scope=scope, settings=settings)
        try:
            if len(keys) != 1:
                raise ValueError("cursor")
            query = query.where(strategies.c.id > uuid.UUID(str(keys[0])))
        except ValueError:
            raise AppError(ErrorCode.INVALID_CURSOR) from None
    with engine.connect() as conn:
        rows = conn.execute(query.order_by(strategies.c.id).limit(page.limit + 1)).all()
        items = []
        for row in rows:
            latest = conn.execute(
                select(health)
                .where(health.c.strategy_version_id == row.current_version_id)
                .order_by(health.c.as_of_date.desc())
                .limit(1)
            ).first()
            items.append(
                {
                    "id": str(row.id),
                    "key": row.key,
                    "name": row.name,
                    "horizons": row.horizons,
                    "risk_level": (row.fields or {}).get("risk_level", "normal"),
                    "current_version": {
                        "id": str(row.current_version_id),
                        "version_no": row.version_no,
                        "lifecycle": row.lifecycle,
                    },
                    "health": {"state": latest.state, "weight": str(latest.weight), "n": latest.n}
                    if latest
                    else None,
                }
            )
    return build_page(
        items, limit=page.limit, key=lambda item: [item["id"]], scope=scope, settings=settings
    )
