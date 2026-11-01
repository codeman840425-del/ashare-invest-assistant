"""``GET /meta/enums``（契约 §7.10，v0.2.4）：§3 枚举、§6.1 原因码、§4 错误码、§4.1 导入提示码。

不分页、可缓存、不需要登录。内容全部来自 :mod:`app.schemas.enums` 与
:mod:`app.common.errors`，本文件不定义任何取值。结构（契约 §7.10）::

    {"version": "v0.2.4",
     "enums": {name: [value, ...]},
     "reason_codes": [{code, release_kinds, check_on, manually_releasable, note}],
     "error_codes": [{code, http_status, scope: "http"|"internal"}],
     "import_codes": [{code, severity, scope, needs_action}],
     "risk_control_labels": {value: "RC1".."RC6"}}
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from typing import Annotated, Any

from fastapi import APIRouter, Header, Response
from pydantic import BaseModel, ConfigDict

from app.common.errors import ERROR_CODES, ErrorCode, ErrorScope
from app.schemas.enums import (
    CONTRACT_ENUMS,
    CONTRACT_VERSION,
    IMPORT_CODE_TABLE,
    REASON_CODE_TABLE,
    RISK_CONTROL_LABELS,
    CheckOn,
    ImportScope,
    ImportSeverity,
    ReasonCode,
    ReleaseKind,
)

router = APIRouter(tags=["meta"])

CACHE_CONTROL = "public, max-age=300"

#: OpenAPI 响应头声明（契约 §7.10：强 ETag + ``Cache-Control: public, max-age=300``）
_CACHE_HEADERS: dict[str, Any] = {
    "ETag": {"description": "强 ETag（内容哈希）", "schema": {"type": "string"}},
    "Cache-Control": {"description": CACHE_CONTROL, "schema": {"type": "string"}},
}


class ReasonCodeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ReasonCode
    release_kinds: list[ReleaseKind]
    check_on: list[CheckOn]
    manually_releasable: bool
    note: str | None


class ErrorCodeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ErrorCode
    http_status: int
    scope: ErrorScope


class ImportCodeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: ImportSeverity
    scope: ImportScope
    needs_action: bool


class EnumsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    enums: dict[str, list[str]]
    reason_codes: list[ReasonCodeOut]
    error_codes: list[ErrorCodeOut]
    import_codes: list[ImportCodeOut]
    risk_control_labels: dict[str, str]


def build_enums() -> EnumsResponse:
    return EnumsResponse(
        version=CONTRACT_VERSION,
        enums={name: [m.value for m in enum] for name, enum in CONTRACT_ENUMS.items()},
        reason_codes=[
            ReasonCodeOut(
                code=s.code,
                release_kinds=list(s.release_kinds),
                check_on=list(s.check_on),
                manually_releasable=s.manually_releasable,
                note=s.note,
            )
            for s in REASON_CODE_TABLE
        ],
        error_codes=[
            ErrorCodeOut(code=code, http_status=spec.http_status, scope=spec.scope)
            for code, spec in ERROR_CODES.items()
        ],
        import_codes=[
            ImportCodeOut(
                code=s.code, severity=s.severity, scope=s.scope, needs_action=s.needs_action
            )
            for s in IMPORT_CODE_TABLE
        ],
        risk_control_labels={k.value: v for k, v in RISK_CONTROL_LABELS.items()},
    )


@lru_cache(maxsize=1)
def _cached() -> tuple[bytes, str]:
    payload: dict[str, Any] = build_enums().model_dump(mode="json")
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    etag = '"' + hashlib.sha256(body).hexdigest()[:32] + '"'
    return body, etag


def _etag_matches(header: str, etag: str) -> bool:
    """RFC 9110 §13.1.2：If-None-Match 用弱比较（忽略 ``W/``），``*`` 匹配任意表示（评审 m8）。"""
    tags = {t.strip() for t in header.split(",")}
    if "*" in tags:
        return True
    return etag in {t.removeprefix("W/") for t in tags}


@router.get(
    "/meta/enums",
    response_model=EnumsResponse,
    summary="枚举、原因码、错误码与导入提示码（不分页，可缓存）",
    responses={
        200: {"headers": _CACHE_HEADERS},
        304: {
            "description": "Not Modified：If-None-Match 命中当前 ETag，无响应体（契约 §7.10）",
            "headers": _CACHE_HEADERS,
        },
    },
)
async def meta_enums(
    if_none_match: Annotated[str | None, Header()] = None,
) -> Response:
    body, etag = _cached()
    headers = {"ETag": etag, "Cache-Control": CACHE_CONTROL}
    if if_none_match is not None and _etag_matches(if_none_match, etag):
        return Response(status_code=304, headers=headers)
    return Response(
        content=body,
        media_type="application/json; charset=utf-8",
        headers=headers,
    )
