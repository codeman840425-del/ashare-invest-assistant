"""导入预览：纯函数，不读库、不写库（plan §3.5A-1/2，契约 §7.2，T-B46）。

``preview_bytes(data, kind, options, ctx)`` → :class:`Preview`。所有依赖库内状态的判断
（主数据、交易日历、已有去重键、手动成交弱指纹、库内流水、已登记股东代码、同文件、已有快照）
都由调用方装进 :class:`PreviewContext`。

判定顺序（plan“判定顺序”）：
1. 文件级：编码 → 格式（表头）→ 必填列 → 账户匹配；
2. 行级结构：``ROW_DECODE_ERROR`` → ``ROW_TRUNCATED`` → ``ROW_COLUMN_MISMATCH``，命中即停；
3. 字段级：报告**全部**字段错误；字段都通过后再做跨字段（数量为 0 / 价格 / 符号 / 金额）；
4. 无 error 的行才计算 warning 与去重；有 error 的行不出 warning、``dedup_status = null``。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Final
from zoneinfo import ZoneInfo

from app.config_files import MarketRulesConfig
from app.importing import findings as F  # noqa: N812
from app.importing.decoding import Decoded, DecodedLine, decode
from app.importing.masking import holder_market, holder_masked, mask_line
from app.importing.parsers import DEFAULT_FOR_KIND, PARSERS, resolve_parser_id
from app.importing.parsers.tdx import (
    Header,
    ParserSpec,
    find_header,
    is_blank_or_separator,
    is_total_line,
    sensitive_spans,
    sniff_candidates,
    split_row,
)
from app.importing.text import fmt_decimal, fmt_qty, parse_decimal, to_halfwidth, tokenize

BEIJING: Final = ZoneInfo("Asia/Shanghai")
AMOUNT_TOLERANCE: Final = Decimal("0.05")
NET_TOLERANCE: Final = Decimal("0.02")
CHAIN_TOLERANCE: Final = Decimal("0.005")
TOTALS_TOLERANCE: Final = Decimal("0.01")
FORMAT_THRESHOLD: Final = 0.95

BUY_WORDS: Final = frozenset({"买入", "证券买入", "买", "担保品买入"})
SELL_WORDS: Final = frozenset({"卖出", "证券卖出", "卖", "担保品卖出"})
#: 非成交业务 → account_events.kind（plan 3.5A-1 规则 7：股息红利税暂记 other）
EVENT_WORDS: Final[dict[str, str]] = {
    "红利入账": "dividend",
    "红利入帐": "dividend",
    "股息入账": "dividend",
    "股息红利税补缴": "other",
    "股息红利差异扣税": "other",
    "新股入帐": "ipo_allot",
    "新股入账": "ipo_allot",
    "送股入账": "bonus_share",
    "红股入账": "bonus_share",
    "配股入账": "rights",
    "转托管转入": "transfer_in",
    "转托管转出": "transfer_out",
    "利息归本": "interest",
    "批量利息归本": "interest",
}
CURRENCY_WORDS: Final[dict[str, str]] = {
    "人民币": "CNY",
    "美元": "USD",
    "港币": "HKD",
    "港元": "HKD",
}
_CODE_RE: Final = re.compile(r"\d{6}")
_DATE_RE: Final = re.compile(r"\d{8}")
_ZERO_AS_MISSING: Final = frozenset({"", "0"})


@dataclass(frozen=True, slots=True)
class SecurityInfo:
    code: str
    name: str
    exchange: str
    type: str
    board: str | None = None


@dataclass(slots=True)
class PreviewOptions:
    encoding_override: str | None = None
    parser_id: str | None = None
    mapping: dict[str, str] | None = None
    snapshot_as_of: dt.datetime | None = None


@dataclass(slots=True)
class PreviewContext:
    account_id: str
    today: dt.date
    #: 上传时刻（快照没有日期时的 as_of）
    uploaded_at: dt.datetime
    holder_hmac: Callable[[str], str]
    #: 主数据；``None`` 表示主数据为空（不报 UNKNOWN_SECURITY / NAME_MISMATCH，市场按代码段推断）
    securities: dict[str, SecurityInfo] | None = None
    #: 交易日集合；``None`` 表示日历未覆盖（退回周一至周五）
    trading_days: set[dt.date] | None = None
    calendar_range: tuple[dt.date, dt.date] | None = None
    market_rules: MarketRulesConfig | None = None
    #: 本账户未作废成交的去重键 → 来源批次 id（手动录入为 None）
    existing_keys: dict[str, str | None] = field(default_factory=dict)
    #: 本账户未作废手动成交的弱指纹 → trade id
    manual_fingerprints: dict[str, str] = field(default_factory=dict)
    #: 库内持仓流水 (日期, 时间 HH:MM:SS|"", 代码, 带符号数量)
    ledger: list[tuple[dt.date, str, str, Decimal]] = field(default_factory=list)
    #: 已登记股东代码 HMAC：市场 → 集合
    registered_holders: dict[str, set[str]] = field(default_factory=dict)
    duplicate_file: dict[str, Any] | None = None
    existing_snapshot_dates: set[dt.date] = field(default_factory=set)
    #: finding id → resolution（重新解析时保留用户已做的处理）
    resolutions: dict[str, dict[str, Any]] = field(default_factory=dict)
    max_rows: int = 50_000


@dataclass(slots=True)
class RowResult:
    row_no: int
    kind: str  # trade / event / ignored / snapshot_position
    status: str = "ok"
    findings: list[dict[str, Any]] = field(default_factory=list)
    normalized: dict[str, Any] | None = None
    dedup_key: str | None = None
    dedup_status: str | None = None
    raw_masked: str = ""

    @property
    def has_error(self) -> bool:
        return any(F.is_error(f) for f in self.findings)


@dataclass(slots=True)
class Preview:
    status: str  # previewed / failed
    kind: str
    parser_id: str | None
    parser_version: str | None
    detected_encoding: str | None
    encoding_confidence: float | None
    format_score: float | None
    detected_columns: list[str]
    file_findings: list[dict[str, Any]]
    rows: list[RowResult]
    snapshot: dict[str, Any] | None = None
    snapshot_as_of: dt.datetime | None = None

    @property
    def stats(self) -> dict[str, int]:
        return compute_stats(self.rows, self.file_findings)


def compute_stats(rows: list[RowResult], file_findings: list[dict[str, Any]]) -> dict[str, int]:
    s = dict.fromkeys(
        (
            "rows",
            "ok",
            "warning",
            "error",
            "skipped",
            "new",
            "duplicate_in_db",
            "duplicate_in_file",
            "possible_duplicate_of_manual",
            "needs_action_open",
        ),
        0,
    )
    s["rows"] = len(rows)
    for r in rows:
        s[r.status] += 1
        if r.dedup_status:
            s[r.dedup_status] += 1
        s["needs_action_open"] += sum(
            1 for f in r.findings if f["needs_action"] and not f.get("resolution")
        )
    s["needs_action_open"] += sum(
        1 for f in file_findings if f["needs_action"] and not f.get("resolution")
    )
    return s


def _h(*parts: object) -> str:
    return hashlib.sha256("|".join("" if p is None else str(p) for p in parts).encode()).hexdigest()


def infer_market(code: str) -> str | None:
    if code.startswith("920") or code[:1] in {"4", "8"}:
        return "BJ"
    if code[:1] in {"6", "9", "5"} or code.startswith("11"):
        return "SH"
    if code[:1] in {"0", "3", "1"}:
        return "SZ"
    return None


def infer_board(code: str, market: str | None) -> str:
    if market == "BJ":
        return "bse"
    if code.startswith(("688", "689")):
        return "star"
    if code.startswith(("300", "301", "302")):
        return "chinext"
    return "main"


def _parse_date(raw: str) -> dt.date | None:
    s = to_halfwidth(raw).strip()
    if not _DATE_RE.fullmatch(s):
        return None
    try:
        return dt.date(int(s[:4]), int(s[4:6]), int(s[6:]))
    except ValueError:
        return None


def _parse_time(raw: str) -> tuple[bool, dt.time | None]:
    """(有效, 时间)；``""`` / ``"0"`` 视为缺失 → (True, None)。"""
    s = to_halfwidth(raw).strip().replace(":", "")
    if s in _ZERO_AS_MISSING:
        return True, None
    if not s.isdigit() or len(s) not in (5, 6):
        return False, None
    s = s.zfill(6)
    try:
        return True, dt.time(int(s[:2]), int(s[2:4]), int(s[4:]))
    except ValueError:
        return False, None


def _num(raw: str) -> Decimal | None:
    try:
        return parse_decimal(raw)
    except (ValueError, InvalidOperation):
        return None


def _resolved(f: dict[str, Any], ctx: PreviewContext) -> dict[str, Any]:
    res = ctx.resolutions.get(f["id"])
    if res and res.get("choice") in (f["resolution_choices"] or []):
        f["resolution"] = res
    return f


def _mk(ctx: PreviewContext, code: str, /, **kw: Any) -> dict[str, Any]:  # noqa: ANN401
    return _resolved(F.make(code, **kw), ctx)


# ---------------------------------------------------------------------------
# 文件级
# ---------------------------------------------------------------------------


def _choose_parser(kind: str, options: PreviewOptions) -> ParserSpec:
    pid = resolve_parser_id(options.parser_id) if options.parser_id else None
    spec = PARSERS[pid] if pid else PARSERS[DEFAULT_FOR_KIND[kind]]
    return spec if spec.kind == kind else PARSERS[DEFAULT_FOR_KIND[kind]]


def _failed(
    kind: str,
    decoded: Decoded | None,
    findings: list[dict[str, Any]],
    **kw: Any,  # noqa: ANN401
) -> Preview:
    return Preview(
        status="failed",
        kind=kind,
        parser_id=kw.get("parser_id"),
        parser_version=kw.get("parser_version"),
        detected_encoding=None if decoded is None else decoded.encoding,
        encoding_confidence=None if decoded is None else decoded.confidence,
        format_score=kw.get("format_score"),
        detected_columns=kw.get("columns", []),
        file_findings=findings,
        rows=[],
    )


def preview_bytes(data: bytes, kind: str, options: PreviewOptions, ctx: PreviewContext) -> Preview:
    file_findings: list[dict[str, Any]] = []
    decoded = decode(data, override=options.encoding_override)
    if decoded.encoding is None:
        return _failed(kind, decoded, [_mk(ctx, "IMPORT_ENCODING_UNDETECTED")])
    lines = decoded.lines
    spec = _choose_parser(kind, options)
    header = find_header(spec, lines, options.mapping)
    if header is None:
        cands = [c for c in sniff_candidates(lines) if c != spec.parser_id]
        return _failed(
            kind,
            decoded,
            [
                _mk(
                    ctx,
                    "IMPORT_UNRECOGNIZED_FORMAT",
                    candidates="、".join(cands) or "无",
                    candidate_ids=cands,
                )
            ],
        )
    cols = [t.text for t in header.tokens]
    common = {
        "parser_id": spec.parser_id,
        "parser_version": spec.version,
        "format_score": header.score,
        "columns": cols,
    }
    if header.missing_required:
        return _failed(
            kind,
            decoded,
            [
                _mk(
                    ctx,
                    "IMPORT_REQUIRED_COLUMN_MISSING",
                    columns="、".join(header.missing_required),
                )
            ],
            **common,
        )
    if ctx.duplicate_file:
        file_findings.append(_mk(ctx, "IMPORT_DUPLICATE_FILE", **ctx.duplicate_file))
    if (decoded.confidence or 0.0) < 0.8 and options.encoding_override is None:
        file_findings.append(
            _mk(
                ctx,
                "IMPORT_ENCODING_LOW_CONFIDENCE",
                encoding=decoded.encoding,
                confidence=f"{decoded.confidence:.2f}",
            )
        )
    if header.score < FORMAT_THRESHOLD:
        file_findings.append(
            _mk(
                ctx,
                "IMPORT_FORMAT_LOW_CONFIDENCE",
                parser=spec.parser_id,
                score=f"{header.score:.2f}",
            )
        )
    if header.unknown:
        file_findings.append(_mk(ctx, "IMPORT_UNKNOWN_COLUMN", columns="、".join(header.unknown)))

    body = lines[header.index + 1 :]
    data_lines = [
        ln
        for ln in body
        if ln.text is None
        or not (is_blank_or_separator(ln.text) or is_total_line(tokenize(ln.text)))
    ]
    if len(data_lines) > ctx.max_rows:
        return _failed(
            kind, decoded, [_mk(ctx, "IMPORT_TOO_MANY_ROWS", limit=ctx.max_rows)], **common
        )
    if lines and not lines[-1].has_newline and lines[-1] in data_lines:
        last = lines[-1]
        if last.text is None or len(tokenize(last.text)) < len(header.tokens):
            file_findings.append(_mk(ctx, "IMPORT_FILE_POSSIBLY_TRUNCATED"))
    if not data_lines:
        file_findings.append(_mk(ctx, "IMPORT_NO_DATA_ROWS"))

    pre = lines[: header.index]
    rows = [
        _structural(spec, header, ln, is_last=ln is lines[-1], encoding=decoded.encoding, ctx=ctx)
        for ln in data_lines
    ]
    snapshot = None
    as_of = options.snapshot_as_of
    if spec.kind == "trades":
        holder_issue = _trade_rows(rows, ctx)
    else:
        snapshot, holder_issue = _position_rows(rows, ctx, pre, file_findings)
        if as_of is None:
            as_of = ctx.uploaded_at
            shown = as_of.astimezone(BEIJING) if as_of.tzinfo else as_of
            file_findings.append(
                _mk(ctx, "IMPORT_SNAPSHOT_AS_OF_ASSUMED", as_of=shown.isoformat(timespec="seconds"))
            )
        as_of_day = as_of.astimezone(BEIJING).date() if as_of.tzinfo else as_of.date()
        if as_of_day in ctx.existing_snapshot_dates:
            file_findings.append(
                _mk(ctx, "IMPORT_SNAPSHOT_SUPERSEDES", as_of=as_of_day.isoformat())
            )
    if holder_issue:
        file_findings.insert(0, _mk(ctx, "IMPORT_ACCOUNT_MISMATCH"))
    for r in rows:
        r.status = _row_status(r)
    blocking = [f for f in file_findings if F.is_error(f) and not f.get("resolution")]
    return Preview(
        status="failed" if blocking else "previewed",
        kind=kind,
        parser_id=spec.parser_id,
        parser_version=spec.version,
        detected_encoding=decoded.encoding,
        encoding_confidence=decoded.confidence,
        format_score=header.score,
        detected_columns=cols,
        file_findings=file_findings,
        rows=rows,
        snapshot=snapshot,
        snapshot_as_of=as_of,
    )


# ---------------------------------------------------------------------------
# 行级结构
# ---------------------------------------------------------------------------

_SKIP_CODES: Final = frozenset(
    {
        "IMPORT_ROW_CANCELLED",
        "IMPORT_ROW_REJECTED",
        "IMPORT_UNKNOWN_BIZ_TYPE",
        "IMPORT_DUPLICATE_IN_DB",
        "IMPORT_DUPLICATE_IN_FILE",
    }
)


def _row_status(r: RowResult) -> str:
    if r.has_error:
        return "error"
    if any(f["code"] in _SKIP_CODES for f in r.findings):
        return "skipped"
    if r.findings:
        return "warning"
    return "ok"


def _structural(
    spec: ParserSpec,
    header: Header,
    line: DecodedLine,
    *,
    is_last: bool,
    encoding: str,
    ctx: PreviewContext,
) -> RowResult:
    default_kind = "trade" if spec.kind == "trades" else "snapshot_position"
    r = RowResult(row_no=line.row_no, kind=default_kind)
    if line.text is None:
        r.findings.append(
            _mk(ctx, "IMPORT_ROW_DECODE_ERROR", row_no=line.row_no, encoding=encoding)
        )
        r.raw_masked = "（无法解码）"
        return r
    split = split_row(spec, header, line, is_last=is_last)
    text = line.text.replace("\t", "  ")
    r.raw_masked = mask_line(text, sensitive_spans(spec, header, split))
    if split.structural:
        r.findings.append(_mk(ctx, split.structural, row_no=line.row_no))
        return r
    r.normalized = {"_values": split.values, "_empty": split.empty_required}
    return r


# ---------------------------------------------------------------------------
# 成交明细
# ---------------------------------------------------------------------------

_TRADE_NUMERIC_REQUIRED: Final = ("qty", "price", "amount")
_TRADE_NUMERIC_OPTIONAL: Final = (
    "net_amount",
    "balance",
    "commission",
    "stamp_tax",
    "transfer_fee",
    "other_fee",
)
_FIELD_LABEL: Final = {c.field: c.name for spec in PARSERS.values() for c in spec.columns}


def _empty_field_finding(ctx: PreviewContext, row_no: int, f: str) -> dict[str, Any]:
    finding = _mk(ctx, "IMPORT_REQUIRED_FIELD_EMPTY", row_no=row_no, field=f)
    finding["params"]["field"] = _FIELD_LABEL.get(f, f)
    finding["message"] = F.render("IMPORT_REQUIRED_FIELD_EMPTY", finding["params"])
    return finding


def _validate_basic(
    r: RowResult,
    v: dict[str, str],
    ctx: PreviewContext,
    *,
    required: tuple[str, ...],
    numeric: tuple[str, ...],
    has_date: bool = True,
) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    empty = {f for f in required if not v.get(f, "").strip()}
    for f in required:
        if f in empty:
            r.findings.append(_empty_field_finding(ctx, r.row_no, f))
    if has_date and "trade_date" not in empty:
        raw = v.get("trade_date", "").strip()
        if raw:
            d = _parse_date(raw)
            if d is None:
                r.findings.append(
                    _mk(ctx, "IMPORT_INVALID_DATE", row_no=r.row_no, field="trade_date", value=raw)
                )
            elif d > ctx.today:
                r.findings.append(
                    _mk(ctx, "IMPORT_FUTURE_DATE", row_no=r.row_no, field="trade_date", value=raw)
                )
            else:
                parsed["trade_date"] = d
    if "trade_time" in v:
        ok, t = _parse_time(v["trade_time"])
        if not ok:
            r.findings.append(
                _mk(
                    ctx,
                    "IMPORT_INVALID_TIME",
                    row_no=r.row_no,
                    field="trade_time",
                    value=v["trade_time"].strip(),
                )
            )
        parsed["trade_time"] = t
    code_raw = to_halfwidth(v.get("security_code", "")).strip()
    if code_raw and "security_code" not in empty:
        if not _CODE_RE.fullmatch(code_raw):
            r.findings.append(
                _mk(
                    ctx,
                    "IMPORT_INVALID_SECURITY_CODE",
                    row_no=r.row_no,
                    field="security_code",
                    value=code_raw,
                )
            )
        else:
            parsed["security_code"] = code_raw
    for f in numeric:
        raw = v.get(f, "").strip()
        if not raw or f in empty:
            parsed[f] = None
            continue
        n = _num(raw)
        if n is None:
            r.findings.append(
                _mk(ctx, "IMPORT_INVALID_NUMBER", row_no=r.row_no, field=f, value=raw)
            )
            r.findings[-1]["params"]["field"] = _FIELD_LABEL.get(f, f)
            r.findings[-1]["message"] = F.render("IMPORT_INVALID_NUMBER", r.findings[-1]["params"])
        parsed[f] = n
    return parsed


def _no(v: dict[str, str], f: str) -> str | None:
    s = to_halfwidth(v.get(f, "")).strip()
    return None if s in _ZERO_AS_MISSING else s


def _classify(v: dict[str, str]) -> tuple[str, str | None]:
    """(类别, 方向/事件类型)：trade/buy|sell、event/<kind>、cancelled、rejected、unknown。"""
    biz = v.get("biz", "").strip()
    remark = v.get("remark", "").strip()
    if "废单" in biz or "废单" in remark:
        return "rejected", None
    if "撤单" in biz or "撤单" in remark or "撤销" in remark:
        return "cancelled", None
    if biz in BUY_WORDS:
        return "trade", "buy"
    if biz in SELL_WORDS:
        return "trade", "sell"
    if biz in EVENT_WORDS:
        return "event", EVENT_WORDS[biz]
    return "unknown", None


def _sum_fees(p: dict[str, Any]) -> Decimal:
    return sum(
        (p.get(f) or Decimal(0) for f in ("commission", "stamp_tax", "transfer_fee", "other_fee")),
        Decimal(0),
    )


def _trade_rows(rows: list[RowResult], ctx: PreviewContext) -> bool:
    """成交明细行的字段 / 跨字段 / 提示 / 去重；返回是否股东代码与账户不符。"""
    holders: set[tuple[str, str]] = set()
    parsed_by_row: dict[int, dict[str, Any]] = {}
    for r in rows:
        if r.normalized is None:
            continue
        v: dict[str, str] = r.normalized["_values"]
        r.normalized = None
        cat, sub = _classify(v)
        if cat in {"cancelled", "rejected"}:
            r.kind = "ignored"
            r.findings.append(
                _mk(
                    ctx,
                    "IMPORT_ROW_CANCELLED" if cat == "cancelled" else "IMPORT_ROW_REJECTED",
                    row_no=r.row_no,
                )
            )
            continue
        if cat == "unknown":
            r.kind = "ignored"
            r.findings.append(
                _mk(
                    ctx,
                    "IMPORT_UNKNOWN_BIZ_TYPE",
                    row_no=r.row_no,
                    biz=v.get("biz", "").strip() or "（空）",
                )
            )
            continue
        if cat == "event":
            r.kind = "event"
            p = _validate_basic(
                r,
                v,
                ctx,
                required=("trade_date",),
                numeric=("qty", "price", "amount", *_TRADE_NUMERIC_OPTIONAL),
            )
        else:
            p = _validate_basic(
                r,
                v,
                ctx,
                required=("trade_date", "security_code", "qty", "price", "amount"),
                numeric=(*_TRADE_NUMERIC_REQUIRED, *_TRADE_NUMERIC_OPTIONAL),
            )
            if not r.has_error:
                _cross_trade(r, p, sub or "", ctx)
        p["side"] = sub if cat == "trade" else None
        p["event_type"] = sub if cat == "event" else None
        p["name"] = v.get("name", "").strip() or None
        p["biz_type_raw"] = v.get("biz", "").strip()
        p["trade_no"] = _no(v, "trade_no")
        p["order_no"] = _no(v, "order_no")
        p["declare_no"] = _no(v, "declare_no")
        holder = to_halfwidth(v.get("holder", "")).strip()
        if holder and holder != "0":
            p["holder_hmac"] = ctx.holder_hmac(holder)
            p["holder_masked"] = holder_masked(holder)
            p["holder_market"] = holder_market(holder)
            if p["holder_market"]:
                holders.add((p["holder_market"], p["holder_hmac"]))
        if r.has_error:
            parsed_by_row[r.row_no] = p
            continue
        r.normalized = _normalize_trade(p)
        parsed_by_row[r.row_no] = p
    _row_warnings(rows, parsed_by_row, ctx)
    _dedup(rows, parsed_by_row, ctx)
    _cash_chain(rows, parsed_by_row, ctx)
    _missing_opening(rows, parsed_by_row, ctx)
    return _holder_mismatch(holders, ctx)


def _cross_trade(r: RowResult, p: dict[str, Any], side: str, ctx: PreviewContext) -> None:
    qty, price, amount = p["qty"], p["price"], p["amount"]
    if qty == 0:
        r.findings.append(_mk(ctx, "IMPORT_INVALID_QUANTITY", row_no=r.row_no, field="qty"))
        return
    if price <= 0 or amount <= 0:
        r.findings.append(_mk(ctx, "IMPORT_INVALID_PRICE", row_no=r.row_no, field="price"))
        return
    if (side == "buy" and qty < 0) or (side == "sell" and qty > 0):
        r.findings.append(_mk(ctx, "IMPORT_SIDE_QTY_SIGN_MISMATCH", row_no=r.row_no, field="qty"))
        return
    diff = abs(abs(qty) * price - amount)
    if diff > AMOUNT_TOLERANCE:
        r.findings.append(
            _mk(
                ctx,
                "IMPORT_AMOUNT_MISMATCH",
                row_no=r.row_no,
                field="amount",
                diff=fmt_decimal(diff, 2),
            )
        )


def _normalize_trade(p: dict[str, Any]) -> dict[str, Any]:
    d: dt.date = p["trade_date"]
    t: dt.time | None = p.get("trade_time")
    qty = p.get("qty")
    fees = _sum_fees(p)
    any_fee = any(
        p.get(f) is not None for f in ("commission", "stamp_tax", "transfer_fee", "other_fee")
    )
    return {
        "trade_date": d.isoformat(),
        "trade_time": None if t is None else t.isoformat("seconds"),
        "security_code": p.get("security_code"),
        "name": p.get("name"),
        "side": p.get("side"),
        "qty": None if qty is None or qty == 0 else fmt_qty(abs(qty)),
        "price": None if p.get("price") is None else fmt_decimal(p["price"], 8),
        "amount": None if p.get("amount") is None else fmt_decimal(abs(p["amount"]), 2),
        "fee_total": fmt_decimal(fees, 2) if any_fee else None,
        "net_amount": None if p.get("net_amount") is None else fmt_decimal(p["net_amount"], 2),
        "biz_type_raw": p.get("biz_type_raw"),
        "event_type": p.get("event_type"),
        # 以下为内部字段（不对外）
        "_qty_signed": None if qty is None else fmt_qty(qty),
        "_commission": _opt(p.get("commission")),
        "_stamp_tax": _opt(p.get("stamp_tax")),
        "_transfer_fee": _opt(p.get("transfer_fee")),
        "_other_fee": _opt(p.get("other_fee")),
        "_balance": _opt(p.get("balance")),
        "_trade_no": p.get("trade_no"),
        "_order_no": p.get("order_no"),
        "_declare_no": p.get("declare_no"),
        "_holder_hmac": p.get("holder_hmac"),
        "_holder_masked": p.get("holder_masked"),
    }


def _opt(v: Decimal | None) -> str | None:
    return None if v is None else format(v, "f")


def _market_for(code: str, ctx: PreviewContext) -> str | None:
    if ctx.securities and code in ctx.securities:
        return ctx.securities[code].exchange
    return infer_market(code)


def _is_trading_day(d: dt.date, ctx: PreviewContext) -> bool:
    if (
        ctx.trading_days is not None
        and ctx.calendar_range
        and ctx.calendar_range[0] <= d <= ctx.calendar_range[1]
    ):
        return d in ctx.trading_days
    return d.weekday() < 5


def _in_session(d: dt.date, t: dt.time, ctx: PreviewContext) -> bool:
    seg = ctx.market_rules.segment_for(d) if ctx.market_rules else None
    if seg is None:
        windows = [(dt.time(9, 15), dt.time(11, 30)), (dt.time(13, 0), dt.time(15, 0))]
    else:
        s = seg.sessions
        windows = [(s.call_auction[0], s.morning[1]), (s.afternoon[0], s.closing_auction[1])]
    return any(a <= t <= b for a, b in windows)


def _lot_ok(code: str, qty: Decimal, d: dt.date, ctx: PreviewContext) -> bool:
    seg = ctx.market_rules.segment_for(d) if ctx.market_rules else None
    info = ctx.securities.get(code) if ctx.securities else None
    market = info.exchange if info else infer_market(code)
    board = (info.board if info and info.board else None) or infer_board(code, market)
    buy_lot = seg.lot.buy_lot if seg else 100
    q = abs(qty)
    if board == "star" and (info is None or info.type != "etf"):
        mn, step = (seg.lot.star_min_buy, seg.lot.star_step) if seg else (200, 1)
        return q >= mn and (q - mn) % step == 0
    if board == "bse":
        mn, step = (seg.lot.bse_min_buy, seg.lot.bse_step) if seg else (100, 1)
        return q >= mn and (q - mn) % step == 0
    return q % buy_lot == 0


def _row_warnings(
    rows: list[RowResult], parsed: dict[int, dict[str, Any]], ctx: PreviewContext
) -> None:
    for r in rows:
        if r.has_error or r.normalized is None or r.kind != "trade":
            continue
        p = parsed[r.row_no]
        code: str = p["security_code"]
        side = p["side"]
        if p.get("net_amount") is not None:
            sign = Decimal(-1) if side == "buy" else Decimal(1)
            expected = sign * abs(p["amount"]) - _sum_fees(p)
            diff = abs(p["net_amount"] - expected)
            if diff > NET_TOLERANCE:
                r.findings.append(
                    _mk(
                        ctx,
                        "IMPORT_NET_AMOUNT_MISMATCH",
                        row_no=r.row_no,
                        field="net_amount",
                        diff=fmt_decimal(diff, 2),
                    )
                )
        info = ctx.securities.get(code) if ctx.securities else None
        if ctx.securities is not None and info is None:
            r.findings.append(_mk(ctx, "IMPORT_UNKNOWN_SECURITY", row_no=r.row_no, code=code))
        if info is not None and p.get("name") and _norm_name(p["name"]) != _norm_name(info.name):
            r.findings.append(
                _mk(
                    ctx,
                    "IMPORT_NAME_MISMATCH",
                    row_no=r.row_no,
                    field="name",
                    name_raw=p["name"],
                    name=info.name,
                )
            )
        hm = p.get("holder_market")
        cm = info.exchange if info else infer_market(code)
        if hm and cm and cm in {"SH", "SZ"} and hm != cm:
            r.findings.append(_mk(ctx, "IMPORT_MARKET_INFERRED_CONFLICT", row_no=r.row_no))
        d: dt.date = p["trade_date"]
        if not _is_trading_day(d, ctx):
            r.findings.append(
                _mk(ctx, "IMPORT_NON_TRADING_DAY", row_no=r.row_no, date=d.isoformat())
            )
        t = p.get("trade_time")
        if t is not None and not _in_session(d, t, ctx):
            r.findings.append(
                _mk(ctx, "IMPORT_TIME_OUTSIDE_SESSION", row_no=r.row_no, field="trade_time")
            )
        if side == "buy" and not _lot_ok(code, p["qty"], d, ctx):
            r.findings.append(_mk(ctx, "IMPORT_LOT_SIZE_IRREGULAR", row_no=r.row_no, field="qty"))


def _norm_name(s: str) -> str:
    return re.sub(r"\s+", "", to_halfwidth(s)).upper()


def _choice(r: RowResult, code: str) -> str | None:
    for f in r.findings:
        if f["code"] == code:
            return F.effective_choice(f)
    return None


def _dedup(rows: list[RowResult], parsed: dict[int, dict[str, Any]], ctx: PreviewContext) -> None:
    seen: dict[str, int] = {}
    occurrences: dict[str, int] = defaultdict(int)
    acc = ctx.account_id
    for r in rows:
        if r.has_error or r.normalized is None:
            continue
        p = parsed[r.row_no]
        if r.kind == "event":
            base = _h(
                acc,
                "event",
                p["trade_date"],
                p.get("security_code"),
                p["event_type"],
                _opt(p.get("net_amount")),
                _opt(p.get("qty")),
                p.get("trade_no"),
                p.get("order_no"),
            )
            occurrences[base] += 1
            r.dedup_key = f"{base}#{occurrences[base]}"
            continue
        code = p["security_code"]
        market = _market_for(code, ctx)
        d = p["trade_date"]
        rule3 = False
        if p.get("trade_no"):
            key = _h(acc, d, market, p["trade_no"])
        elif p.get("order_no"):
            key = _h(acc, d, market, p["order_no"], p["side"], code)
        else:
            t = p.get("trade_time")
            traded_at = f"{d}T{t.isoformat('seconds') if t else ''}"
            base = _h(
                acc,
                traded_at,
                code,
                p["side"],
                _opt(abs(p["qty"])),
                _opt(p["price"].normalize()),
                _opt(abs(p["amount"])),
                _opt(p.get("net_amount")),
            )
            occurrences[base] += 1
            key = f"{base}#{occurrences[base]}"
            rule3 = True
        r.dedup_key = key
        if not rule3 and key in seen:
            f = _mk(ctx, "IMPORT_DUPLICATE_IN_FILE", row_no=r.row_no, other_row_no=seen[key])
            r.findings = [f]
            r.dedup_status = "duplicate_in_file"
            continue
        seen.setdefault(key, r.row_no)
        if key in ctx.existing_keys:
            r.findings.insert(
                0,
                _mk(
                    ctx, "IMPORT_DUPLICATE_IN_DB", row_no=r.row_no, batch_id=ctx.existing_keys[key]
                ),
            )
            r.findings = [f for f in r.findings if f["code"] == "IMPORT_DUPLICATE_IN_DB"]
            r.dedup_status = "duplicate_in_db"
            continue
        weak = weak_fingerprint(acc, d, code, p["side"], abs(p["qty"]), p["price"])
        if weak in ctx.manual_fingerprints:
            r.findings.append(
                _mk(
                    ctx,
                    "IMPORT_POSSIBLE_DUPLICATE_OF_MANUAL",
                    row_no=r.row_no,
                    trade_id=ctx.manual_fingerprints[weak],
                )
            )
            r.dedup_status = "possible_duplicate_of_manual"
            continue
        r.dedup_status = "new"


def weak_fingerprint(
    account_id: str, d: dt.date, code: str, side: str, qty: Decimal, price: Decimal
) -> str:
    return _h(account_id, d, code, side, _opt(abs(qty).normalize()), _opt(price.normalize()))


def _cash_chain(
    rows: list[RowResult], parsed: dict[int, dict[str, Any]], ctx: PreviewContext
) -> None:
    prev: Decimal | None = None
    for r in rows:
        if r.kind == "ignored" or r.dedup_status == "duplicate_in_file":
            continue
        p = parsed.get(r.row_no)
        if p is None:
            continue
        bal, net = p.get("balance"), p.get("net_amount")
        if bal is None:
            continue
        if prev is not None and net is not None and not r.has_error:
            diff = bal - (prev + net)
            if abs(diff) > CHAIN_TOLERANCE:
                r.findings.append(
                    _mk(
                        ctx,
                        "IMPORT_CASH_CHAIN_BREAK",
                        row_no=r.row_no,
                        field="balance",
                        diff=fmt_decimal(diff, 2),
                    )
                )
        prev = bal


def written_by_default(r: RowResult) -> bool:
    """确认时（valid_rows_only）是否写入：无 error、非跳过、各提示的处理不是“跳过”。"""
    if r.has_error or r.kind == "ignored" or r.normalized is None:
        return False
    if r.kind == "snapshot_position":
        return True
    if r.dedup_status in {"duplicate_in_db", "duplicate_in_file"}:
        return (
            _choice(
                r,
                "IMPORT_DUPLICATE_IN_DB"
                if r.dedup_status == "duplicate_in_db"
                else "IMPORT_DUPLICATE_IN_FILE",
            )
            == "force_import"
        )
    if (
        r.dedup_status == "possible_duplicate_of_manual"
        and _choice(r, "IMPORT_POSSIBLE_DUPLICATE_OF_MANUAL") != "keep_import_void_manual"
    ):
        return False
    return _choice(r, "IMPORT_UNKNOWN_SECURITY") != "skip_row"


def _missing_opening(
    rows: list[RowResult], parsed: dict[int, dict[str, Any]], ctx: PreviewContext
) -> None:
    events: list[tuple[dt.date, str, int, int, str, Decimal, RowResult | None]] = []
    for d0, t0, code0, delta0 in ctx.ledger:
        events.append((d0, t0, 0, 0, code0, delta0, None))
    for r in rows:
        if not written_by_default(r):
            continue
        p = parsed[r.row_no]
        code = p.get("security_code")
        if not code:
            continue
        t = p.get("trade_time")
        ts = t.isoformat("seconds") if t else ""
        if r.kind == "trade":
            q = abs(p["qty"])
            delta = q if p["side"] == "buy" else -q
        elif (
            r.kind == "event"
            and p.get("event_type")
            in {"ipo_allot", "bonus_share", "rights", "transfer_in", "transfer_out"}
            and p.get("qty")
        ):
            q = abs(p["qty"])
            delta = -q if p["event_type"] == "transfer_out" else q
        else:
            continue
        events.append(
            (p["trade_date"], ts, 1, r.row_no, code, delta, r if r.kind == "trade" else None)
        )
    events.sort(key=lambda e: (e[0], e[1], e[2], e[3]))
    pos: dict[str, Decimal] = defaultdict(Decimal)
    for _d, _t, _src, _no, code, delta, row in events:
        if delta < 0 and row is not None and pos[code] < -delta:
            row.findings.append(_mk(ctx, "IMPORT_MISSING_OPENING_POSITION", row_no=row.row_no))
        pos[code] = max(Decimal(0), pos[code] + delta)
    for r in rows:
        r.findings.sort(key=_finding_order)


_ORDER: Final = {
    "IMPORT_DUPLICATE_IN_DB": 0,
    "IMPORT_DUPLICATE_IN_FILE": 0,
    "IMPORT_MISSING_OPENING_POSITION": 5,
    "IMPORT_CASH_CHAIN_BREAK": 6,
}


def _finding_order(f: dict[str, Any]) -> int:
    return _ORDER.get(f["code"], 1)


def _holder_mismatch(holders: set[tuple[str, str]], ctx: PreviewContext) -> bool:
    for market, hm in holders:
        reg = ctx.registered_holders.get(market)
        if reg and hm not in reg:
            return True
    return False


# ---------------------------------------------------------------------------
# 资金持仓快照
# ---------------------------------------------------------------------------

_SUMMARY_RE: Final = re.compile(r"(\S+?)[:：]\s*(\S+)")
_SUMMARY_KEYS: Final = {
    "余额": "cash_balance",
    "可用": "cash_available",
    "可取": "cash_withdrawable",
    "参考市值": "market_value_ref",
    "资产": "total_assets_ref",
    "盈亏": "pnl_ref",
}


def _parse_summary(pre: list[DecodedLine]) -> list[tuple[str, dict[str, Decimal | None]]]:
    """表头前的资金摘要行：``人民币: 余额:x  可用:x ...``（每币种一行）。"""
    out: list[tuple[str, dict[str, Decimal | None]]] = []
    for ln in pre:
        if ln.text is None:
            continue
        m = re.match(r"\s*(\S+?)[:：]\s*(.*)$", to_halfwidth(ln.text))
        if m is None or m.group(1) not in CURRENCY_WORDS:
            continue
        vals: dict[str, Decimal | None] = {}
        for k, val in _SUMMARY_RE.findall(m.group(2)):
            if k in _SUMMARY_KEYS:
                vals[_SUMMARY_KEYS[k]] = _num(val)
        out.append((m.group(1), vals))
    return out


def _position_rows(
    rows: list[RowResult],
    ctx: PreviewContext,
    pre: list[DecodedLine],
    file_findings: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, bool]:
    holders: set[tuple[str, str]] = set()
    summaries = _parse_summary(pre)
    cny: dict[str, Decimal | None] = {}
    for label, vals in summaries:
        cur = CURRENCY_WORDS.get(label, label)
        if cur == "CNY":
            cny = vals
        else:
            file_findings.append(_mk(ctx, "IMPORT_UNSUPPORTED_CURRENCY", currency=label))
    items_mv = Decimal(0)
    items_pnl = Decimal(0)
    for r in rows:
        if r.normalized is None:
            continue
        v: dict[str, str] = r.normalized["_values"]
        r.normalized = None
        p = _validate_basic(
            r,
            v,
            ctx,
            required=("security_code", "qty"),
            numeric=(
                "qty",
                "sellable_qty",
                "cost_price",
                "last_price",
                "market_value",
                "pnl",
                "pnl_pct",
            ),
            has_date=False,
        )
        holder = to_halfwidth(v.get("holder", "")).strip()
        hm = hmk = None
        if holder and holder != "0":
            hm, hmk = ctx.holder_hmac(holder), holder_masked(holder)
            mk = holder_market(holder)
            if mk:
                holders.add((mk, hm))
        if r.has_error:
            continue
        code = p["security_code"]
        info = ctx.securities.get(code) if ctx.securities else None
        name = v.get("name", "").strip() or None
        if ctx.securities is not None and info is None:
            r.findings.append(_mk(ctx, "IMPORT_UNKNOWN_SECURITY", row_no=r.row_no, code=code))
        if info is not None and name and _norm_name(name) != _norm_name(info.name):
            r.findings.append(
                _mk(
                    ctx,
                    "IMPORT_NAME_MISMATCH",
                    row_no=r.row_no,
                    field="name",
                    name_raw=name,
                    name=info.name,
                )
            )
        items_mv += p.get("market_value") or Decimal(0)
        items_pnl += p.get("pnl") or Decimal(0)
        r.normalized = {
            "security_code": code,
            "name": name,
            "qty": fmt_qty(p["qty"]),
            "sellable_qty": None if p.get("sellable_qty") is None else fmt_qty(p["sellable_qty"]),
            "cost_price": None if p.get("cost_price") is None else fmt_decimal(p["cost_price"], 4),
            "last_price": None if p.get("last_price") is None else fmt_decimal(p["last_price"], 4),
            "market_value": None
            if p.get("market_value") is None
            else fmt_decimal(p["market_value"], 2),
            "pnl": None if p.get("pnl") is None else fmt_decimal(p["pnl"], 2),
            "pnl_pct": None if p.get("pnl_pct") is None else format(p["pnl_pct"], "f"),
            "_holder_hmac": hm,
            "_holder_masked": hmk,
        }
    snapshot = {k: _opt(v) for k, v in cny.items()} | {"currency": "CNY"}
    bal, mv, assets = (
        cny.get("cash_balance"),
        cny.get("market_value_ref"),
        cny.get("total_assets_ref"),
    )
    mismatch = False
    if (
        bal is not None
        and mv is not None
        and assets is not None
        and abs(bal + mv - assets) > TOTALS_TOLERANCE
    ):
        mismatch = True
    if mv is not None and abs(items_mv - mv) > TOTALS_TOLERANCE:
        mismatch = True
    if mismatch:
        file_findings.append(_mk(ctx, "IMPORT_SNAPSHOT_TOTALS_MISMATCH"))
    return snapshot, _holder_mismatch(holders, ctx)
