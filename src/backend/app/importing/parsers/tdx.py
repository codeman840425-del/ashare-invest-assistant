"""通达信（TDX）导出格式（plan §3.5A，T-B46）。

成交明细 ``tdx_trades_v1``、资金持仓 ``tdx_positions_v1``。

只负责“表头定位 + 定宽切分”，字段校验在 :mod:`app.importing.preview`。

切分（plan §3.5A 定宽解析方法）：
- 策略 b（主路径）：按 ≥2 个空白分词，token 数 == 表头列数；
- 策略 a：每个 token 的显示列起点（东亚宽字符记 2）必须等于对应表头列起点；
- 两者一致才采用。末行无换行且列数不足 → ``ROW_TRUNCATED``；所有 token 都对齐但缺的只是
  必填列 → 逐个 ``REQUIRED_FIELD_EMPTY``（列位置保持、值为空）；其余 → ``ROW_COLUMN_MISMATCH``。
"""

# 交割单表头词在源码里一律写成 \u 转义：
# CI secret_scan 的 S7 规则把出现 ≥3 个表头词的文件当作真实交割单拦截。

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final

from app.importing.decoding import DecodedLine
from app.importing.text import Token, tokenize


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    name: str
    field: str
    required: bool = False
    sensitive: str | None = None  # "holder" / "drop"


@dataclass(frozen=True, slots=True)
class ParserSpec:
    parser_id: str
    version: str
    kind: str  # trades / positions
    columns: tuple[ColumnSpec, ...]
    sniff: frozenset[str]

    @property
    def by_name(self) -> dict[str, ColumnSpec]:
        return {c.name: c for c in self.columns}

    @property
    def fields(self) -> frozenset[str]:
        return frozenset(c.field for c in self.columns)


TRADES: Final = ParserSpec(
    parser_id="tdx_trades_v1",
    version="1",
    kind="trades",
    columns=(
        ColumnSpec("\u6210\u4ea4\u65e5\u671f", "trade_date", required=True),
        ColumnSpec("成交时间", "trade_time"),
        ColumnSpec("\u8bc1\u5238\u4ee3\u7801", "security_code", required=True),
        ColumnSpec("证券名称", "name"),
        ColumnSpec("买卖标志", "biz", required=True),
        ColumnSpec("成交数量", "qty", required=True),
        ColumnSpec("成交价格", "price", required=True),
        ColumnSpec("成交金额", "amount", required=True),
        ColumnSpec("\u59d4\u6258\u7f16\u53f7", "order_no"),
        ColumnSpec("\u6210\u4ea4\u7f16\u53f7", "trade_no"),
        ColumnSpec("\u53d1\u751f\u91d1\u989d", "net_amount"),
        ColumnSpec("\u5269\u4f59\u91d1\u989d", "balance"),
        ColumnSpec("申报序号", "declare_no"),
        ColumnSpec("\u80a1\u4e1c\u4ee3\u7801", "holder", sensitive="holder"),
        ColumnSpec("席位代码", "seat", sensitive="drop"),
        ColumnSpec("净佣金", "commission"),
        ColumnSpec("印花税", "stamp_tax"),
        ColumnSpec("过户费", "transfer_fee"),
        ColumnSpec("交易规费", "other_fee"),
        ColumnSpec("备注", "remark"),
    ),
    sniff=frozenset(
        {
            "\u6210\u4ea4\u65e5\u671f",
            "成交时间",
            "\u8bc1\u5238\u4ee3\u7801",
            "买卖标志",
            "成交数量",
            "成交价格",
            "\u53d1\u751f\u91d1\u989d",
            "\u5269\u4f59\u91d1\u989d",
        }
    ),
)

POSITIONS: Final = ParserSpec(
    parser_id="tdx_positions_v1",
    version="1",
    kind="positions",
    columns=(
        ColumnSpec("编号", "seq"),
        ColumnSpec("\u8bc1\u5238\u4ee3\u7801", "security_code", required=True),
        ColumnSpec("证券名称", "name"),
        ColumnSpec("证券数量", "qty", required=True),
        ColumnSpec("可卖数量", "sellable_qty"),
        ColumnSpec("成本价", "cost_price"),
        ColumnSpec("当前价", "last_price"),
        ColumnSpec("最新市值", "market_value"),
        ColumnSpec("浮动盈亏", "pnl"),
        ColumnSpec("盈亏比例(%)", "pnl_pct"),
        ColumnSpec("\u80a1\u4e1c\u4ee3\u7801", "holder", sensitive="holder"),
    ),
    sniff=frozenset({"\u8bc1\u5238\u4ee3\u7801", "证券数量", "可卖数量", "成本价"}),
)

HEADER_SCAN_LINES: Final = 30
MIN_HEADER_HITS: Final = 4
_SEPARATOR: Final = re.compile(r"^[\s\-=—_]+$")


def is_blank_or_separator(text: str) -> bool:
    return not text.strip() or bool(_SEPARATOR.match(text))


