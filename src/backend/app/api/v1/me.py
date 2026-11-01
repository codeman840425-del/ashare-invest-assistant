"""``/me``、``/me/profile``（契约 §7.1；T-B03）。

契约 v0.2.5（T-A06）：删除 ``/me/consents``、``/me/risk-assessment``，``Me`` 不再有 ``consents``、
``risk_assessment``；v0.2.6（T-A07）``Me`` 加 ``data_licence_status``；
画像的 ``effort``、``risk_tolerance``、``experience`` 为用户自报、可为 null。
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Connection, Row
from sqlalchemy.exc import IntegrityError

from app.auth import service
from app.auth.deps import AuthDep, EngineDep, SettingsDep, client_ip, ip_hash
from app.common.errors import AppError, ErrorCode
from app.licences.service import live_status
from app.schemas.enums import Horizon, ProfileEffort, ProfileExperience

router = APIRouter(tags=["me"])

#: plan §6.1 risk_controls.rc2_position_cap：用户可调范围 5–50（与 ``Rc2PositionCap`` 同口径）
POSITION_PCT_MIN = Decimal(5)
POSITION_PCT_MAX = Decimal(50)


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProfileIn(_Body):
    horizon_pref: Annotated[list[Horizon], Field(min_length=1, max_length=len(Horizon))]
    #: 用户自报、选填：null（或不传）= 未填写（分类器不封顶、不提示）
    effort: ProfileEffort | None = None
    risk_tolerance: Annotated[int, Field(ge=1, le=5, strict=True)] | None = None
    experience: ProfileExperience | None = None
    max_single_position_pct: Annotated[
        Decimal, Field(ge=POSITION_PCT_MIN, le=POSITION_PCT_MAX, max_digits=5, decimal_places=2)
    ]

    @field_validator("horizon_pref")
    @classmethod
    def _unique(cls, v: list[Horizon]) -> list[Horizon]:
        if len(set(v)) != len(v):
            raise ValueError("duplicate horizon")
        return v

    @field_validator("max_single_position_pct", mode="before")
    @classmethod
    def _decimal_string(cls, v: object) -> str:
        # 契约：string(decimal)。拒绝 JSON 数字（避免二进制浮点误差悄悄入库）
        if not isinstance(v, str):
            raise ValueError("must be a decimal string")
        return v


def build_me(conn: Connection, user: Row[Any]) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "status": user.status,
        # 权益（entitlements）归 T-B28；此前恒为空对象
        "entitlements": {},
        # 契约 v0.2.6（T-A07）：本人数据证书状态（只有状态，不含证书值）
        "data_licence_status": live_status(conn, uuid.UUID(str(user.id))),
    }


def _validation(fields: list[dict[str, str]]) -> AppError:
    return AppError(ErrorCode.VALIDATION_ERROR, details={"fields": fields})


@router.get("/me")
def me(auth: AuthDep, engine: EngineDep) -> dict[str, Any]:
    with engine.connect() as conn:
        return build_me(conn, auth.user)


@router.get("/me/profile")
def get_profile(auth: AuthDep, engine: EngineDep) -> dict[str, Any]:
    with engine.connect() as conn:
        row = service.latest_profile(conn, auth.user_id)
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND)
    return service.profile_view(row)


@router.put("/me/profile")
def put_profile(
    body: ProfileIn, auth: AuthDep, request: Request, settings: SettingsDep, engine: EngineDep
) -> dict[str, Any]:
    changes: dict[str, Any] = {
        "horizon_pref": [h.value for h in body.horizon_pref],
        "effort": None if body.effort is None else body.effort.value,
        "risk_tolerance": body.risk_tolerance,
        "experience": None if body.experience is None else body.experience.value,
        "max_single_position_pct": body.max_single_position_pct,
    }
    try:
        with engine.begin() as conn:
            # v0.2.5：不再有测评，confirmed_at 不由本接口维护（沿用上一版）
            row = service.insert_profile_version(conn, auth.user_id, changes)
            service.audit(
                conn,
                action="profile.updated",
                actor_id=auth.user_id,
                actor_role=auth.user.role,
                target_type="user_profile",
                target_id=str(row.id),
                detail={"version_no": int(row.version_no)},
                ip_hash=ip_hash(settings, client_ip(request, settings)),
            )
    except IntegrityError as exc:
        raise AppError(ErrorCode.VERSION_CONFLICT) from exc
    return service.profile_view(row)
