"""通达信本地 .day / .lc1 / .lc5 只读解析、sha256 清单与导入规划（T-B133）。

契约只读参照：``git show 362ad41:docs/contracts/daily-bars-tdx.md`` §2–§5 与
``git show 362ad41:docs/contracts/intraday-bars.md`` §1.2–§1.3、§2.2。

本模块只做离线文件读取与纯计算：不出网，不 import 任何 egress / transport，不连库。
库读写由 ``app.cli.tdx_import`` 注入（取证券主数据、已有行、写入器）。参数出处见
``reports/T-B133.md`` 的参数出处表；没有出处的参数不在这里生效。
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import logging
import math
import os
import re
import struct
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence, Set
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final, Literal
from zoneinfo import ZoneInfo

from app.db.base import MONEY

logger = logging.getLogger("app.ingest.tdx_local")

BEIJING: Final = ZoneInfo("Asia/Shanghai")

# daily-bars-tdx §3.3「每条 32 字节，小端 <IIIIIfII」；intraday-bars §1.2「每条 32 字节，小端」。
RECORD_SIZE: Final[int] = 32
DAY_LAYOUT: Final = struct.Struct("<IIIIIfII")
# intraday-bars §1.2：2 字节日期 + 2 字节分钟 + 5×float32（OHLC、额）+ 整数量 + 4 字节保留。
LC_LAYOUT: Final = struct.Struct("<HHfffffII")
if DAY_LAYOUT.size != RECORD_SIZE or LC_LAYOUT.size != RECORD_SIZE:
    raise RuntimeError("tdx record layout must be 32 bytes")

# daily-bars-tdx §2「价格：股票为整数 ÷100，到分」。
DAY_PRICE_DIVISOR: Final = Decimal(100)
# intraday-bars §1.2 分钟日期编码；T-B133 用真实样本与 .day 交叉核对（日期全部命中）。
LC_YEAR_BASE: Final[int] = 2004
LC_YEAR_SPAN: Final[int] = 2048
# 分钟价为 float32 元；入库按股票价格位数（app.marketdata.security_types.STOCK_PRICE_DP=2）取整。
LC_PRICE_Q: Final = Decimal("0.01")
_MONEY_Q: Final = Decimal("0.0001")  # 与 market 表 Numeric(20,4) 一致
# 裁定②：写库列 MONEY（Numeric(20,4)）可容纳的整数位，取自类型本身，不另设阈值。
if MONEY.precision is None or MONEY.scale is None:
    raise RuntimeError("MONEY must declare precision and scale")
_MONEY_INT_DIGITS: Final[int] = MONEY.precision - MONEY.scale
# daily-bars-tdx §3.3 单位自检：额÷量落在 [low, high]（容差 1%），超 5% 整文件拒绝。
UNIT_TOLERANCE: Final = 0.01
UNIT_REJECT_RATIO: Final = 0.05
# daily-bars-tdx §5 金额容差：|差| ≤ max(1 元, |麦蕊值| × 2.4e-7)。
AMOUNT_ABS_TOL: Final = Decimal(1)
AMOUNT_REL_TOL: Final = Decimal("2.4e-7")

Kind = Literal["day", "lc1", "lc5"]
MARKETS: Final[tuple[str, ...]] = ("sh", "sz", "bj")
# daily-bars-tdx §3.2 / intraday-bars §1.2：lday（日线）、minline（.lc1）、fzline（.lc5）。
KIND_DIR: Final[dict[str, str]] = {"day": "lday", "lc1": "minline", "lc5": "fzline"}
KIND_SUFFIX: Final[dict[str, str]] = {"day": ".day", "lc1": ".lc1", "lc5": ".lc5"}
LC_BAR_MINUTES: Final[dict[str, int]] = {"lc1": 1, "lc5": 5}
_NAME_RE: Final = re.compile(r"^(sh|sz|bj)(\d{6})\.(day|lc1|lc5)$", re.IGNORECASE)
MANIFEST_PREFIX: Final[str] = "tdx-{kind}-manifest-"
_MANIFEST_RE: Final = re.compile(r"^tdx-(day|lc1|lc5)-manifest-\d{8}T\d{6}-[0-9a-z]+\.txt$")

# 按原因的跳过计数键（daily-bars-tdx §3.3 第 1 步）。
SKIP_NOT_TARGET: Final = "not_target_file"
SKIP_NAME_INVALID: Final = "name_invalid"
SKIP_NORMALIZE: Final = "normalize_failed"
SKIP_NON_A_SHARE: Final = "non_a_share"
SKIP_NOT_LISTED: Final = "not_listed"
SKIP_OUT_OF_SCOPE: Final = "out_of_scope"
REJECT_NON_FINITE: Final = "non_finite"
REJECT_OUT_OF_RANGE: Final = "out_of_range"


class TdxRefused(Exception):  # noqa: N818 - 契约用语「拒绝」
    """整次运行拒绝（零写入，退出码非 0）。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class TdxBar:
    """一根通达信 K 线；日线 ts 为 None，分钟线 ts 为北京时间 bar 结束时刻。"""

    code: str
    trade_date: dt.date
    ts: dt.datetime | None
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    amount: Decimal


