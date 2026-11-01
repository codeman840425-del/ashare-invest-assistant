"""``/me``、``/me/profile``、``/me/consents``、``/me/risk-assessment``（契约 §7.1；T-B03）。"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Connection, Row
from sqlalchemy.exc import IntegrityError

from app.auth import risk_assessment, service
from app.auth.consents import API_TO_KIND
from app.auth.deps import AuthDep, EngineDep, SettingsDep, client_ip, ip_hash
from app.common.errors import AppError, ErrorCode
from app.schemas.enums import Horizon, ProfileEffort, ProfileExperience

router = APIRouter(tags=["me"])

#: plan §6.1 risk_controls.rc2_position_cap：用户可调范围 5–50（与 ``Rc2PositionCap`` 同口径）
POSITION_PCT_MIN = Decimal(5)
POSITION_PCT_MAX = Decimal(50)


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProfileIn(_Body):
    horizon_pref: Annotated[list[Horizon], Field(min_length=1, max_length=len(Horizon))]
    effort: ProfileEffort
    risk_tolerance: Annotated[int, Field(ge=1, le=5, strict=True)]
    experience: ProfileExperience
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


class ConsentIn(_Body):
    key: Literal["signal_risk_disclosure", "privacy", "terms"]
    version: Annotated[str, Field(min_length=1, max_length=64)]


class Answer(_Body):
    q_id: Annotated[str, Field(min_length=1, max_length=64)]
    choice: Annotated[str, Field(min_length=1, max_length=64)]


class RiskAssessmentIn(_Body):
    answers: Annotated[list[Answer], Field(max_length=200)]


def build_me(conn: Connection, user: Row[Any]) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "status": user.status,
        # 权益（entitlements）归 T-B28；此前恒为空对象
        "entitlements": {},
        "consents": service.consents_view(conn, user.id),
        "risk_assessment": service.risk_assessment_view(conn, user.id),
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
        "effort": body.effort.value,
        "risk_tolerance": body.risk_tolerance,
        "experience": body.experience.value,
        "max_single_position_pct": body.max_single_position_pct,
    }
    try:
        with engine.begin() as conn:
            prev = service.latest_profile(conn, auth.user_id)
            # confirmed_at = 测评时间：改了风险等级就不再算“已测评”，需重新测评
            if prev is None or prev.risk_tolerance != body.risk_tolerance:
                changes["confirmed_at"] = None
            row = service.insert_profile_version(conn, auth.user_id, changes)
            service.audit(
                conn,
                action="profile.updated",
                actor_id=auth.user_id,
                actor_role=auth.user.role,
                target_type="user_profile",
                target_id=str(row.id),
                detail={"version_no": int(row.version_no)},
                ip_hash=ip_hash(settings, client_ip(request)),
            )
    except IntegrityError as exc:
        raise AppError(ErrorCode.VERSION_CONFLICT) from exc
    return service.profile_view(row)


@router.post("/me/consents", status_code=201)
def post_consent(
    body: ConsentIn, auth: AuthDep, request: Request, settings: SettingsDep, engine: EngineDep
) -> dict[str, Any]:
    ih = ip_hash(settings, client_ip(request))
    with engine.begin() as conn:
        at = service.insert_consents(
            conn, auth.user_id, [API_TO_KIND[body.key]], doc_version=body.version, ip_hash=ih
        )
        service.audit(
            conn,
            action="consent.granted",
            actor_id=auth.user_id,
            actor_role=auth.user.role,
            target_type="consent",
            target_id=body.key,
            detail={"version": body.version},
            ip_hash=ih,
        )
    return {"key": body.key, "version": body.version, "accepted_at": service.bj(at)}


@router.post("/me/risk-assessment")
def post_risk_assessment(
    body: RiskAssessmentIn,
    auth: AuthDep,
    request: Request,
    settings: SettingsDep,
    engine: EngineDep,
) -> dict[str, Any]:
    questionnaire = risk_assessment.ACTIVE_QUESTIONNAIRE
    level, issues = risk_assessment.score(questionnaire, [(a.q_id, a.choice) for a in body.answers])
    if level is None or questionnaire is None:
        raise _validation(issues)
    try:
        with engine.begin() as conn:
            row = service.insert_profile_version(
                conn,
                auth.user_id,
                {"risk_tolerance": level, "confirmed_at": service.now_utc()},
            )
            service.audit(
                conn,
                action="risk_assessment.submitted",
                actor_id=auth.user_id,
                actor_role=auth.user.role,
                target_type="user_profile",
                target_id=str(row.id),
                detail={
                    "questionnaire_version": questionnaire.version,
                    "level": level,
                    "version_no": int(row.version_no),
                },
                ip_hash=ip_hash(settings, client_ip(request)),
            )
    except IntegrityError as exc:
        raise AppError(ErrorCode.VERSION_CONFLICT) from exc
    return {"level": level, "assessed_at": service.bj(row.confirmed_at)}
