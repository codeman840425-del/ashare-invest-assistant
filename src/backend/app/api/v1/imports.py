"""交割单 / 持仓文件导入（契约 v0.2.8 §7.2 ``/imports*``；plan §3.5A；T-B46）。

流程：``POST /imports``（上传阶段校验 → 加密落盘 → ``201 uploaded``）→ 后台解析
（``parsing`` → ``previewed`` / ``failed``）→ 预览 / 处理提示 / 改选项重新解析 →
``confirm``（两步提交）→ 可 ``revert``。

隐私：原始文件只存仓库外的加密存储；``import_rows.raw_line`` 先掩码再加密，对外只给掩码行；
响应、``errors.csv``、日志都不含股东代码 / 资金账号原文。日志只记批次 id 与计数。
"""

from __future__ import annotations

import codecs
import csv
import datetime as dt
import hashlib
import io
import json
import logging
import uuid
from collections.abc import Sequence
from pathlib import PurePath
from typing import Annotated, Any, Final, Literal

import redis
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Header,
    Query,
    Request,
    Response,
    UploadFile,
)
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import Connection, Engine, Row, and_, insert, or_, select, update

from app.api.v1.accounts import owned_account
from app.auth import service as auth_service
from app.auth.abuse import RateLimiter, Window
from app.auth.deps import AuthContext, AuthDep, EngineDep, RedisDep, SettingsDep, client_ip, ip_hash
from app.common import idempotency
from app.common.errors import AppError, ErrorCode
from app.common.pagination import Page, PageParams, build_page, decode_cursor, page_params
from app.config import Settings
from app.db.tables.accounts import import_batches, import_files, import_rows
from app.importing import findings as fnd
from app.importing import pipeline, storage
from app.importing.decoding import ENCODING_ALIASES
from app.importing.parsers import resolve_parser_id
from app.importing.resolutions import validate_resolution
from app.schemas.enums import (
    DedupStatus,
    ImportRowStatus,
    ImportScope,
    ImportSeverity,
    ImportStatus,
    ReconciliationStatus,
)

log = logging.getLogger(__name__)
router = APIRouter(tags=["imports"])

SCOPE_LIST: Final = "imports:list"
SCOPE_ROWS: Final = "imports:rows"
UPLOADS_PER_HOUR: Final = 30
WRITES_PER_HOUR: Final = 120
MAPPING_MAX: Final = 64
CACHE_CONTROL: Final = "private, no-cache"
JSON_UTF8: Final = "application/json; charset=utf-8"
ImportKind = Literal["trades", "positions"]


# ---------------------------------------------------------------------------
# 模型
# ---------------------------------------------------------------------------


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Resolution(BaseModel):
    choice: str
    reason: str | None
    by: uuid.UUID
    at: dt.datetime


class ImportFinding(BaseModel):
    id: str
    code: str
    severity: ImportSeverity
    scope: ImportScope
    row_no: int | None
    field: str | None
    message: str
    params: dict[str, Any]
    needs_action: bool
    resolution_choices: list[str]
    default_resolution: str | None
    resolution: Resolution | None


class ImportStats(BaseModel):
    rows: int
    ok: int
    warning: int
    error: int
    skipped: int
    new: int
    duplicate_in_db: int
    duplicate_in_file: int
    possible_duplicate_of_manual: int
    needs_action_open: int


class UploadOut(BaseModel):
    batch_id: uuid.UUID
    status: Literal["uploaded"]
    file_findings: list[ImportFinding]


class ImportBatchSummary(BaseModel):
    batch_id: uuid.UUID
    account_id: uuid.UUID
    kind: ImportKind
    status: ImportStatus
    parser_id: str | None
    stats: ImportStats
    created_at: dt.datetime
    committed_at: dt.datetime | None
    reverted_at: dt.datetime | None


class ImportBatchDetail(ImportBatchSummary):
    parser_version: str | None
    detected_encoding: str | None
    encoding_override: str | None
    encoding_confidence: float | None
    format_score: float | None
    detected_columns: list[str]
    mapping: dict[str, str] | None
    snapshot_as_of: dt.datetime | None
    file_findings: list[ImportFinding]