@dataclass
class ParseResult:
    bars: list[TdxBar] = field(default_factory=list)
    rejected: Counter[str] = field(default_factory=Counter)


@dataclass(frozen=True)
class Candidate:
    code: str
    market: str
    rel: str  # 相对 --root 的 posix 路径（清单与报告只写它，不写宿主路径）
    path: Path


@dataclass
class ScanResult:
    files: list[Candidate] = field(default_factory=list)
    skipped: Counter[str] = field(default_factory=Counter)


@dataclass(frozen=True)
class ManifestEntry:
    sha256: str
    size: int
    rel: str


@dataclass(frozen=True)
class Manifest:
    entries: tuple[ManifestEntry, ...]
    text: str
    sha256: str


# ---------------------------------------------------------------- 记录解析


def _quantize(value: float, q: Decimal) -> Decimal | None:
    """量化 float32 值；量化报错或超出写库列 MONEY 的整数位时返回 None（裁定②，按记录拒绝）。

    「极大」只以实际会不会出错为准：Decimal 默认精度下 quantize 抛 InvalidOperation，或整数位
    超过 ``MONEY``（Numeric(20,4)，market 各 K 线表价/额列）的 precision - scale；不另设阈值。
    """
    try:
        result = Decimal(repr(float(value))).quantize(q)
    except InvalidOperation:
        return None
    if result.adjusted() + 1 > _MONEY_INT_DIGITS:
        return None
    return result


