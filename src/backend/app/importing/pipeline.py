"""导入批次的库侧流程（契约 v0.2.8 §7.2 ``/imports*``；plan §3.5A；T-B46）。

- :func:`load_context`：读证券主数据、交易日历、本账户已有去重键 / 手动成交弱指纹 / 持仓流水 /
  已登记股东代码 HMAC / 同文件批次 / 已有快照日期，组装纯函数 :func:`preview_bytes` 的上下文。
- :func:`run_parse`：后台解析（读加密原始文件 → 预览 → 写 ``import_rows``，
  原始行**先掩码再加密**）。
- :func:`confirm`：两步提交的第二步（写成交 / 账户事件 / 快照，重建持仓，对账）。
- :func:`revert`：回滚（成交作废 ``batch_reverted:{id}``，事件删除，快照随批次状态失效）。
- :func:`rebuild_holdings`：由 ``opening_positions + trades + account_events`` 全量重放重建
  ``holdings``（摊薄成本，见 :mod:`app.domain.portfolio`）。

日志只记批次 id 与计数，绝不记原始行、股东代码或文件内容。
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from collections import defaultdict
from decimal import Decimal
from typing import Any, Final
from zoneinfo import ZoneInfo

from sqlalchemy import (
    ColumnElement,
    Connection,
    Engine,
    Row,
    Select,
    and_,
    delete,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.common.errors import AppError, ErrorCode
from app.config import Settings
from app.db.tables.accounts import (
    account_events,
    broker_position_snapshot_items,
    broker_position_snapshots,
    holdings,
    import_batches,
    import_files,
    import_rows,
    opening_positions,
    reconciliation_items,
    reconciliation_runs,
    trades,
)
from app.db.tables.market import securities, trading_calendar
from app.domain import portfolio as pf
from app.domain.trades import batch_revert_void_reason
from app.importing import findings as fnd
from app.importing import storage
from app.importing.masking import holder_hmac
from app.importing.preview import (
    Preview,
    PreviewContext,
    PreviewOptions,
    RowResult,
    SecurityInfo,
    compute_stats,
    infer_market,
    preview_bytes,
    weak_fingerprint,
    written_by_default,
)

log = logging.getLogger(__name__)

BEIJING: Final = ZoneInfo("Asia/Shanghai")
LIVE_BATCH_STATES: Final = ("uploaded", "parsing", "previewed", "committed")
MANUAL_VOID_PREFIX: Final = "replaced_by_import:"
#: 账户事件里改变数量的类型（与 portfolio 同口径）
_HOLDER_MARKET: Final = {"A": "SH", "0": "SZ"}


def _bj_day(ts: dt.datetime) -> dt.date:
    return ts.astimezone(BEIJING).date()


def _time_str(ts: dt.datetime | None) -> str:
    return "" if ts is None else ts.astimezone(BEIJING).time().isoformat("seconds")


def _dec(v: str | None) -> Decimal | None:
    return None if v is None else Decimal(v)


# ---------------------------------------------------------------------------
# 上下文
# ---------------------------------------------------------------------------


def bare_code(code: str) -> str:
    """``600000.SH`` → ``600000``（交割单与预览按 6 位代码处理）。"""
    return code.split(".", 1)[0]


def full_code(code: str, secs: dict[str, SecurityInfo] | None) -> str:
    """6 位代码 → 系统统一格式 ``600000.SH``：主数据有 → 其交易所；否则按代码段推断
    （可转债 11x → SH、12x → SZ）；推断不出时保留原样。"""
    if "." in code:
        return code
    info = secs.get(code) if secs else None
    market = info.exchange if info is not None else infer_market(code)
    return f"{code}.{market}" if market else code


def load_securities(conn: Connection) -> dict[str, SecurityInfo] | None:
    """主数据（不含指数，避免 000001.SH 指数与 000001.SZ 股票的 6 位代码冲突），按 6 位代码索引。"""
    rows = conn.execute(
        select(
            securities.c.code,
            securities.c.name,
            securities.c.exchange,
            securities.c.type,
            securities.c.board,
        ).where(securities.c.type != "index")
    ).all()
    if not rows:
        return None
    out: dict[str, SecurityInfo] = {}
    for r in rows:
        b = bare_code(r.code)
        out[b] = SecurityInfo(b, r.name, r.exchange, r.type, r.board)
    return out


def _calendar(conn: Connection) -> tuple[set[dt.date] | None, tuple[dt.date, dt.date] | None]:
    rng = conn.execute(
        select(func.min(trading_calendar.c.date), func.max(trading_calendar.c.date))
    ).one()
    if rng[0] is None:
        return None, None
    days = set(
        conn.execute(select(trading_calendar.c.date).where(trading_calendar.c.is_open)).scalars()
    )
    return days, (rng[0], rng[1])


def _live_trades(account_id: uuid.UUID) -> ColumnElement[bool]:
    return and_(trades.c.account_id == account_id, trades.c.voided_at.is_(None))


def ledger_entries(conn: Connection, account_id: uuid.UUID) -> list[pf.LedgerEntry]:
    """本账户全部未作废流水（期初持仓 + 成交 + 带代码的账户事件），供重放。"""
    out: list[pf.LedgerEntry] = []
    for o in conn.execute(
        select(opening_positions).where(opening_positions.c.account_id == account_id)
    ).mappings():
        qty = Decimal(o["quantity"])
        cost = Decimal(o["cost_price"]) if o["cost_price"] is not None else Decimal(0)
        out.append(pf.LedgerEntry(o["as_of_date"], "", 0, o["security_code"], qty, -(cost * qty)))
    for t in conn.execute(select(trades).where(_live_trades(account_id))).mappings():
        qty = Decimal(t["quantity"])
        fees = [t[c] for c in ("commission", "stamp_tax", "transfer_fee", "other_fee")]
        fee_sum = sum((Decimal(f) for f in fees if f is not None), Decimal(0))
        amount = Decimal(t["amount"]) if t["amount"] is not None else qty * Decimal(t["price"])
        cash = pf.trade_cash(
            t["side"],
            amount,
            fee_sum,
            None if t["net_amount"] is None else Decimal(t["net_amount"]),
        )
        out.append(
            pf.LedgerEntry(
                t["trade_date"],
                _time_str(t["traded_at"]),
                1,
                t["security_code"],
                qty if t["side"] == "buy" else -qty,
                cash,
                t["traded_at"],
            )
        )
    for e in conn.execute(
        select(account_events).where(
            account_events.c.account_id == account_id,
            account_events.c.security_code.is_not(None),
        )
    ).mappings():
        q = pf.event_qty(e["kind"], None if e["quantity"] is None else Decimal(e["quantity"]))
        cash = Decimal(e["amount"]) if e["amount"] is not None else Decimal(0)
        out.append(pf.LedgerEntry(e["occurred_on"], "~", 2, e["security_code"], q, cash))
    return out


def _registered_holders(conn: Connection, account_id: uuid.UUID) -> dict[str, set[str]]:
    out: dict[str, set[str]] = defaultdict(set)
    q1 = select(trades.c.shareholder_code_hmac, trades.c.shareholder_code_masked).where(
        _live_trades(account_id), trades.c.shareholder_code_hmac.is_not(None)
    )
    q2 = (
        select(
            broker_position_snapshot_items.c.shareholder_code_hmac,
            broker_position_snapshot_items.c.shareholder_code_masked,
        )
        .select_from(
            broker_position_snapshot_items.join(
                broker_position_snapshots,
                broker_position_snapshots.c.id == broker_position_snapshot_items.c.snapshot_id,
            ).join(
                import_batches,
                import_batches.c.id == broker_position_snapshots.c.import_batch_id,
            )
        )
        .where(
            broker_position_snapshots.c.account_id == account_id,
            import_batches.c.status == "committed",
            broker_position_snapshot_items.c.shareholder_code_hmac.is_not(None),
        )
    )
    for q in (q1, q2):
        for h, masked in conn.execute(q.distinct()).all():
            market = _HOLDER_MARKET.get((masked or "")[:1])
            if market:
                out[market].add(h)
    return dict(out)


def live_snapshots(account_id: uuid.UUID) -> Select[Any]:
    """有效快照：来自已提交（未回滚）批次。"""
    return (
        select(broker_position_snapshots)
        .join(import_batches, import_batches.c.id == broker_position_snapshots.c.import_batch_id)
        .where(
            broker_position_snapshots.c.account_id == account_id,
            import_batches.c.status == "committed",
        )
    )


def load_context(
    conn: Connection,
    settings: Settings,
    batch: Row[Any],
    *,
    sha256: str | None,
    resolutions: dict[str, dict[str, Any]],
) -> PreviewContext:
    account_id = batch.account_id
    days, rng = _calendar(conn)
    existing: dict[str, str | None] = {
        k: (None if b is None else str(b))
        for k, b in conn.execute(
            select(trades.c.dedup_key, trades.c.import_batch_id).where(
                _live_trades(account_id), trades.c.dedup_key.is_not(None)
            )
        ).all()
    }
    manual: dict[str, str] = {}
    for t in conn.execute(
        select(
            trades.c.id,
            trades.c.trade_date,
            trades.c.security_code,
            trades.c.side,
            trades.c.quantity,
            trades.c.price,
        ).where(_live_trades(account_id), trades.c.source == "manual")
    ).all():
        fp = weak_fingerprint(
            str(account_id), t.trade_date, bare_code(t.security_code), t.side, t.quantity, t.price
        )
        manual.setdefault(fp, str(t.id))
    ledger = [
        (e.day, "" if e.time == "~" else e.time, bare_code(e.code), e.qty)
        for e in ledger_entries(conn, account_id)
        if e.qty != 0
    ]
    dup: dict[str, Any] | None = None
    if sha256 is not None:
        hit = conn.execute(
            select(import_batches.c.id, import_batches.c.created_at)
            .join(import_files, import_files.c.batch_id == import_batches.c.id)
            .where(
                import_batches.c.account_id == account_id,
                import_batches.c.id != batch.id,
                import_batches.c.status.in_(LIVE_BATCH_STATES),
                import_files.c.sha256 == sha256,
                import_batches.c.created_at <= batch.created_at,
            )
            .order_by(import_batches.c.created_at.desc())
            .limit(1)
        ).first()
        if hit is not None:
            dup = {
                "batch_id": str(hit.id),
                "imported_at": hit.created_at.astimezone(BEIJING).isoformat(timespec="seconds"),
            }
    snap_days = {
        _bj_day(s.as_of)
        for s in conn.execute(live_snapshots(account_id)).all()
        if s.as_of is not None
    }
    return PreviewContext(
        account_id=str(account_id),
        today=dt.datetime.now(BEIJING).date(),
        uploaded_at=batch.created_at,
        holder_hmac=lambda code: holder_hmac(settings, code),
        securities=load_securities(conn),
        trading_days=days,
        calendar_range=rng,
        market_rules=settings.business.market_rules,
        existing_keys=existing,
        manual_fingerprints=manual,
        ledger=ledger,
        registered_holders=_registered_holders(conn, account_id),
        duplicate_file=dup,
        existing_snapshot_dates=snap_days,
        resolutions=resolutions,
        max_rows=settings.business.imports.max_rows_per_file,
    )


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------


def _collect_resolutions(conn: Connection, batch: Row[Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for f in batch.file_findings or []:
        if f.get("resolution"):
            out[f["id"]] = f["resolution"]
    for fl in conn.execute(
        select(import_rows.c.findings).where(import_rows.c.batch_id == batch.id)
    ).scalars():
        for f in fl or []:
            if f.get("resolution"):
                out[f["id"]] = f["resolution"]
    return out


#: 架构师裁定（T-live-83a031c §8，契约随 T-A04）：批次进入这些状态时，同一事务内删除其全部预览行
#: （``import_rows``，未提交的行级数据）；批次头保留；原始文件按保留策略处理（不在此删除）。
ROWS_DROPPED_STATUSES: Final = ("discarded", "failed")


def drop_uncommitted_rows(conn: Connection, batch_id: uuid.UUID) -> int:
    """删除一个批次的预览行（调用方保证批次在同一事务内已置为 discarded / failed）。"""
    res = conn.execute(delete(import_rows).where(import_rows.c.batch_id == batch_id))
    return int(res.rowcount or 0)


def purge_uncommitted_import_rows(conn: Connection) -> int:
    """定时清理（beat 每小时排程、worker 执行）：删除 discarded / failed 批次残留的预览行。

    幂等：只按批次当前状态删除，重复执行第二次删 0 行；状态判定与删除在同一条语句里，
    并发的“重新解析”（failed → parsing）不会被误删（语句快照内批次已不是 failed）。"""
    b = import_batches
    res = conn.execute(
        delete(import_rows).where(
            import_rows.c.batch_id.in_(select(b.c.id).where(b.c.status.in_(ROWS_DROPPED_STATUSES)))
        )
    )
    return int(res.rowcount or 0)


def run_parse(engine: Engine, settings: Settings, batch_id: uuid.UUID) -> None:
    """后台任务：解析一个 ``uploaded``/``parsing`` 批次。任何异常 → ``failed``（只记批次 id）。"""
    try:
        _run_parse(engine, settings, batch_id)
    except Exception:
        log.exception("import parse failed batch=%s", batch_id)
        with engine.begin() as conn:
            res = conn.execute(
                update(import_batches)
                .where(import_batches.c.id == batch_id, import_batches.c.status == "parsing")
                .values(status="failed")
            )
            if res.rowcount:
                drop_uncommitted_rows(conn, batch_id)


def _run_parse(engine: Engine, settings: Settings, batch_id: uuid.UUID) -> None:
    with engine.begin() as conn:
        batch = conn.execute(
            select(import_batches).where(import_batches.c.id == batch_id).with_for_update()
        ).first()
        if batch is None or batch.status != "parsing":
            return
        f = conn.execute(
            select(import_files).where(
                import_files.c.batch_id == batch_id, import_files.c.deleted_at.is_(None)
            )
        ).first()
        if f is None or f.storage_path is None:
            conn.execute(
                update(import_batches)
                .where(import_batches.c.id == batch_id)
                .values(status="failed")
            )
            drop_uncommitted_rows(conn, batch_id)
            return
        data = storage.read_raw(settings, f.storage_path, str(batch_id))
        resolutions = _collect_resolutions(conn, batch)
        ctx = load_context(conn, settings, batch, sha256=f.sha256, resolutions=resolutions)
        options = PreviewOptions(
            encoding_override=batch.encoding_override,
            parser_id=batch.parser_id if (batch.summary or {}).get("parser_pinned") else None,
            mapping=batch.mapping,
            snapshot_as_of=batch.snapshot_as_of,
        )
        pv = preview_bytes(data, batch.kind, options, ctx)
        del data
        _store_preview(conn, settings, batch, f.id, pv, ctx.securities)
    log.info("import parsed batch=%s status=%s rows=%d", batch_id, pv.status, len(pv.rows))


def _store_preview(
    conn: Connection,
    settings: Settings,
    batch: Row[Any],
    file_id: uuid.UUID,
    pv: Preview,
    secs: dict[str, SecurityInfo] | None,
) -> None:
    conn.execute(delete(import_rows).where(import_rows.c.batch_id == batch.id))
    # 架构师裁定（T-live §8）：解析结果为 failed → 不落预览行（统计仍写进批次 summary）
    stored = [] if pv.status in ROWS_DROPPED_STATUSES else pv.rows
    for r in stored:
        n = r.normalized
        if n and n.get("security_code"):
            n["security_code"] = full_code(n["security_code"], secs)
    payload = [
        {
            "id": uuid.uuid4(),
            "batch_id": batch.id,
            "file_id": file_id,
            "row_no": r.row_no,
            "raw_line": storage.encrypt_line(settings, r.raw_masked),
            "kind": r.kind,
            "status": r.status,
            "normalized": r.normalized,
            "findings": r.findings,
            "dedup_key": r.dedup_key,
            "dedup_status": r.dedup_status,
        }
        for r in stored
    ]
    for i in range(0, len(payload), 1000):
        conn.execute(insert(import_rows), payload[i : i + 1000])
    summary = dict(batch.summary or {})
    summary.update(
        {
            "stats": pv.stats,
            "snapshot": pv.snapshot,
            "snapshot_as_of_effective": None
            if pv.snapshot_as_of is None
            else pv.snapshot_as_of.isoformat(),
        }
    )
    conn.execute(
        update(import_batches)
        .where(import_batches.c.id == batch.id)
        .values(
            status=pv.status,
            parser_id=pv.parser_id,
            parser_version=pv.parser_version,
            detected_encoding=pv.detected_encoding,
            encoding_confidence=None
            if pv.encoding_confidence is None
            else Decimal(str(round(pv.encoding_confidence, 4))),
            format_score=None
            if pv.format_score is None
            else Decimal(str(round(pv.format_score, 4))),
            detected_columns=pv.detected_columns,
            file_findings=pv.file_findings,
            summary=summary,
        )
    )


# ---------------------------------------------------------------------------
# 行 → RowResult（确认 / 处理提示时用）
# ---------------------------------------------------------------------------


def row_result(r: Row[Any]) -> RowResult:
    return RowResult(
        row_no=r.row_no,
        kind=r.kind,
        status=r.status,
        findings=list(r.findings or []),
        normalized=r.normalized,
        dedup_key=r.dedup_key,
        dedup_status=r.dedup_status,
    )


def refresh_stats(conn: Connection, batch_id: uuid.UUID) -> dict[str, int]:
    batch = conn.execute(select(import_batches).where(import_batches.c.id == batch_id)).one()
    rows = [
        row_result(r)
        for r in conn.execute(select(import_rows).where(import_rows.c.batch_id == batch_id))
    ]
    stats = compute_stats(rows, list(batch.file_findings or []))
    summary = dict(batch.summary or {}) | {"stats": stats}
    conn.execute(
        update(import_batches).where(import_batches.c.id == batch_id).values(summary=summary)
    )
    return stats


# ---------------------------------------------------------------------------
# 确认
# ---------------------------------------------------------------------------


def _choice(findings: list[dict[str, Any]], code: str) -> str | None:
    for f in findings:
        if f["code"] == code:
            return fnd.effective_choice(f)
    return None


def confirm(
    conn: Connection,
    settings: Settings,
    batch: Row[Any],
    *,
    mode: str,
    acknowledge_warnings: bool,
) -> dict[str, Any]:
    """在调用方事务内提交批次；``batch`` 须已 ``FOR UPDATE`` 锁定。"""
    if batch.status == "failed":
        raise AppError(
            ErrorCode.IMPORT_FILE_ERRORS,
            details={"findings": [f for f in batch.file_findings or [] if fnd.is_error(f)]},
        )
    if batch.status != "previewed":
        raise AppError(ErrorCode.INVALID_STATE_TRANSITION)
    file_findings = list(batch.file_findings or [])
    blocking = [f for f in file_findings if fnd.is_error(f) and not f.get("resolution")]
    if blocking:
        raise AppError(ErrorCode.IMPORT_FILE_ERRORS, details={"findings": blocking})
    rows = [
        (r.id, row_result(r))
        for r in conn.execute(
            select(import_rows)
            .where(import_rows.c.batch_id == batch.id)
            .order_by(import_rows.c.row_no)
        )
    ]
    error_rows = [rr.row_no for _, rr in rows if rr.has_error]
    if mode == "all" and error_rows:
        raise AppError(ErrorCode.IMPORT_ROW_ERRORS, details={"error_rows": error_rows[:500]})
    selected = [(rid, rr) for rid, rr in rows if written_by_default(rr)]
    # 需要确认的提示：文件级 + 将写入行上的 warning；已逐条处理（resolve）的不再计
    pending = [f for f in file_findings if f["severity"] == "warning" and not f.get("resolution")]
    pending += [
        f
        for _, rr in selected
        for f in rr.findings
        if f["severity"] == "warning" and not f.get("resolution")
    ]
    if pending and not acknowledge_warnings:
        raise AppError(
            ErrorCode.IMPORT_WARNINGS_UNACKNOWLEDGED,
            details={"codes": sorted({f["code"] for f in pending}), "count": len(pending)},
        )
    if not selected:
        raise AppError(ErrorCode.IMPORT_NOTHING_TO_COMMIT)

    now = dt.datetime.now(dt.UTC)
    written = {"trades": 0, "events": 0, "snapshot_positions": 0}
    reconciliation: dict[str, Any] | None = None
    if batch.kind == "trades":
        for rid, rr in selected:
            if rr.kind == "trade":
                written["trades"] += _commit_trade(conn, batch, rid, rr, now)
            elif rr.kind == "event":
                written["events"] += _commit_event(conn, batch, rid, rr)
    else:
        snap_id = _commit_snapshot(conn, batch, selected)
        written["snapshot_positions"] = len(selected)
        rebuild_holdings(conn, batch.account_id, batch_id=batch.id)
        reconciliation = run_reconciliation(conn, batch.account_id, snap_id, trigger="import")
    if batch.kind == "trades":
        if written["trades"] == 0 and written["events"] == 0:
            raise AppError(ErrorCode.IMPORT_NOTHING_TO_COMMIT)
        rebuild_holdings(conn, batch.account_id, batch_id=batch.id)
        latest = conn.execute(
            live_snapshots(batch.account_id)
            .order_by(broker_position_snapshots.c.version_no.desc())
            .limit(1)
        ).first()
        if latest is not None:
            reconciliation = run_reconciliation(conn, batch.account_id, latest.id, trigger="import")
    conn.execute(
        update(import_batches)
        .where(import_batches.c.id == batch.id)
        .values(
            status="committed",
            committed_at=now,
            summary=dict(batch.summary or {}) | {"written": written, "mode": mode},
        )
    )
    return {"status": "committed", "written": written, "reconciliation": reconciliation}


def _commit_trade(
    conn: Connection, batch: Row[Any], rid: uuid.UUID, rr: RowResult, now: dt.datetime
) -> int:
    n = rr.normalized or {}
    key = rr.dedup_key
    if rr.dedup_status in {"duplicate_in_db", "duplicate_in_file"}:
        key = f"{key}#force:{batch.id}:{rr.row_no}"
    if (
        rr.dedup_status == "possible_duplicate_of_manual"
        and _choice(rr.findings, "IMPORT_POSSIBLE_DUPLICATE_OF_MANUAL") == "keep_import_void_manual"
    ):
        for f in rr.findings:
            manual_id = (f.get("params") or {}).get("trade_id")
            if f["code"] == "IMPORT_POSSIBLE_DUPLICATE_OF_MANUAL" and manual_id:
                conn.execute(
                    update(trades)
                    .where(
                        trades.c.id == uuid.UUID(str(manual_id)),
                        trades.c.account_id == batch.account_id,
                        trades.c.voided_at.is_(None),
                    )
                    .values(voided_at=now, void_reason=f"{MANUAL_VOID_PREFIX}{batch.id}")
                )
    d = dt.date.fromisoformat(n["trade_date"])
    traded_at = (
        None
        if not n.get("trade_time")
        else dt.datetime.combine(d, dt.time.fromisoformat(n["trade_time"]), BEIJING)
    )
    stmt = (
        pg_insert(trades)
        .values(
            id=uuid.uuid4(),
            account_id=batch.account_id,
            user_id=batch.user_id,
            security_code=n["security_code"],
            side=n["side"],
            quantity=Decimal(n["qty"]),
            price=Decimal(n["price"]),
            amount=_dec(n.get("amount")),
            commission=_dec(n.get("_commission")),
            stamp_tax=_dec(n.get("_stamp_tax")),
            transfer_fee=_dec(n.get("_transfer_fee")),
            other_fee=_dec(n.get("_other_fee")),
            net_amount=_dec(n.get("net_amount")),
            traded_at=traded_at,
            trade_date=d,
            broker_trade_no=n.get("_trade_no"),
            order_no=n.get("_order_no"),
            declare_no=n.get("_declare_no"),
            cash_balance_after=_dec(n.get("_balance")),
            shareholder_code_hmac=n.get("_holder_hmac"),
            shareholder_code_masked=n.get("_holder_masked"),
            source="import",
            import_batch_id=batch.id,
            import_row_no=rr.row_no,
            dedup_key=key,
        )
        .on_conflict_do_nothing(
            index_elements=["account_id", "dedup_key"],
            index_where=trades.c.voided_at.is_(None),
        )
        .returning(trades.c.id)
    )
    tid = conn.execute(stmt).scalar()
    if tid is None:
        # 并发提交的其他批次已写入同一成交：按库内重复处理
        conn.execute(
            update(import_rows)
            .where(import_rows.c.id == rid)
            .values(dedup_status="duplicate_in_db")
        )
        return 0
    conn.execute(update(import_rows).where(import_rows.c.id == rid).values(committed_trade_id=tid))
    return 1


def _commit_event(conn: Connection, batch: Row[Any], rid: uuid.UUID, rr: RowResult) -> int:
    n = rr.normalized or {}
    qty = _dec(n.get("_qty_signed"))
    stmt = (
        pg_insert(account_events)
        .values(
            id=uuid.uuid4(),
            account_id=batch.account_id,
            kind=n.get("event_type") or "other",
            security_code=n.get("security_code"),
            quantity=None if qty is None else abs(qty),
            amount=_dec(n.get("net_amount")),
            occurred_on=dt.date.fromisoformat(n["trade_date"]),
            import_batch_id=batch.id,
            dedup_key=rr.dedup_key,
        )
        .on_conflict_do_nothing(index_elements=["account_id", "dedup_key"])
        .returning(account_events.c.id)
    )
    eid = conn.execute(stmt).scalar()
    if eid is None:
        return 0
    conn.execute(update(import_rows).where(import_rows.c.id == rid).values(committed_event_id=eid))
    return 1


def _commit_snapshot(
    conn: Connection, batch: Row[Any], selected: list[tuple[uuid.UUID, RowResult]]
) -> uuid.UUID:
    summary = batch.summary or {}
    snap = summary.get("snapshot") or {}
    as_of_raw = summary.get("snapshot_as_of_effective")
    as_of = batch.snapshot_as_of or (
        dt.datetime.fromisoformat(as_of_raw) if as_of_raw else batch.created_at
    )
    version = (
        conn.execute(
            select(func.coalesce(func.max(broker_position_snapshots.c.version_no), 0)).where(
                broker_position_snapshots.c.account_id == batch.account_id
            )
        ).scalar_one()
        + 1
    )
    snap_id = uuid.uuid4()
    conn.execute(
        insert(broker_position_snapshots).values(
            id=snap_id,
            account_id=batch.account_id,
            import_batch_id=batch.id,
            as_of=as_of,
            currency=snap.get("currency") or "CNY",
            cash_balance=_dec(snap.get("cash_balance")),
            cash_available=_dec(snap.get("cash_available")),
            cash_withdrawable=_dec(snap.get("cash_withdrawable")),
            market_value_ref=_dec(snap.get("market_value_ref")),
            total_assets_ref=_dec(snap.get("total_assets_ref")),
            pnl_ref=_dec(snap.get("pnl_ref")),
            version_no=version,
        )
    )
    items = []
    for _, rr in selected:
        n = rr.normalized or {}
        items.append(
            {
                "id": uuid.uuid4(),
                "snapshot_id": snap_id,
                "security_code": n["security_code"],
                "quantity": _dec(n.get("qty")),
                "sellable_quantity": _dec(n.get("sellable_qty")),
                "broker_cost_price": _dec(n.get("cost_price")),
                "last_price_ref": _dec(n.get("last_price")),
                "market_value_ref": _dec(n.get("market_value")),
                "unrealized_pnl_ref": _dec(n.get("pnl")),
                "unrealized_pnl_pct_ref": _dec(n.get("pnl_pct")),
                "shareholder_code_hmac": n.get("_holder_hmac"),
                "shareholder_code_masked": n.get("_holder_masked"),
            }
        )
    conn.execute(insert(broker_position_snapshot_items), items)
    return snap_id


# ---------------------------------------------------------------------------
# 持仓重建与对账
# ---------------------------------------------------------------------------


def rebuild_holdings(
    conn: Connection, account_id: uuid.UUID, *, batch_id: uuid.UUID | None = None
) -> dict[str, pf.Lot]:
    lots = pf.replay(ledger_entries(conn, account_id))
    conn.execute(delete(holdings).where(holdings.c.account_id == account_id))
    now = dt.datetime.now(dt.UTC)
    payload = [
        {
            "account_id": account_id,
            "security_code": code,
            "quantity": lot.qty,
            "avg_cost": None if lot.avg_cost is None else lot.avg_cost.quantize(Decimal("1e-8")),
            "realized_pnl": pf.q2(lot.realized),
            "last_trade_at": lot.last_at,
            "rebuilt_at": now,
            "rebuild_batch_id": batch_id,
        }
        for code, lot in sorted(lots.items())
        if lot.qty > 0 or lot.realized != 0
    ]
    if payload:
        conn.execute(insert(holdings), payload)
    return lots


def last_cash_balance(conn: Connection, account_id: uuid.UUID) -> Decimal | None:
    row = conn.execute(
        select(trades.c.cash_balance_after)
        .where(_live_trades(account_id), trades.c.cash_balance_after.is_not(None))
        .order_by(
            trades.c.trade_date.desc(),
            trades.c.traded_at.desc().nulls_last(),
            trades.c.import_row_no.desc().nulls_last(),
            trades.c.created_at.desc(),
        )
        .limit(1)
    ).first()
    return None if row is None else Decimal(row[0])


def _chain_breaks(conn: Connection, account_id: uuid.UUID) -> int:
    n = 0
    for fl in conn.execute(
        select(import_rows.c.findings)
        .join(import_batches, import_batches.c.id == import_rows.c.batch_id)
        .where(
            import_batches.c.account_id == account_id,
            import_batches.c.status == "committed",
            import_rows.c.committed_trade_id.is_not(None),
        )
    ).scalars():
        n += sum(1 for f in fl or [] if f["code"] == "IMPORT_CASH_CHAIN_BREAK")
    return n


def run_reconciliation(
    conn: Connection, account_id: uuid.UUID, snapshot_id: uuid.UUID, *, trigger: str
) -> dict[str, Any]:
    has_ledger = bool(ledger_entries(conn, account_id))
    snap = conn.execute(
        select(broker_position_snapshots).where(broker_position_snapshots.c.id == snapshot_id)
    ).one()
    run_id = uuid.uuid4()
    if not has_ledger:
        conn.execute(
            insert(reconciliation_runs).values(
                id=run_id,
                account_id=account_id,
                snapshot_id=snapshot_id,
                trigger=trigger,
                status="not_imported",
            )
        )
        return {"status": "not_imported", "diff_count": 0}
    lots = pf.replay(ledger_entries(conn, account_id))
    broker: dict[str, tuple[Decimal, Decimal | None]] = {}
    for it in conn.execute(
        select(broker_position_snapshot_items).where(
            broker_position_snapshot_items.c.snapshot_id == snapshot_id
        )
    ).mappings():
        q = Decimal(it["quantity"] or 0)
        prev = broker.get(it["security_code"])
        broker[it["security_code"]] = (
            q + (prev[0] if prev else Decimal(0)),
            None if it["broker_cost_price"] is None else Decimal(it["broker_cost_price"]),
        )
    items = pf.reconcile(
        lots,
        broker,
        ours_cash=last_cash_balance(conn, account_id),
        broker_cash=None if snap.cash_balance is None else Decimal(snap.cash_balance),
        chain_breaks=_chain_breaks(conn, account_id),
    )
    status = "diff" if items else "matched"
    conn.execute(
        insert(reconciliation_runs).values(
            id=run_id,
            account_id=account_id,
            snapshot_id=snapshot_id,
            trigger=trigger,
            status=status,
        )
    )
    if items:
        conn.execute(
            insert(reconciliation_items),
            [
                {
                    "id": uuid.uuid4(),
                    "run_id": run_id,
                    "kind": i.kind,
                    "security_code": i.security_code,
                    "ours": {"value": i.ours},
                    "broker": {"value": i.broker},
                    "diff": {"value": i.diff},
                    "possible_causes": [i.note],
                    "suggested_actions": list(i.actions),
                }
                for i in items
            ],
        )
    return {"status": status, "diff_count": len(items)}


# ---------------------------------------------------------------------------
# 回滚
# ---------------------------------------------------------------------------


def revert(conn: Connection, batch: Row[Any]) -> None:
    """``committed`` → ``reverted``：成交作废、事件删除、持仓重建；
    快照随批次状态失效（只追加表）。"""
    if batch.status != "committed":
        raise AppError(ErrorCode.INVALID_STATE_TRANSITION)
    now = dt.datetime.now(dt.UTC)
    conn.execute(
        update(trades)
        .where(trades.c.import_batch_id == batch.id, trades.c.voided_at.is_(None))
        .values(voided_at=now, void_reason=batch_revert_void_reason(batch.id))
    )
    conn.execute(
        update(import_rows)
        .where(import_rows.c.batch_id == batch.id)
        .values(committed_event_id=None)
    )
    conn.execute(delete(account_events).where(account_events.c.import_batch_id == batch.id))
    conn.execute(
        update(import_batches)
        .where(import_batches.c.id == batch.id)
        .values(status="reverted", reverted_at=now)
    )
    rebuild_holdings(conn, batch.account_id, batch_id=batch.id)