class ImportRowOut(BaseModel):
    row_no: int
    status: ImportRowStatus
    kind: str
    dedup_status: DedupStatus | None
    findings: list[ImportFinding]
    raw_masked: str
    normalized: dict[str, Any] | None


_Mapping = Annotated[
    dict[
        Annotated[str, StringConstraints(min_length=1, max_length=64)],
        Annotated[str, StringConstraints(min_length=1, max_length=64)],
    ],
    Field(max_length=MAPPING_MAX),
]


class OptionsIn(_Body):
    encoding_override: Annotated[str, StringConstraints(max_length=32)] | None = None
    parser_id: Annotated[str, StringConstraints(max_length=64)] | None = None
    mapping: _Mapping | None = None
    snapshot_as_of: dt.datetime | None = None


class StatusOut(BaseModel):
    status: str


class ResolveIn(_Body):
    choice: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    reason: Annotated[str, StringConstraints(max_length=1000)] | None = None


class ConfirmIn(_Body):
    mode: Literal["all", "valid_rows_only"]
    acknowledge_warnings: bool


class Written(BaseModel):
    trades: int
    events: int
    snapshot_positions: int


class ReconSummary(BaseModel):
    status: ReconciliationStatus
    diff_count: int


class ConfirmOut(BaseModel):
    status: Literal["committed"]
    written: Written
    reconciliation: ReconSummary | None


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

_EMPTY_STATS: Final = dict.fromkeys(ImportStats.model_fields, 0)


def _stats(batch: Row[Any]) -> dict[str, int]:
    got = (batch.summary or {}).get("stats") or {}
    return {k: int(got.get(k, 0)) for k in _EMPTY_STATS}


def _ts(v: dt.datetime | None) -> str | None:
    return None if v is None else v.isoformat()


def summary_out(b: Row[Any]) -> dict[str, Any]:
    return {
        "batch_id": str(b.id),
        "account_id": str(b.account_id),
        "kind": b.kind,
        "status": b.status,
        "parser_id": b.parser_id,
        "stats": _stats(b),
        "created_at": _ts(b.created_at),
        "committed_at": _ts(b.committed_at),
        "reverted_at": _ts(b.reverted_at),
    }


def detail_out(b: Row[Any]) -> dict[str, Any]:
    return summary_out(b) | {
        "parser_version": b.parser_version,
        "detected_encoding": b.detected_encoding,
        "encoding_override": b.encoding_override,
        "encoding_confidence": None
        if b.encoding_confidence is None
        else float(b.encoding_confidence),
        "format_score": None if b.format_score is None else float(b.format_score),
        "detected_columns": list(b.detected_columns or []),
        "mapping": b.mapping,
        "snapshot_as_of": _ts(b.snapshot_as_of),
        "file_findings": list(b.file_findings or []),
    }


def _public_normalized(n: dict[str, Any] | None) -> dict[str, Any] | None:
    if n is None:
        return None
    return {k: v for k, v in n.items() if not k.startswith("_")}


def _owned_batch(
    conn: Connection, auth: AuthContext, batch_id: uuid.UUID, *, lock: bool = False
) -> Row[Any]:
    q = select(import_batches).where(
        import_batches.c.id == batch_id, import_batches.c.user_id == auth.user_id
    )
    if lock:
        q = q.with_for_update()
    row = conn.execute(q).first()
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND)
    return row


def _limit(rds: redis.Redis, auth: AuthContext, scope: str, per_hour: int) -> None:
    RateLimiter(rds).enforce(f"user:{auth.user_id}", [Window(scope, per_hour, 3600)])


def _audit(
    conn: Connection,
    request: Request,
    settings: Settings,
    auth: AuthContext,
    action: str,
    batch_id: uuid.UUID,
    detail: dict[str, Any],
) -> None:
    auth_service.audit(
        conn,
        action=action,
        actor_id=auth.user_id,
        actor_role=auth.user.role,
        target_type="import_batch",
        target_id=str(batch_id),
        detail=detail,
        ip_hash=ip_hash(settings, client_ip(request, settings)),
    )