def decode_lc_date(value: int) -> dt.date:
    """intraday-bars §1.2：年 = 值 // 2048 + 2004；余数 // 100 为月，余数 % 100 为日。"""
    rest = value % LC_YEAR_SPAN
    return dt.date(value // LC_YEAR_SPAN + LC_YEAR_BASE, rest // 100, rest % 100)


def encode_lc_date(day: dt.date) -> int:
    return (day.year - LC_YEAR_BASE) * LC_YEAR_SPAN + day.month * 100 + day.day


def _bar(
    code: str,
    day: dt.date,
    ts: dt.datetime | None,
    prices: Sequence[Decimal],
    volume: int,
    amount: Decimal,
) -> TdxBar:
    o, h, low, c = prices
    return TdxBar(code, day, ts, o, h, low, c, Decimal(volume), amount)


def _valid_ohlc(o: Decimal, h: Decimal, low: Decimal, c: Decimal) -> str | None:
    if min(o, h, low, c) <= 0:
        return "zero_price"
    if not (low <= min(o, c) and max(o, c) <= h):
        return "high_low_conflict"
    return None


def parse_day_bytes(code: str, data: bytes) -> ParseResult:
    """daily-bars-tdx §3.3：日期非法、高低价矛盾、价格为 0 的记录拒绝并计数。"""
    out = ParseResult()
    if len(data) % RECORD_SIZE:
        out.rejected["truncated_file"] += 1
        return out
    for raw_date, o, h, low, c, amount, volume, _r in DAY_LAYOUT.iter_unpack(data):
        try:
            day = dt.datetime.strptime(f"{raw_date:08d}", "%Y%m%d").date()
        except ValueError:
            out.rejected["invalid_date"] += 1
            continue
        if not math.isfinite(amount):  # T-A147 M2：float32 NaN/Inf 按记录拒绝
            out.rejected[REJECT_NON_FINITE] += 1
            continue
        quantized_amount = _quantize(amount, _MONEY_Q)
        if quantized_amount is None:
            out.rejected[REJECT_OUT_OF_RANGE] += 1
            continue
        prices = [Decimal(x) / DAY_PRICE_DIVISOR for x in (o, h, low, c)]
        bad = _valid_ohlc(*prices)
        if bad:
            out.rejected[bad] += 1
            continue
        out.bars.append(_bar(code, day, None, prices, volume, quantized_amount))
    return out


def parse_lc_bytes(code: str, data: bytes, kind: Kind) -> ParseResult:
    """.lc1 / .lc5：分钟数为当日零点起、bar 结束时刻（T-B133 真实样本核对：首根 09:31/09:35）。"""
    if kind not in LC_BAR_MINUTES:
        raise ValueError("kind must be lc1 or lc5")
    out = ParseResult()
    if len(data) % RECORD_SIZE:
        out.rejected["truncated_file"] += 1
        return out
    for raw_date, minute, o, h, low, c, amount, volume, _r in LC_LAYOUT.iter_unpack(data):
        try:
            day = decode_lc_date(raw_date)
        except ValueError:
            out.rejected["invalid_date"] += 1
            continue
        if not 0 < minute <= 24 * 60:
            out.rejected["invalid_minute"] += 1
            continue
        if not all(math.isfinite(x) for x in (o, h, low, c, amount)):  # T-A147 M2
            out.rejected[REJECT_NON_FINITE] += 1
            continue
        quantized_prices = [_quantize(x, LC_PRICE_Q) for x in (o, h, low, c)]
        quantized_amount = _quantize(amount, _MONEY_Q)
        prices = [x for x in quantized_prices if x is not None]
        if len(prices) != len(quantized_prices) or quantized_amount is None:  # 裁定②
            out.rejected[REJECT_OUT_OF_RANGE] += 1
            continue
        bad = _valid_ohlc(*prices)
        if bad:
            out.rejected[bad] += 1
            continue
        end = dt.datetime.combine(day, dt.time(0), BEIJING) + dt.timedelta(minutes=minute)
        out.bars.append(_bar(code, day, end, prices, volume, quantized_amount))
    return out


def unit_suspect(bars: Sequence[TdxBar]) -> bool:
    """daily-bars-tdx §3.3：额÷量须落在 [low, high]（容差 1%）；不满足比例 > 5% 为可疑。"""
    checked = bad = 0
    tol = Decimal(repr(UNIT_TOLERANCE))
    for bar in bars:
        if bar.volume <= 0:
            continue
        checked += 1
        avg = bar.amount / bar.volume
        if not (bar.low * (1 - tol) <= avg <= bar.high * (1 + tol)):
            bad += 1
    return checked > 0 and bad / checked > UNIT_REJECT_RATIO


# ---------------------------------------------------------------- 扫描与过滤


def _child_ci(parent: Path, name: str) -> Path | None:
    """目录名大小写不敏感匹配（daily-bars-tdx §3.5）。"""
    if not parent.is_dir():
        return None
    for child in sorted(parent.iterdir()):
        if child.is_dir() and child.name.lower() == name:
            return child
    return None


def kind_dirs(root: Path, kind: Kind, exclude: Set[str] = frozenset()) -> dict[str, Path]:
    """--root 下未排除市场须有 <kind 目录>，缺任一即拒绝（daily-bars-tdx §3.3）。"""
    found: dict[str, Path] = {}
    sub = KIND_DIR[kind]
    for market in MARKETS:
        if market in exclude:
            continue
        mdir = _child_ci(root, market)
        kdir = _child_ci(mdir, sub) if mdir is not None else None
        if kdir is None:
            raise TdxRefused(f"root_missing:{market}/{sub}")
        found[market] = kdir
    return found


SecurityOf = Callable[[str], "tuple[str, str | None] | None"]


def scan(
    root: Path,
    kind: Kind,
    *,
    normalize: Callable[[str], str],
    security_of: SecurityOf,
    scope_codes: frozenset[str] | None,
    exclude: Set[str] = frozenset(),
) -> ScanResult:
    """只列目录、看文件名，被过滤的文件不打开、不算哈希。"""
    result = ScanResult()
    suffix = KIND_SUFFIX[kind]
    for market, kdir in kind_dirs(root, kind, exclude=exclude).items():
        for entry in sorted(kdir.iterdir(), key=lambda p: p.name):
            if not entry.is_file() or not entry.name.lower().endswith(suffix):
                result.skipped[SKIP_NOT_TARGET] += 1
                continue
            m = _NAME_RE.match(entry.name)
            if m is None or m.group(1).lower() != market:
                result.skipped[SKIP_NAME_INVALID] += 1
                continue
            try:
                code = normalize(m.group(1).upper() + m.group(2))
            except Exception:  # noqa: BLE001 - 规范化失败只计数
                result.skipped[SKIP_NORMALIZE] += 1
                continue
            info = security_of(code)
            if info is None or info[0] != "stock":
                result.skipped[SKIP_NON_A_SHARE] += 1
                continue
            if info[1] != "listed":
                result.skipped[SKIP_NOT_LISTED] += 1
                continue
            if scope_codes is not None and code not in scope_codes:
                result.skipped[SKIP_OUT_OF_SCOPE] += 1
                continue
            rel = entry.relative_to(root).as_posix()
            result.files.append(Candidate(code=code, market=market, rel=rel, path=entry))
    result.files.sort(key=lambda c: c.rel)
    return result


# ---------------------------------------------------------------- sha256 清单


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(files: Iterable[Candidate], gaps: Iterable[str] = ()) -> Manifest:
    """每行「sha256、字节数、相对路径」（制表符分隔），末行为文件数与清单自身 sha256。"""
    entries = tuple(ManifestEntry(file_sha256(c.path), c.path.stat().st_size, c.rel) for c in files)
    body = "".join(f"{e.sha256}\t{e.size}\t{e.rel}\n" for e in entries)
    body += "".join(f"gap\t{rel}\texcluded_by_scope\n" for rel in gaps)
    own = hashlib.sha256(body.encode("utf-8")).hexdigest()
    text = body + f"files={len(entries)}\tmanifest_sha256={own}\n"
    return Manifest(entries=entries, text=text, sha256=own)


def parse_manifest(text: str) -> Manifest | None:
    lines = text.splitlines(keepends=True)
    if not lines:
        return None
    body = "".join(lines[:-1])
    tail = lines[-1].rstrip("\n").split("\t")
    own = hashlib.sha256(body.encode("utf-8")).hexdigest()
    if len(tail) != 2 or tail[1] != f"manifest_sha256={own}":
        return None
    entries = []
    for line in lines[:-1]:
        parts = line.rstrip("\n").split("\t")
        if len(parts) != 3:
            return None
        if parts[0] == "gap":
            continue
        entries.append(ManifestEntry(parts[0], int(parts[1]), parts[2]))
    if tail[0] != f"files={len(entries)}":
        return None
    return Manifest(entries=tuple(entries), text=text, sha256=own)


def compare_manifests(previous: Manifest, current: Manifest) -> dict[str, int]:
    """复跑比对：新增、删除、变化的文件数（变化不算错误，daily-bars-tdx §3.3 第 3 步）。"""
    old = {e.rel: e for e in previous.entries}
    new = {e.rel: e for e in current.entries}
    return {
        "added": len(new.keys() - old.keys()),
        "removed": len(old.keys() - new.keys()),
        "changed": sum(
            1
            for rel in new.keys() & old.keys()
            if (new[rel].sha256, new[rel].size) != (old[rel].sha256, old[rel].size)
        ),
    }


def check_audit_dir(root: Path, audit_dir: Path) -> Path:
    """--audit-dir 须存在、可写，且不在 --root 之下（daily-bars-tdx §3.3）。"""
    resolved_root = root.resolve()
    resolved = audit_dir.resolve()
    if resolved == resolved_root or resolved.is_relative_to(resolved_root):
        raise TdxRefused("audit_dir_inside_root")
    if not resolved.is_dir() or not os.access(resolved, os.W_OK | os.X_OK):
        raise TdxRefused("audit_dir_not_writable")
    return resolved


def latest_manifest(audit_dir: Path, kind: Kind) -> tuple[str, Manifest | None] | None:
    names = sorted(
        p.name
        for p in audit_dir.iterdir()
        if p.is_file() and _MANIFEST_RE.match(p.name) and p.name.startswith(f"tdx-{kind}-")
    )
    if not names:
        return None
    name = names[-1]
    return name, parse_manifest((audit_dir / name).read_text(encoding="utf-8"))


def _write_new(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".part")
    with tmp.open("x", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


# ---------------------------------------------------------------- 重叠对账（只读）


@dataclass(frozen=True)
class ExistingBar:
    source: str | None
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    volume: Decimal | None
    amount: Decimal | None


def _amount_tolerance(existing: Decimal) -> Decimal:
    return max(AMOUNT_ABS_TOL, abs(existing) * AMOUNT_REL_TOL)


def reconcile(
    bar: TdxBar, existing: ExistingBar, *, compare_amount: bool
) -> list[dict[str, object]]:
    """daily-bars-tdx §5：OHLC 到分、量完全相等；额按容差。只出差异项，不改任何行。"""
    key_day = bar.trade_date.isoformat()
    items: list[dict[str, object]] = []
    for name in ("open", "high", "low", "close", "volume"):
        theirs = getattr(existing, name)
        ours = getattr(bar, name)
        if theirs is None or Decimal(theirs) != ours:
            items.append(
                {
                    "code": bar.code,
                    "trade_date": key_day,
                    "ts": bar.ts.isoformat() if bar.ts else None,
                    "field": name,
                    "existing_source": existing.source,
                    "existing_value": None if theirs is None else str(theirs),
                    "tdx_value": str(ours),
                    "tolerance": "0",
                    "kind": "mismatch",
                }
            )
    if compare_amount:
        theirs = existing.amount
        if theirs is None or abs(Decimal(theirs) - bar.amount) > _amount_tolerance(Decimal(theirs)):
            items.append(
                {
                    "code": bar.code,
                    "trade_date": key_day,
                    "ts": bar.ts.isoformat() if bar.ts else None,
                    "field": "amount",
                    "existing_source": existing.source,
                    "existing_value": None if theirs is None else str(theirs),
                    "tdx_value": str(bar.amount),
                    "tolerance": str(_amount_tolerance(Decimal(theirs or 0))),
                    "kind": "mismatch",
                }
            )
    return items


# ---------------------------------------------------------------- 一次运行


ExistingLookup = Callable[[str, Sequence[TdxBar]], Mapping[object, ExistingBar]]
Writer = Callable[[Sequence[TdxBar]], int]


def bar_key(bar: TdxBar) -> object:
    return bar.ts if bar.ts is not None else bar.trade_date


@dataclass
class RunReport:
    kind: str
    run_id: str
    apply: bool
    status: str = "ok"
    files: int = 0
    skipped: Counter[str] = field(default_factory=Counter)
    rejected_records: Counter[str] = field(default_factory=Counter)
    rejected_files: Counter[str] = field(default_factory=Counter)
    issues: list[str] = field(default_factory=list)
    parsed_rows: int = 0
    before_from: int = 0
    after_until: int = 0
    overlap_rows: int = 0
    conflicts: int = 0
    would_insert: int = 0
    inserted: int = 0
    manifest_name: str = ""
    manifest_sha256: str = ""
    rerun: dict[str, int] | None = None
    previous_manifest: str | None = None
    reconcile_name: str = ""

    def stats(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "run_id": self.run_id,
            "mode": "apply" if self.apply else "dry-run",
            "status": self.status,
            "files": self.files,
            "skipped": dict(sorted(self.skipped.items())),
            "rejected_records": dict(sorted(self.rejected_records.items())),
            "rejected_files": dict(sorted(self.rejected_files.items())),
            "issues": sorted(set(self.issues)),
            "parsed_rows": self.parsed_rows,
            "before_from": self.before_from,
            "after_until": self.after_until,
            "overlap_rows": self.overlap_rows,
            "conflicts": self.conflicts,
            "would_insert": self.would_insert,
            "inserted": self.inserted,
            "manifest": self.manifest_name,
            "manifest_sha256": self.manifest_sha256,
            "previous_manifest": self.previous_manifest,
            "rerun": self.rerun,
            "reconcile_report": self.reconcile_name,
        }


def run_import(
    *,
    root: Path,
    audit_dir: Path,
    kind: Kind,
    start: dt.date | None,
    until_for: Callable[[str], dt.date | None],
    normalize: Callable[[str], str],
    security_of: SecurityOf,
    scope_codes: frozenset[str] | None,
    existing_for: ExistingLookup,
    writer: Writer | None,
    now: dt.datetime,
    run_id: str,
    compare_amount: bool,
    exclude: Set[str] = frozenset(),
) -> RunReport:
    """daily-bars-tdx §3.3 第 1–5 步；writer 为 None 即 dry-run（零写入）。

    与已有行同键（任何来源）的 bar 只进对账报告、不交给 writer；D 之后的行不导入。
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    audit = check_audit_dir(root, audit_dir)
    report = RunReport(kind=kind, run_id=run_id, apply=writer is not None)
    scanned = scan(
        root,
        kind,
        normalize=normalize,
        security_of=security_of,
        scope_codes=scope_codes,
        exclude=exclude,
    )
    report.skipped.update(scanned.skipped)
    report.files = len(scanned.files)

    previous = latest_manifest(audit, kind)
    gaps = [f"{market}/{KIND_DIR[kind]}" for market in MARKETS if market in exclude]
    report.issues.extend(f"tdx_scope_excluded:{rel}" for rel in gaps)
    manifest = build_manifest(scanned.files, gaps=gaps)
    stamp = now.astimezone(BEIJING).strftime("%Y%m%dT%H%M%S")
    report.manifest_name = f"tdx-{kind}-manifest-{stamp}-{run_id}.txt"
    report.manifest_sha256 = manifest.sha256
    _write_new(audit / report.manifest_name, manifest.text)
    if previous is not None:
        report.previous_manifest = previous[0]
        if previous[1] is None:
            report.issues.append("tdx_previous_manifest_invalid")
        else:
            report.rerun = compare_manifests(previous[1], manifest)

    hashes = {e.rel: e.sha256 for e in manifest.entries}
    mismatch_items = 0
    report.reconcile_name = f"tdx-{kind}-reconcile-{stamp}-{run_id}.jsonl"
    reconcile_path = audit / report.reconcile_name
    reconcile_tmp = reconcile_path.with_name(reconcile_path.name + ".part")
    reconcile_file = reconcile_tmp.open("x", encoding="utf-8")
    try:
        with reconcile_file:
            for cand in scanned.files:
                pending: list[TdxBar] = []
                data = cand.path.read_bytes()
                if kind == "day":
                    parsed = parse_day_bytes(cand.code, data)
                else:
                    parsed = parse_lc_bytes(cand.code, data, kind)
                # 第 4 步：解析后再算一次 sha256，与清单不同即视为导入中被改写。
                if (
                    hashlib.sha256(data).hexdigest() != hashes[cand.rel]
                    or file_sha256(cand.path) != hashes[cand.rel]
                ):
                    report.rejected_files["changed_during_import"] += 1
                    report.issues.append(f"tdx_file_changed:{cand.code}")
                    report.status = "partial"
                    continue
                report.rejected_records.update(parsed.rejected)
                if unit_suspect(parsed.bars):
                    report.rejected_files["unit_suspect"] += 1
                    report.issues.append(f"tdx_unit_suspect:{cand.code}")
                    report.status = "partial"
                    continue
                until = until_for(cand.code)
                kept: list[TdxBar] = []
                for bar in parsed.bars:
                    report.parsed_rows += 1
                    if start is not None and bar.trade_date < start:
                        report.before_from += 1
                    elif until is None or bar.trade_date > until:
                        report.after_until += 1
                    else:
                        kept.append(bar)
                existing = existing_for(cand.code, kept) if kept else {}
                for bar in kept:
                    row = existing.get(bar_key(bar))
                    if row is None:
                        pending.append(bar)
                        continue
                    report.overlap_rows += 1
                    items = reconcile(bar, row, compare_amount=compare_amount)
                    if items:
                        report.conflicts += 1
                        mismatch_items += len(items)
                        for item in items:
                            reconcile_file.write(
                                json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n"
                            )
                # T-A147 M1：逐文件落盘对账差异、逐文件写入，不跨文件攒行。
                reconcile_file.flush()
                report.would_insert += len(pending)
                if writer is not None and pending:
                    report.inserted += writer(pending)

            summary = {
                "summary": True,
                "overlap_keys": report.overlap_rows,
                "mismatch_keys": report.conflicts,
                "mismatch_items": mismatch_items,
                "mismatch_rate": (report.conflicts / report.overlap_rows)
                if report.overlap_rows
                else 0.0,
                "amount_compared": compare_amount,
            }
            reconcile_file.write(json.dumps(summary, ensure_ascii=False, sort_keys=True) + "\n")
        os.replace(reconcile_tmp, reconcile_path)
    except BaseException:
        # 裁定③：中途出错删掉本次创建的对账 .part（open("x") 失败不进这里），
        # 记一条日志后原样抛出。
        with contextlib.suppress(OSError):
            reconcile_tmp.unlink(missing_ok=True)
        logger.warning(
            "tdx 导入中途出错，已清理对账临时文件 %s（run_id=%s）", reconcile_tmp.name, run_id
        )
        raise
    return report
