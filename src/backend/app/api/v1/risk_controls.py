"""Draft §7.11.2 explicitly assigned by P2N-02; no HTTP/vendor/G7 operations."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable, Coroutine, Iterator
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from fastapi.routing import APIRoute
from pydantic import AfterValidator, Field, StrictBool, StrictInt
from sqlalchemy import Connection, Engine
from sqlalchemy.exc import DBAPIError

from app.api.v1.candidate_signals import scoped_page
from app.api.v1.trades import normalize_code
from app.auth.deps import AuthDep, EngineDep, SettingsDep
from app.common.errors import AppError, ErrorCode
from app.common.pagination import PageParams, page_params
from app.risk import settings as store
from app.risk.models import RiskEvaluation, RiskEvent, RiskSetting
from app.schemas.enums import RiskControl
from app.signals.models import Model

router = APIRouter(tags=["risk-controls"])


@contextmanager
def settings_transaction(engine: Engine) -> Iterator[Connection]:
    """T-A52: roll back before reporting retryable transaction conflicts."""
    try:
        with engine.begin() as conn:
            yield conn
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) in {"40001", "40P01"}:
            raise AppError(ErrorCode.CONFLICT, details={"field": "risk_controls"}) from None
        raise


class ResetRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def checked(request: Request) -> Response:
            # Resource shape is resolved before authentication/CSRF, without decoding JSON.
            if (
                request.path_params.get("control") not in {c.value for c in RiskControl}
                or request.scope.get("query_string")
                or await request.body()
            ):
                raise AppError(ErrorCode.NOT_FOUND)
            return await handler(request)

        return checked


reset_router = APIRouter(route_class=ResetRoute)


@reset_router.delete("/risk-controls/{control}", response_model=list[RiskSetting])
def reset_setting(
    control: str, auth: AuthDep, engine: EngineDep, settings: SettingsDep, response: Response
) -> list[dict[str, Any]]:
    response.headers["Cache-Control"] = "private, no-store"
    with settings_transaction(engine) as conn:
        return store.reset(
            conn,
            auth.user_id,
            auth.user.role,
            settings.business.risk_controls,
            control,
            dt.datetime.now(dt.UTC),
        )


router.include_router(reset_router)


def decimal_text(value: str) -> str:
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        raise ValueError("must be a finite decimal string") from None
    if not parsed.is_finite():
        raise ValueError("must be a finite decimal string")
    return value


DecimalText = Annotated[str, Field(strict=True), AfterValidator(decimal_text)]


class StopParams(Model):
    long_horizon_default_stop_pct: DecimalText
    clamp_to_price_limit: StrictBool


class PositionParams(Model):
    single_position_max_pct: DecimalText


class Ranges(Model):
    uptrend: tuple[DecimalText, DecimalText]
    range: tuple[DecimalText, DecimalText]
    downtrend: tuple[DecimalText, DecimalText]


class TotalParams(Model):
    regime_ranges: Ranges
    regime_confirm_days: StrictInt


class SectorParams(Model):
    sw_l1_max_pct: DecimalText
    concept_max_pct: DecimalText


class LossParams(Model):
    closed_loss_streak: StrictInt
    drawdown_from_peak_pct: DecimalText
    strategy_sim_fail_streak: StrictInt
    pause_on_trigger: StrictBool
    pause_days: StrictInt


class PlanParams(Model):
    checks: list[
        Literal[
            "opposite_side",
            "qty_over_plan",
            "held_after_invalidation",
            "buy_without_stop",
            "buy_during_wait",
        ]
    ]


class Patch(Model):
    enabled: StrictBool


class StopPatch(Patch):
    control: Literal["stop_take"]
    params: StopParams


class PositionPatch(Patch):
    control: Literal["position_cap"]
    params: PositionParams


class TotalPatch(Patch):
    control: Literal["total_exposure"]
    params: TotalParams


class SectorPatch(Patch):
    control: Literal["sector_concentration"]
    params: SectorParams


class LossPatch(Patch):
    control: Literal["loss_streak_drawdown"]
    params: LossParams


class PlanPatch(Patch):
    control: Literal["plan_violation"]
    params: PlanParams


RiskPatch = Annotated[
    StopPatch | PositionPatch | TotalPatch | SectorPatch | LossPatch | PlanPatch,
    Field(discriminator="control"),
]


@router.get("/risk-controls", response_model=list[RiskSetting])
def read_settings(
    auth: AuthDep, engine: EngineDep, settings: SettingsDep, response: Response
) -> list[dict[str, Any]]:
    response.headers["Cache-Control"] = "private, no-store"
    with engine.connect() as conn:
        return store.entries(conn, auth.user_id, settings.business.risk_controls)


@router.put("/risk-controls", response_model=list[RiskSetting])
def write_settings(
    body: list[RiskPatch], auth: AuthDep, engine: EngineDep, settings: SettingsDep
) -> list[dict[str, Any]]:
    with settings_transaction(engine) as conn:
        return store.save(
            conn,
            auth.user_id,
            auth.user.role,
            settings.business.risk_controls,
            [row.model_dump() for row in body],
            dt.datetime.now(dt.UTC),
        )


@router.get("/risk-controls/evaluation", response_model=RiskEvaluation)
def evaluation(
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
    response: Response,
    security_code: str,
    account_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    from app.risk.evaluation import current

    response.headers["Cache-Control"] = "private, no-store"
    with engine.connect() as conn:
        code = normalize_code(conn, security_code)
        return current(conn, auth.user_id, code, account_id, settings, dt.datetime.now(dt.UTC))


@router.get("/risk-controls/events")
def events(
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
    page: Annotated[PageParams, Depends(page_params)],
    status: Literal["active", "cleared"] | None = None,
    control: RiskControl | None = None,
    security_code: str | None = None,
    since: dt.datetime | None = None,
) -> dict[str, Any]:
    from app.risk.events import listing

    if since is not None and since.tzinfo is None:
        raise AppError(ErrorCode.VALIDATION_ERROR)
    with engine.connect() as conn:
        code = normalize_code(conn, security_code) if security_code else None
        query, table, stamp, scope = listing(conn, auth.user_id, status, control, code, since)
        rows, cursor = scoped_page(
            query, table=table, time=stamp, params=page, scope=scope, settings=settings, conn=conn
        )
        return {
            "items": [
                RiskEvent.model_validate(row.payload).model_dump(mode="json") for row in rows
            ],
            "next_cursor": cursor,
        }