def _etag(payload: bytes) -> str:
    return 'W/"' + hashlib.sha256(payload).hexdigest()[:32] + '"'


def _etag_matches(header: str, etag: str) -> bool:
    """RFC 9110 §13.1.2：If-None-Match 用弱比较（忽略 ``W/``），``*`` 匹配任意表示。"""
    tags = {t.strip() for t in header.split(",")}
    if "*" in tags:
        return True
    return etag.removeprefix("W/") in {t.removeprefix("W/") for t in tags}


def etag_response(content: object, if_none_match: str | None) -> Response:
    """弱 ETag + ``Cache-Control: private, no-cache``（契约 §1 条件请求）；命中 → 304。"""
    body = json.dumps(content, ensure_ascii=False, separators=(",", ":"), default=str).encode()
    tag = _etag(body)
    headers = {"ETag": tag, "Cache-Control": CACHE_CONTROL}
    if if_none_match is not None and _etag_matches(if_none_match, tag):
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type=JSON_UTF8, headers=headers)


ETAG_RESPONSES: Final[dict[int | str, dict[str, Any]]] = {
    304: {"description": "Not Modified：If-None-Match 命中当前弱 ETag，无响应体"},
}


def _start_parse(engine: Engine, settings: Settings, batch_id: uuid.UUID) -> None:
    """后台任务：``uploaded`` → ``parsing`` → 解析。"""
    with engine.begin() as conn:
        conn.execute(
            update(import_batches)
            .where(import_batches.c.id == batch_id, import_batches.c.status == "uploaded")
            .values(status="parsing")
        )
    pipeline.run_parse(engine, settings, batch_id)


# ---------------------------------------------------------------------------
# 上传
# ---------------------------------------------------------------------------