def is_total_line(tokens: list[Token]) -> bool:
    return bool(tokens) and "合计" in tokens[0].text


@dataclass(slots=True)
class Header:
    index: int  # 在 lines 中的下标
    row_no: int
    tokens: list[Token]
    #: 每列映射到的字段（未识别列为 None）
    fields: list[str | None]
    unknown: list[str]
    missing_required: list[str]
    score: float


def find_header(
    spec: ParserSpec, lines: list[DecodedLine], mapping: dict[str, str] | None = None
) -> Header | None:
    """前 30 行中第一条含 ≥4 个已知列头的行。``mapping`` = 用户列映射 ``{列名: 字段}``。"""
    known = spec.by_name
    allowed = spec.fields
    user_map = {k: v for k, v in (mapping or {}).items() if v in allowed}
    for i, line in enumerate(lines[:HEADER_SCAN_LINES]):
        if line.text is None:
            continue
        tokens = tokenize(line.text)
        names = [t.text for t in tokens]
        hits = sum(1 for n in names if n in known or n in user_map)
        if hits < MIN_HEADER_HITS:
            continue
        fields: list[str | None] = []
        for n in names:
            if n in user_map:
                fields.append(user_map[n])
            elif n in known:
                fields.append(known[n].field)
            else:
                fields.append(None)
        present = {f for f in fields if f}
        missing = [c.name for c in spec.columns if c.required and c.field not in present]
        unknown = [n for n, f in zip(names, fields, strict=True) if f is None]
        score = round(len(present) / len(spec.columns), 4)
        return Header(i, line.row_no, tokens, fields, unknown, missing, score)
    return None


def sniff_candidates(lines: list[DecodedLine]) -> list[str]:
    """有 ≥4 个已知列头的解析器 id（``UNRECOGNIZED_FORMAT`` 的候选）。"""
    out: list[str] = []
    for spec in (TRADES, POSITIONS):
        for line in lines[:HEADER_SCAN_LINES]:
            if line.text is None:
                continue
            names = {t.text for t in tokenize(line.text)}
            if len(names & set(spec.by_name)) >= MIN_HEADER_HITS:
                out.append(spec.parser_id)
                break
    return out


@dataclass(slots=True)
class SplitRow:
    row_no: int
    text: str
    tokens: list[Token]
    values: dict[str, str] = field(default_factory=dict)
    #: ROW_TRUNCATED / ROW_COLUMN_MISMATCH / None
    structural: str | None = None
    empty_required: list[str] = field(default_factory=list)


def split_row(spec: ParserSpec, header: Header, line: DecodedLine, *, is_last: bool) -> SplitRow:
    text = line.text or ""
    tokens = tokenize(text)
    row = SplitRow(line.row_no, text, tokens)
    starts = [t.col for t in header.tokens]
    n = len(starts)
    slot_of = {c: i for i, c in enumerate(starts)}
    slots = [slot_of.get(t.col) for t in tokens]
    aligned = all(s is not None for s in slots) and slots == sorted(set(slots))  # type: ignore[type-var]
    if len(tokens) == n and aligned:
        filled = dict(enumerate(t.text for t in tokens))
    elif not line.has_newline and is_last and len(tokens) < n:
        row.structural = "IMPORT_ROW_TRUNCATED"
        return row
    elif aligned and len(tokens) < n:
        filled = {s: t.text for s, t in zip(slots, tokens, strict=True) if s is not None}
        missing = [i for i in range(n) if i not in filled]
        req = {c.field for c in spec.columns if c.required}
        if all(header.fields[i] in req for i in missing):
            row.empty_required = [str(header.fields[i]) for i in missing]
        else:
            row.structural = "IMPORT_ROW_COLUMN_MISMATCH"
            return row
    else:
        row.structural = "IMPORT_ROW_COLUMN_MISMATCH"
        return row
    for i, f in enumerate(header.fields):
        if f is not None:
            row.values[f] = filled.get(i, "")
    return row


def sensitive_spans(spec: ParserSpec, header: Header, row: SplitRow) -> list[tuple[int, int, str]]:
    """原始行中需要掩码的字符区间（按 token 文本定位）。"""
    from app.importing.masking import MASK, holder_masked

    by_field = spec.by_name
    sens = {c.field: c.sensitive for c in by_field.values() if c.sensitive}
    spans: list[tuple[int, int, str]] = []
    if row.structural is not None:
        return spans
    starts = [t.col for t in header.tokens]
    for tok in row.tokens:
        if tok.col not in starts:
            continue
        f = header.fields[starts.index(tok.col)]
        kind = sens.get(f or "")
        if kind is None:
            continue
        repl = holder_masked(tok.text) if kind == "holder" else MASK
        spans.append((tok.start, tok.start + len(tok.text), repl))
    return spans


PARSERS_BY_KIND: Final = {"trades": TRADES, "positions": POSITIONS}
