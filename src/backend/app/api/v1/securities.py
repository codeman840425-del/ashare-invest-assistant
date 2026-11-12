"""契约 §7.3：公开主数据搜索及旧别名；只读，不触发供应商 IO。"""

from __future__ import annotations

from fastapi import APIRouter, Header, Request, Response

from app.api.v1.imports import etag_response
from app.auth.deps import AuthDep, EngineDep, SettingsDep
from app.marketdata.bars_read import BarsQuery, BarsReaderDep, BarsResponse
from app.master.profile import profile
from app.master.search import invalid, search

router = APIRouter(prefix="/securities", tags=["securities"])


@router.get("/search")
@router.get("")
def search_securities(
    request: Request,
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
    if_none_match: str | None = Header(default=None),
) -> Response:
    # 鉴权先于字段校验；别名固定使用默认类型和数量，仍返回旧数组结构。
    params = request.query_params
    alias = request.url.path.rstrip("/").endswith("/securities")
    raw_include = params.get("include_delisted", "false")
    if raw_include not in {"true", "false"}:
        raise invalid("include_delisted", "must be true or false")
    try:
        limit = None if alias or "limit" not in params else int(params["limit"])
    except ValueError as exc:
        raise invalid("limit", "must be an integer") from exc
    with engine.connect() as conn:
        value = search(
            conn,
            auth.user_id,
            settings.business.securities.search,
            q=params.get("q", ""),
            types="stock,cdr,etf" if alias else params.get("types", "stock,cdr,etf"),
            include_delisted=raw_include == "true",
            limit=limit,
        )
    content = (
        [
            {"security_code": item["security_code"], "name": item["name"]}
            for item in value["items"][:20]
        ]
        if alias
        else value
    )
    return etag_response(content, if_none_match)


@router.get("/{code}/bars", response_model=BarsResponse)
def security_bars(
    code: str,
    request: Request,
    auth: AuthDep,
    reader: BarsReaderDep,
    if_none_match: str | None = Header(default=None),
) -> Response:
    query = BarsQuery.parse(request.query_params)
    content = BarsResponse.model_validate(reader.read(auth.user_id, code, query))
    return etag_response(content.model_dump(mode="json"), if_none_match)


@router.get("/{code}")
def security_profile(
    code: str,
    auth: AuthDep,
    engine: EngineDep,
    if_none_match: str | None = Header(default=None),
) -> Response:
    with engine.connect() as conn:
        content = profile(conn, auth.user_id, code)
    return etag_response(content, if_none_match)