def _upload_findings(
    settings: Settings, filename: str, data: bytes, size: int
) -> list[dict[str, Any]]:
    cfg = settings.business.imports
    out: list[dict[str, Any]] = []
    ext = PurePath(filename or "").suffix.lower()
    if size > cfg.max_file_bytes:
        out.append(fnd.make("IMPORT_FILE_TOO_LARGE", limit_mb=cfg.max_file_bytes // (1024 * 1024)))
        return out
    if ext not in cfg.allowed_extensions or b"\x00" in data:
        out.append(fnd.make("IMPORT_UNSUPPORTED_FILE_TYPE"))
        return out
    stripped = data.removeprefix(b"\xef\xbb\xbf").strip()
    if not stripped:
        out.append(fnd.make("IMPORT_EMPTY_FILE"))
        return out
    # 粗算：非空行数 − 1（表头）。精确行数在解析阶段再判（超限 → 批次 failed）
    lines = sum(1 for ln in stripped.splitlines() if ln.strip())
    if lines - 1 > cfg.max_rows_per_file:
        out.append(fnd.make("IMPORT_TOO_MANY_ROWS", limit=cfg.max_rows_per_file))
    return out


@router.post(
    "/imports",
    status_code=201,
    response_model=UploadOut,
    responses={422: {"description": "IMPORT_FILE_ERRORS：上传阶段文件级错误，不创建批次"}},
)
async def upload(
    request: Request,
    background: BackgroundTasks,
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
    rds: RedisDep,
    file: Annotated[UploadFile, File()],
    account_id: Annotated[uuid.UUID, Form()],
    kind: Annotated[ImportKind, Form()],
    snapshot_as_of: Annotated[dt.datetime | None, Form()] = None,
) -> dict[str, Any]:
    _limit(rds, auth, "imports:upload", UPLOADS_PER_HOUR)
    cfg = settings.business.imports
    data = await file.read(cfg.max_file_bytes + 1)
    size = len(data) if len(data) <= cfg.max_file_bytes else (file.size or len(data))
    filename = file.filename or ""
    with engine.connect() as conn:
        owned_account(conn, auth, account_id)
    errors = _upload_findings(settings, filename, data, size)
    if errors:
        raise AppError(ErrorCode.IMPORT_FILE_ERRORS, details={"findings": errors})
    sha = hashlib.sha256(data).hexdigest()
    batch_id = uuid.uuid4()
    rel = storage.write_raw(settings, str(auth.user_id), str(batch_id), data)
    del data
    now = dt.datetime.now(dt.UTC)
    file_findings: list[dict[str, Any]] = []
    try:
        with engine.begin() as conn:
            hit = conn.execute(
                select(import_batches.c.id, import_batches.c.created_at)
                .join(import_files, import_files.c.batch_id == import_batches.c.id)
                .where(
                    import_batches.c.account_id == account_id,
                    import_batches.c.status.in_(pipeline.LIVE_BATCH_STATES),
                    import_files.c.sha256 == sha,
                )
                .order_by(import_batches.c.created_at.desc())
                .limit(1)
            ).first()
            if hit is not None:
                file_findings.append(
                    fnd.make(
                        "IMPORT_DUPLICATE_FILE",
                        batch_id=str(hit.id),
                        imported_at=hit.created_at.astimezone(pipeline.BEIJING).isoformat(
                            timespec="seconds"
                        ),
                    )
                )
            conn.execute(
                insert(import_batches).values(
                    id=batch_id,
                    user_id=auth.user_id,
                    account_id=account_id,
                    status="uploaded",
                    kind=kind,
                    snapshot_as_of=snapshot_as_of,
                    file_findings=file_findings,
                    summary={"stats": _EMPTY_STATS, "parser_pinned": False},
                )
            )
            conn.execute(
                insert(import_files).values(
                    id=uuid.uuid4(),
                    batch_id=batch_id,
                    original_filename=None,  # 文件名可能含账户信息，不落库
                    size_bytes=size,
                    sha256=sha,
                    storage_path=rel,
                    retained_until=now + dt.timedelta(days=cfg.raw_file_retention_days),
                )
            )
            _audit(conn, request, settings, auth, "import.uploaded", batch_id, {"kind": kind})
    except BaseException:
        storage.delete_raw(settings, rel)
        raise
    background.add_task(_start_parse, engine, settings, batch_id)
    log.info("import uploaded batch=%s kind=%s bytes=%d", batch_id, kind, size)
    return {"batch_id": str(batch_id), "status": "uploaded", "file_findings": file_findings}


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------


@router.get("/imports", response_model=Page[ImportBatchSummary])
def list_imports(
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
    page: Annotated[PageParams, Depends(page_params)],
    account_id: uuid.UUID | None = None,
    status: ImportStatus | None = None,
) -> Page[dict[str, Any]]:
    b = import_batches
    cond = [b.c.user_id == auth.user_id]
    if account_id is not None:
        cond.append(b.c.account_id == account_id)
    if status is not None:
        cond.append(b.c.status == status.value)
    if page.cursor:
        keys = decode_cursor(page.cursor, scope=SCOPE_LIST, settings=settings)
        try:
            at, bid = dt.datetime.fromisoformat(str(keys[0])), uuid.UUID(str(keys[1]))
        except (ValueError, IndexError):
            raise AppError(ErrorCode.INVALID_CURSOR) from None
        cond.append(or_(b.c.created_at < at, and_(b.c.created_at == at, b.c.id < bid)))
    with engine.connect() as conn:
        rows = conn.execute(
            select(b)
            .where(*cond)
            .order_by(b.c.created_at.desc(), b.c.id.desc())
            .limit(page.limit + 1)
        ).all()
    built = build_page(
        rows,
        limit=page.limit,
        key=lambda r: [r.created_at.isoformat(), str(r.id)],
        scope=SCOPE_LIST,
        settings=settings,
    )
    return Page[dict[str, Any]](
        items=[summary_out(r) for r in built.items], next_cursor=built.next_cursor
    )


@router.get(
    "/imports/{batch_id}",
    response_model=ImportBatchDetail,
    responses=ETAG_RESPONSES,
)
def get_import(
    batch_id: uuid.UUID,
    auth: AuthDep,
    engine: EngineDep,
    if_none_match: Annotated[str | None, Header()] = None,
) -> Response:
    with engine.connect() as conn:
        b = _owned_batch(conn, auth, batch_id)
    content = ImportBatchDetail.model_validate(detail_out(b)).model_dump(mode="json")
    return etag_response(content, if_none_match)


@router.get("/imports/{batch_id}/rows", response_model=Page[ImportRowOut])
def list_rows(
    batch_id: uuid.UUID,
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
    page: Annotated[PageParams, Depends(page_params)],
    status: ImportRowStatus | None = None,
    code: Annotated[str | None, Query(max_length=64)] = None,
    dedup_status: DedupStatus | None = None,
) -> Page[dict[str, Any]]:
    r = import_rows
    cond = [r.c.batch_id == batch_id]
    if status is not None:
        cond.append(r.c.status == status.value)
    if dedup_status is not None:
        cond.append(r.c.dedup_status == dedup_status.value)
    if code:
        cond.append(r.c.findings.contains([{"code": code}]))
    if page.cursor:
        keys = decode_cursor(page.cursor, scope=f"{SCOPE_ROWS}:{batch_id}", settings=settings)
        if len(keys) != 1 or not isinstance(keys[0], int):
            raise AppError(ErrorCode.INVALID_CURSOR)
        cond.append(r.c.row_no > keys[0])
    with engine.connect() as conn:
        _owned_batch(conn, auth, batch_id)
        rows = conn.execute(select(r).where(*cond).order_by(r.c.row_no).limit(page.limit + 1)).all()
    built = build_page(
        rows,
        limit=page.limit,
        key=lambda x: [int(x.row_no)],
        scope=f"{SCOPE_ROWS}:{batch_id}",
        settings=settings,
    )
    items = [
        {
            "row_no": x.row_no,
            "status": x.status,
            "kind": x.kind,
            "dedup_status": x.dedup_status,
            "findings": list(x.findings or []),
            "raw_masked": storage.decrypt_line(settings, x.raw_line),
            "normalized": _public_normalized(x.normalized),
        }
        for x in built.items
    ]
    return Page[dict[str, Any]](items=items, next_cursor=built.next_cursor)


# ---------------------------------------------------------------------------
# 改选项 / 处理提示
# ---------------------------------------------------------------------------


def _field_error(field: str, issue: str) -> AppError:
    return AppError(
        ErrorCode.VALIDATION_ERROR, details={"fields": [{"field": field, "issue": issue}]}
    )


@router.put("/imports/{batch_id}/options", status_code=202, response_model=StatusOut)
def set_options(
    batch_id: uuid.UUID,
    body: OptionsIn,
    request: Request,
    background: BackgroundTasks,
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
    rds: RedisDep,
) -> dict[str, str]:
    _limit(rds, auth, "imports:write", WRITES_PER_HOUR)
    enc = None
    if body.encoding_override is not None:
        enc = ENCODING_ALIASES.get(body.encoding_override.strip().lower())
        if enc is None:
            raise _field_error("encoding_override", "unsupported")
        codecs.lookup(enc)
    pid = None
    if body.parser_id is not None:
        pid = resolve_parser_id(body.parser_id.strip())
        if pid is None:
            raise _field_error("parser_id", "unknown")
    with engine.begin() as conn:
        b = _owned_batch(conn, auth, batch_id, lock=True)
        if b.status not in ("previewed", "failed"):
            raise AppError(ErrorCode.INVALID_STATE_TRANSITION)
        if pid is not None and not pid.startswith(f"tdx_{b.kind}"):
            raise _field_error("parser_id", "kind_mismatch")
        summary = dict(b.summary or {}) | {"parser_pinned": pid is not None}
        conn.execute(
            update(import_batches)
            .where(import_batches.c.id == batch_id)
            .values(
                status="parsing",
                encoding_override=enc,
                parser_id=pid if pid is not None else b.parser_id,
                mapping=body.mapping,
                snapshot_as_of=body.snapshot_as_of,
                summary=summary,
            )
        )
        _audit(conn, request, settings, auth, "import.options_changed", batch_id, {})
    background.add_task(pipeline.run_parse, engine, settings, batch_id)
    return {"status": "parsing"}


def _find(
    b: Row[Any], rows: Sequence[Row[Any]], finding_id: str
) -> tuple[Row[Any] | None, dict[str, Any]] | None:
    for f in b.file_findings or []:
        if f.get("id") == finding_id:
            return None, f
    for r in rows:
        for f in r.findings or []:
            if f.get("id") == finding_id:
                return r, f
    return None


@router.post("/imports/{batch_id}/findings/{finding_id}/resolve", response_model=ImportFinding)
def resolve_finding(
    batch_id: uuid.UUID,
    finding_id: Annotated[str, StringConstraints(max_length=128)],
    body: ResolveIn,
    request: Request,
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
    rds: RedisDep,
) -> dict[str, Any]:
    _limit(rds, auth, "imports:write", WRITES_PER_HOUR)
    with engine.begin() as conn:
        b = _owned_batch(conn, auth, batch_id, lock=True)
        if b.status != "previewed":
            raise AppError(ErrorCode.INVALID_STATE_TRANSITION)
        row_no = None
        if finding_id.startswith("r"):
            head = finding_id[1:].split("-", 1)[0]
            row_no = int(head) if head.isdigit() else None
        q = select(import_rows).where(import_rows.c.batch_id == batch_id)
        rows = conn.execute(q.where(import_rows.c.row_no == row_no)).all() if row_no else []
        hit = _find(b, rows, finding_id)
        if hit is None:
            raise AppError(ErrorCode.NOT_FOUND)
        row, f = hit
        note = validate_resolution(f["code"], body.choice, body.reason)
        res = {
            "choice": body.choice,
            "reason": note,
            "by": str(auth.user_id),
            "at": dt.datetime.now(dt.UTC).isoformat(),
        }
        f = dict(f) | {"resolution": res}
        if row is None:
            ff = [f if x.get("id") == finding_id else x for x in b.file_findings or []]
            conn.execute(
                update(import_batches)
                .where(import_batches.c.id == batch_id)
                .values(file_findings=ff)
            )
        else:
            fl = [f if x.get("id") == finding_id else x for x in row.findings or []]
            conn.execute(update(import_rows).where(import_rows.c.id == row.id).values(findings=fl))
        conn.execute(
            update(import_batches).where(import_batches.c.id == batch_id).values(status="parsing")
        )
        _audit(
            conn,
            request,
            settings,
            auth,
            "import.finding_resolved",
            batch_id,
            {"finding_id": finding_id, "code": f["code"], "choice": body.choice, "reason": note},
        )
    # 处理结果影响行状态与去重：同步重新解析（解析器读取已保存的处理结果）
    pipeline.run_parse(engine, settings, batch_id)
    with engine.connect() as conn:
        b2 = _owned_batch(conn, auth, batch_id)
        rows2 = (
            conn.execute(
                select(import_rows).where(
                    import_rows.c.batch_id == batch_id, import_rows.c.row_no == row_no
                )
            ).all()
            if row_no
            else []
        )
    again = _find(b2, rows2, finding_id)
    return again[1] if again is not None else f


# ---------------------------------------------------------------------------
# 确认 / 放弃 / 回滚
# ---------------------------------------------------------------------------


@router.post(
    "/imports/{batch_id}/confirm",
    response_model=ConfirmOut,
    responses={
        409: {"description": "INVALID_STATE_TRANSITION / IDEMPOTENCY_CONFLICT"},
        422: {"description": "IMPORT_FILE_ERRORS / IMPORT_ROW_ERRORS / ..."},
    },
)
def confirm_import(
    batch_id: uuid.UUID,
    body: ConfirmIn,
    request: Request,
    response: Response,
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
    rds: RedisDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> object:
    _limit(rds, auth, "imports:write", WRITES_PER_HOUR)

    def _do() -> tuple[int, Any]:
        with engine.begin() as conn:
            b = _owned_batch(conn, auth, batch_id, lock=True)
            out = pipeline.confirm(
                conn,
                settings,
                b,
                mode=body.mode,
                acknowledge_warnings=body.acknowledge_warnings,
            )
            _audit(
                conn,
                request,
                settings,
                auth,
                "import.confirmed",
                batch_id,
                {"mode": body.mode, "written": out["written"]},
            )
        log.info("import committed batch=%s written=%s", batch_id, out["written"])
        return 200, out

    status, out = idempotency.run(
        rds,
        user_id=auth.user_id,
        scope=f"imports:confirm:{batch_id}",
        key=idempotency_key,
        payload=body.model_dump(mode="json"),
        fn=_do,
    )
    response.status_code = status
    return out


@router.post("/imports/{batch_id}/discard", response_model=StatusOut)
def discard_import(
    batch_id: uuid.UUID,
    request: Request,
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
    rds: RedisDep,
) -> dict[str, str]:
    _limit(rds, auth, "imports:write", WRITES_PER_HOUR)
    now = dt.datetime.now(dt.UTC)
    with engine.begin() as conn:
        b = _owned_batch(conn, auth, batch_id, lock=True)
        if b.status not in ("previewed", "failed"):
            raise AppError(ErrorCode.INVALID_STATE_TRANSITION)
        files = conn.execute(
            select(import_files).where(
                import_files.c.batch_id == batch_id, import_files.c.deleted_at.is_(None)
            )
        ).all()
        conn.execute(
            update(import_batches).where(import_batches.c.id == batch_id).values(status="discarded")
        )
        conn.execute(
            update(import_files)
            .where(import_files.c.batch_id == batch_id)
            .values(deleted_at=now, storage_path=None)
        )
        _audit(conn, request, settings, auth, "import.discarded", batch_id, {})
    for f in files:
        if f.storage_path:
            storage.delete_raw(settings, f.storage_path)
    return {"status": "discarded"}


@router.post("/imports/{batch_id}/revert", response_model=StatusOut)
def revert_import(
    batch_id: uuid.UUID,
    request: Request,
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
    rds: RedisDep,
) -> dict[str, str]:
    _limit(rds, auth, "imports:write", WRITES_PER_HOUR)
    with engine.begin() as conn:
        b = _owned_batch(conn, auth, batch_id, lock=True)
        pipeline.revert(conn, b)
        _audit(conn, request, settings, auth, "import.reverted", batch_id, {})
    log.info("import reverted batch=%s", batch_id)
    return {"status": "reverted"}


# ---------------------------------------------------------------------------
# errors.csv
# ---------------------------------------------------------------------------

_CSV_FORMULA: Final = ("=", "+", "-", "@", "\t", "\r")


def _cell(v: object) -> str:
    s = "" if v is None else str(v)
    return "'" + s if s.startswith(_CSV_FORMULA) else s


@router.get(
    "/imports/{batch_id}/errors.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {"schema": {"type": "string"}}}}},
)
def errors_csv(
    batch_id: uuid.UUID,
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
) -> Response:
    """文件级与行级的 error / warning 提示，一条提示一行；只含掩码后的原始行。"""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(["row_no", "code", "severity", "field", "message", "raw_masked"])
    with engine.connect() as conn:
        b = _owned_batch(conn, auth, batch_id)
        for f in b.file_findings or []:
            if f["severity"] in ("error", "warning"):
                w.writerow(
                    ["", f["code"], f["severity"], _cell(f.get("field")), _cell(f["message"]), ""]
                )
        for r in conn.execute(
            select(import_rows)
            .where(
                import_rows.c.batch_id == batch_id, import_rows.c.status.in_(["error", "warning"])
            )
            .order_by(import_rows.c.row_no)
        ):
            raw = storage.decrypt_line(settings, r.raw_line)
            for f in r.findings or []:
                if f["severity"] in ("error", "warning"):
                    w.writerow(
                        [
                            r.row_no,
                            f["code"],
                            f["severity"],
                            _cell(f.get("field")),
                            _cell(f["message"]),
                            _cell(raw),
                        ]
                    )
    data = "\ufeff" + buf.getvalue()
    return Response(
        content=data.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="import-{batch_id}-errors.csv"',
            "Cache-Control": "private, no-store",
        },
    )
