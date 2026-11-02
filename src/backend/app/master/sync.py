"""主数据同步：快照入库、校验、合并、历史表（plan 4.6，T-B52）。

分两步，便于把外网抓取放在数据库事务之外：

1. :func:`collect`：按来源串行调用 ``fetcher``，得到每个来源的响应段（或抓取异常类型）。不连库。
2. :func:`apply_run`：在调用方给的连接（事务）里写 ``master_runs``、``master_snapshots``，
   校验后合并到 ``market.securities`` 与 4 张历史表。**本模块从不 commit**。

规则摘要（plan 4.6.1 / 4.6.4）：

- 交易所当前名单是唯一可以新建证券、改状态的来源；名单里简称带"退" → ``delisting_period``，
  否则 ``listed``；``delisted`` 只来自终止上市名单（带终止日期，且不在当前名单）。
- 某代码从当前名单消失、又不在终止上市名单：该来源连续 ``master.missing_after_snapshots`` 个
  *成功快照日*（``master_runs.stats`` 中该来源 ok 的不同 ``trade_date``，含本次）都没有它，才置
  ``missing_from_list``；重新出现即恢复。
- 同一代码同时出现在两个交易所的当前名单 → 本次不合并该代码（``stats.exchange_conflicts``）。
- 被拒收或抓取失败的来源，本次不改动该来源负责的任何字段。
- 历史表一律半开区间 ``[valid_from, valid_until)``；同一天的第二次变化就地改当天开的那一行。
- 深交所简称变更表（SSGSGMXX）快照内容变化时，按它整体重建深市证券的简称历史与风险警示历史。
- 日志只记来源 URL、行数与 sha256（运维补充 ②）。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import os
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, Table, and_, func, insert, select, text, update

from app.config_files import SecuritiesMaster
from app.db.tables.market import (
    master_runs,
    master_snapshots,
    securities,
    security_code_history,
    security_listing_status_history,
    security_name_history,
    security_risk_flag_history,
)
from app.master.sources import (
    DAILY_SOURCES,
    SOURCES,
    CodeMapRow,
    DelistRow,
    Fetcher,
    ListRow,
    ParseError,
    Part,
    RenameRow,
    Row,
    norm_name,
    pack_parts,
)
from app.master.validate import validate

log = logging.getLogger("app.master.sync")

BEIJING: Final = ZoneInfo("Asia/Shanghai")
#: 北交所开市日；此前的上市日期是原精选层挂牌日（T007 §2：list_date_basis=neeq_select）
BSE_OPENED: Final = dt.date(2021, 11, 15)
RAW_KEEP_DAYS: Final = 90


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def snapshot_trade_date(now: dt.datetime) -> dt.date:
    """快照对应的北京时间交易日：18:00 前算上一个工作日（07:30 补拉即上一交易日）。"""
    bj = now.astimezone(BEIJING)
    d = bj.date()
    if bj.time() < dt.time(18, 0):
        d -= dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def risk_flag(name: str) -> str | None:
    """简称前缀 → 风险警示（同时命中取最高：delisting > star_st > st）。"""
    n = norm_name(name)
    if "退" in n:
        return "delisting"
    if n.startswith(("*ST", "S*ST")):
        return "star_st"
    if n.startswith(("ST", "SST")):
        return "st"
    return None


def sec_code(code: str, exchange: str) -> str:
    """6 位代码 + 交易所 → ``securities.code``（如 ``600519.SH``，plan §3.3）。"""
    return f"{code}.{exchange}"


def listing_status_for(name: str) -> str:
    return "delisting_period" if "退" in name else "listed"


def resolve_master_root(path: str | os.PathLike[str] | None, app_env: str) -> Path | None:
    """``MASTER_SNAPSHOT_PATH``；未配置时 local/test 用 ``<tmp>/aia-master``，其他环境 None。"""
    if path is not None and str(path) != "":
        return Path(path)
    if app_env in {"local", "test"}:
        return Path(tempfile.gettempdir()) / "aia-master"
    return None


def _write_raw(root: Path, source: str, trade_date: dt.date, sha: str, raw: bytes) -> str:
    """原始快照落盘（公开数据，明文）；返回相对 ``root`` 的路径。"""
    rel = f"{source}/{trade_date:%Y%m%d}-{sha[:16]}.json"
    dest = root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    with open(tmp, "wb") as fh:
        fh.write(raw)
    os.chmod(tmp, 0o640)
    os.replace(tmp, dest)
    return rel


# ---------------------------------------------------------------------------
# 抓取（不连库）
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Fetched:
    source: str
    parts: list[Part] | None
    error: str | None = None  # 异常类型名


def collect(fetcher: Fetcher, sources: Iterable[str]) -> list[Fetched]:
    out: list[Fetched] = []
    for s in sources:
        try:
            out.append(Fetched(s, fetcher(s)))
        except Exception as exc:  # noqa: BLE001  只记类型
            log.warning("master 抓取失败 url=%s err=%s", SOURCES[s].url, type(exc).__name__)
            out.append(Fetched(s, None, type(exc).__name__))
    return out


# ---------------------------------------------------------------------------
# 快照
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Snap:
    source: str
    status: str  # ok / rejected / fetch_failed
    snapshot_id: int | None = None
    reason: str | None = None
    rows: Sequence[Row] = ()
    sha256: str | None = None
    row_count: int | None = None
    is_new: bool = False  # 本次内容（sha）此前没有成功快照
    fetched_at: dt.datetime | None = None


def _prev_ok_count(conn: Connection, source: str, exclude_id: int | None) -> int | None:
    q = (
        select(master_snapshots.c.row_count)
        .where(master_snapshots.c.source == source, master_snapshots.c.parse_status == "ok")
        .order_by(master_snapshots.c.fetched_at.desc(), master_snapshots.c.id.desc())
        .limit(1)
    )
    if exclude_id is not None:
        q = q.where(master_snapshots.c.id != exclude_id)
    v = conn.execute(q).scalar()
    return int(v) if v is not None else None


def take_snapshot(
    conn: Connection,
    f: Fetched,
    cfg: SecuritiesMaster,
    *,
    trade_date: dt.date,
    now: dt.datetime,
    raw_root: Path | None,
    check_drop: bool,
) -> Snap:
    src = SOURCES[f.source]
    if f.parts is None:
        return Snap(f.source, "fetch_failed", reason=f.error)
    raw = pack_parts(f.parts)
    sha = hashlib.sha256(raw).hexdigest()
    existing = conn.execute(
        select(master_snapshots.c.id, master_snapshots.c.parse_status).where(
            master_snapshots.c.source == f.source, master_snapshots.c.sha256 == sha
        )
    ).first()
    rows: Sequence[Row] = ()
    reason: str | None
    try:
        rows = src.parse(f.parts)
    except ParseError:
        reason = "parse_error"
    else:
        prev = _prev_ok_count(conn, f.source, existing.id if existing else None)
        reason = validate(rows, cfg, prev_ok_count=prev, check_drop=check_drop)
    status = "ok" if reason is None else "rejected"
    count = len(rows) if reason != "parse_error" else None
    values: dict[str, Any] = {
        "fetched_at": now,
        "trade_date": trade_date,
        "row_count": count,
        "parse_status": status,
        "reject_reason": reason,
    }
    if existing is not None:
        snap_id = int(existing.id)
        conn.execute(
            update(master_snapshots).where(master_snapshots.c.id == snap_id).values(**values)
        )
        is_new = existing.parse_status != "ok"
    else:
        raw_path = _write_raw(raw_root, f.source, trade_date, sha, raw) if raw_root else None
        snap_id = int(
            conn.execute(
                insert(master_snapshots)
                .values(source=f.source, url=src.url, sha256=sha, raw_path=raw_path, **values)
                .returning(master_snapshots.c.id)
            ).scalar_one()
        )
        is_new = True
    log.info("master 快照 url=%s rows=%s sha256=%s", src.url, count, sha)
    if status != "ok":
        log.warning("master 快照拒收 url=%s rows=%s sha256=%s", src.url, count, sha)
    return Snap(
        f.source,
        status,
        snap_id,
        reason,
        rows if status == "ok" else (),
        sha,
        count,
        is_new and status == "ok",
        now,
    )


# ---------------------------------------------------------------------------
# 历史表（半开区间）
# ---------------------------------------------------------------------------


def set_period(
    conn: Connection,
    table: Table,
    code: str,
    day: dt.date,
    key: str,
    value: object,
    extra: Mapping[str, Any] | None = None,
    *,
    skip_initial_null: bool = False,
) -> bool:
    """把 ``code`` 的 ``key`` 在 ``day`` 起改为 ``value``；值未变返回 False。

    当天已开的行就地改（PK (code, valid_from)）；开着的行晚于 ``day``（回填过）时不动。
    """
    extra = dict(extra or {})
    c = table.c
    cur = conn.execute(
        select(c.valid_from, c[key]).where(c.code == code, c.valid_until.is_(None))
    ).first()
    if cur is not None and cur[1] == value:
        return False
    if cur is None and value is None and skip_initial_null:
        return False
    if cur is not None and cur.valid_from > day:
        return False
    if cur is not None and cur.valid_from == day:
        conn.execute(
            update(table).where(c.code == code, c.valid_from == day).values({key: value, **extra})
        )
        return True
    if cur is not None:
        conn.execute(
            update(table)
            .where(c.code == code, c.valid_from == cur.valid_from)
            .values(valid_until=day)
        )
    conn.execute(insert(table).values(code=code, valid_from=day, **{key: value}, **extra))
    return True


# ---------------------------------------------------------------------------
# 合并
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Stats:
    added: int = 0
    renamed: int = 0
    status_changed: int = 0
    risk_changed: int = 0
    missing_pending: int = 0
    missing_set: int = 0
    delisted: int = 0
    exchange_conflicts: list[str] = field(default_factory=list)
    prefix_mismatch: list[str] = field(default_factory=list)
    name_history_rebuilt: int = 0
    code_map_rows: int = 0
    code_map_skipped: int = 0

    def as_dict(self) -> dict[str, Any]:
        d = {k: getattr(self, k) for k in self.__dataclass_fields__}
        d["exchange_conflicts"] = sorted(self.exchange_conflicts)[:50]
        d["prefix_mismatch"] = sorted(self.prefix_mismatch)[:50]
        return d


#: 前缀校验（T007 §3.2：只告警，不覆盖交易所给的板块）
_PREFIX_BOARD: Final[dict[str, dict[str, tuple[str, ...]]]] = {
    "SH": {"main": ("60",), "star": ("688", "689")},
    "SZ": {"main": ("000", "001", "002", "003", "004"), "chinext": ("300", "301", "302")},
    "BJ": {"bse": ("92", "8", "4")},
}


def _prefix_ok(r: ListRow) -> bool:
    prefixes = _PREFIX_BOARD.get(r.exchange, {}).get(r.board or "")
    return prefixes is None or r.code.startswith(prefixes)


def _ok_trade_dates_since(conn: Connection, source: str, since: dt.date | None) -> set[dt.date]:
    q = text(
        "SELECT DISTINCT (stats->>'trade_date')::date AS d FROM market.master_runs "
        "WHERE stats->'sources'->:src->>'status' = 'ok' "
        "AND (CAST(:since AS date) IS NULL OR (stats->>'trade_date')::date > :since)"
    )
    return {r.d for r in conn.execute(q, {"src": source, "since": since})}


def merge_lists(
    conn: Connection,
    snaps: Mapping[str, Snap],
    cfg: SecuritiesMaster,
    *,
    trade_date: dt.date,
    stats: Stats,
) -> None:
    lists = {s.source: s for s in snaps.values() if SOURCES[s.source].kind == "list"}
    delists = {
        SOURCES[s.source].exchange: s
        for s in snaps.values()
        if SOURCES[s.source].kind == "delist" and s.status == "ok"
    }
    seen: dict[str, set[str]] = {}
    for s in lists.values():
        if s.status == "ok":
            seen[SOURCES[s.source].exchange] = {r.code for r in s.rows if isinstance(r, ListRow)}
    dup = {
        c
        for ex, codes in seen.items()
        for c in codes
        if any(c in o for e, o in seen.items() if e != ex)
    }
    stats.exchange_conflicts.extend(dup)

    for s in lists.values():
        if s.status != "ok":
            continue
        ex = SOURCES[s.source].exchange
        current = {
            sec_code(r.code, ex): r
            for r in reversed([r for r in s.rows if isinstance(r, ListRow)])
            if r.code and r.name
        }
        delisted_codes = (
            {sec_code(r.code, ex) for r in delists[ex].rows if isinstance(r, DelistRow)}
            if ex in delists
            else set()
        )
        existing = {
            r.code: r
            for r in conn.execute(
                select(
                    securities.c.code,
                    securities.c.type,
                    securities.c.exchange,
                    securities.c.name,
                    securities.c.listing_status,
                    securities.c.risk_flag,
                    securities.c.last_seen_on,
                    securities.c.list_date,
                    securities.c.field_sources,
                ).where(securities.c.code.in_(list(current)) | (securities.c.exchange == ex))
            )
        }
        for code, r in sorted(current.items()):
            if r.code in dup:
                continue
            old = existing.get(code)
            if old is not None and old.exchange != ex:
                stats.exchange_conflicts.append(code)
                continue
            if not _prefix_ok(r):
                stats.prefix_mismatch.append(code)
            status = listing_status_for(r.name)
            flag = risk_flag(r.name)
            vals: dict[str, Any] = {
                "type": r.type,
                "name": r.name,
                "exchange": ex,
                "board": r.board,
                "listing_status": status,
                "risk_flag": flag,
                "name_norm": norm_name(r.name),
                "master_source": "exchange",
                "master_as_of": s.fetched_at,
                "last_seen_on": trade_date,
                "missing_since": None,
                "delist_date": None,
                "updated_at": func.now(),
            }
            if r.list_date is not None:
                vals["list_date"] = r.list_date
                vals["list_date_basis"] = (
                    "neeq_select" if ex == "BJ" and r.list_date < BSE_OPENED else "listing"
                )
                vals["field_sources"] = {
                    **((old.field_sources or {}) if old else {}),
                    "list_date": "exchange",
                }
            if old is None:
                conn.execute(insert(securities).values(code=code, **vals))
                stats.added += 1
            else:
                conn.execute(update(securities).where(securities.c.code == code).values(**vals))
                if old.name != r.name:
                    stats.renamed += 1
                if old.listing_status != status:
                    stats.status_changed += 1
            sid = {"snapshot_id": s.snapshot_id}
            set_period(
                conn,
                security_name_history,
                code,
                trade_date,
                "name",
                r.name,
                {"source": "exchange_diff", **sid},
            )
            if (
                set_period(
                    conn,
                    security_risk_flag_history,
                    code,
                    trade_date,
                    "risk_flag",
                    flag,
                    sid,
                    skip_initial_null=True,
                )
                and old is not None
            ):
                stats.risk_changed += 1
            set_period(
                conn,
                security_listing_status_history,
                code,
                trade_date,
                "listing_status",
                status,
                {"reason": "exchange_list", **sid},
            )

        # 从当前名单消失、又不在终止上市名单
        n_needed = cfg.missing_after_snapshots
        for code, old in sorted(existing.items()):
            if (
                old.exchange != ex
                or code in current
                or code in delisted_codes
                or old.type not in {"stock", "cdr"}  # ETF / 指数不在这三份名单里
                or old.listing_status not in {"listed", "delisting_period"}
            ):
                continue
            days = _ok_trade_dates_since(conn, s.source, old.last_seen_on)
            if old.last_seen_on is None or trade_date > old.last_seen_on:
                days.add(trade_date)
            if len(days) < n_needed:
                stats.missing_pending += 1
                continue
            conn.execute(
                update(securities)
                .where(securities.c.code == code)
                .values(
                    listing_status="missing_from_list",
                    missing_since=trade_date,
                    updated_at=func.now(),
                )
            )
            set_period(
                conn,
                security_listing_status_history,
                code,
                trade_date,
                "listing_status",
                "missing_from_list",
                {"reason": "missing_from_list", "snapshot_id": s.snapshot_id},
            )
            stats.missing_set += 1
            stats.status_changed += 1


def merge_delists(
    conn: Connection,
    snaps: Mapping[str, Snap],
    *,
    trade_date: dt.date,
    stats: Stats,
) -> None:
    on_list: set[str] = set()
    for s in snaps.values():
        if SOURCES[s.source].kind == "list" and s.status == "ok":
            ex_l = SOURCES[s.source].exchange
            on_list |= {sec_code(r.code, ex_l) for r in s.rows if isinstance(r, ListRow)}
    for s in snaps.values():
        if SOURCES[s.source].kind != "delist" or s.status != "ok":
            continue
        ex = SOURCES[s.source].exchange
        rows = {
            sec_code(r.code, ex): r
            for r in s.rows
            if isinstance(r, DelistRow) and r.code and r.delist_date
        }
        existing = {
            r.code: r
            for r in conn.execute(
                select(
                    securities.c.code,
                    securities.c.exchange,
                    securities.c.listing_status,
                    securities.c.delist_date,
                ).where(securities.c.code.in_(list(rows)))
            )
        }
        for code, r in sorted(rows.items()):
            if r.delist_date is None or code in on_list or r.delist_date > trade_date:
                continue  # 当前名单优先；未来日期不提前生效
            old = existing.get(code)
            sid = {"reason": "exchange_delist_list", "snapshot_id": s.snapshot_id}
            if old is None:
                vals: dict[str, Any] = {
                    "code": code,
                    "type": "cdr" if ex == "SH" and r.code.startswith("689") else "stock",
                    "name": r.name or code,
                    "exchange": ex,
                    "listing_status": "delisted",
                    "delist_date": r.delist_date,
                    "risk_flag": risk_flag(r.name),
                    "name_norm": norm_name(r.name),
                    "master_source": "exchange",
                    "master_as_of": s.fetched_at,
                }
                if r.list_date is not None:
                    vals["list_date"] = r.list_date
                    vals["list_date_basis"] = "listing"
                    vals["field_sources"] = {"list_date": "exchange"}
                conn.execute(insert(securities).values(**vals))
                set_period(
                    conn,
                    security_listing_status_history,
                    code,
                    r.delist_date,
                    "listing_status",
                    "delisted",
                    sid,
                )
                stats.added += 1
                stats.delisted += 1
                continue
            if old.exchange != ex:
                stats.exchange_conflicts.append(code)
                continue
            if old.listing_status == "delisted" and old.delist_date == r.delist_date:
                continue
            conn.execute(
                update(securities)
                .where(securities.c.code == code)
                .values(
                    listing_status="delisted",
                    delist_date=r.delist_date,
                    missing_since=None,
                    master_as_of=s.fetched_at,
                    updated_at=func.now(),
                )
            )
            if old.listing_status != "delisted":
                set_period(
                    conn,
                    security_listing_status_history,
                    code,
                    trade_date,
                    "listing_status",
                    "delisted",
                    sid,
                )
                stats.delisted += 1
                stats.status_changed += 1


def _merge_runs(seq: Sequence[tuple[dt.date, Any]]) -> list[tuple[dt.date, Any]]:
    """相邻同值合并、同一天取最后一个。"""
    by_day: dict[dt.date, Any] = {}
    for d, v in seq:
        by_day[d] = v
    out: list[tuple[dt.date, Any]] = []
    for d in sorted(by_day):
        if out and out[-1][1] == by_day[d]:
            continue
        out.append((d, by_day[d]))
    return out


def _rebuild(
    conn: Connection,
    table: Table,
    code: str,
    key: str,
    seq: list[tuple[dt.date, Any]],
    extra: Mapping[str, Any],
) -> None:
    conn.execute(table.delete().where(table.c.code == code))
    for i, (d, v) in enumerate(seq):
        until = seq[i + 1][0] if i + 1 < len(seq) else None
        conn.execute(
            insert(table).values(code=code, valid_from=d, valid_until=until, **{key: v}, **extra)
        )


def rebuild_szse_names(conn: Connection, snap: Snap, *, trade_date: dt.date, stats: Stats) -> None:
    """按深交所简称变更表整体重建深市证券的简称历史与风险警示历史。"""
    changes: dict[str, list[RenameRow]] = {}
    for r in snap.rows:
        if isinstance(r, RenameRow) and r.code and r.changed_on and r.after:
            changes.setdefault(sec_code(r.code, "SZ"), []).append(r)
    if not changes:
        return
    known = {
        row.code: row
        for row in conn.execute(
            select(securities.c.code, securities.c.name, securities.c.list_date).where(
                securities.c.exchange == "SZ", securities.c.code.in_(list(changes))
            )
        )
    }
    for code, rows in sorted(changes.items()):
        sec = known.get(code)
        if sec is None:
            continue
        rows.sort(key=lambda r: r.changed_on or dt.date.min)  # 稳定排序：同日保留文件顺序
        first = rows[0]
        names: list[tuple[dt.date, Any]] = []
        if (
            first.before
            and first.changed_on is not None
            and sec.list_date is not None
            and sec.list_date < first.changed_on
        ):
            names.append((sec.list_date, first.before))
        names += [(r.changed_on, r.after) for r in rows if r.changed_on]
        names = _merge_runs(names)
        if names[-1][1] != sec.name and trade_date > names[-1][0]:
            names.append((trade_date, sec.name))  # 当前名单的简称与变更表最后一条不同
        sid = {"snapshot_id": snap.snapshot_id}
        _rebuild(
            conn,
            security_name_history,
            code,
            "name",
            names,
            {"source": "szse_ssgsgmxx", **sid},
        )
        flags = _merge_runs([(d, risk_flag(n)) for d, n in names])
        while flags and flags[0][1] is None:
            flags.pop(0)  # 首段无风险警示不记（null 只表示摘帽）
        _rebuild(conn, security_risk_flag_history, code, "risk_flag", flags, sid)
        stats.name_history_rebuilt += 1


def merge_code_map(conn: Connection, snap: Snap, *, trade_date: dt.date, stats: Stats) -> None:
    """北交所旧代码 → 新代码。valid_from 取对照表的上市日期（换码日官网未给，见报告）。"""
    pairs = [
        (sec_code(r.old_code, "BJ"), sec_code(r.new_code, "BJ"), r.list_date)
        for r in snap.rows
        if isinstance(r, CodeMapRow) and r.old_code and r.new_code
    ]
    known = set(
        conn.execute(
            select(securities.c.code).where(securities.c.code.in_([p[1] for p in pairs]))
        ).scalars()
    )
    t = security_code_history
    for old, new, list_date in pairs:
        if new not in known or old == new:
            stats.code_map_skipped += 1
            continue
        vf = list_date or trade_date
        cur = conn.execute(select(t.c.code, t.c.valid_from).where(t.c.old_code == old)).first()
        if cur is not None and cur.code == new and cur.valid_from == vf:
            continue
        if cur is not None:
            conn.execute(t.delete().where(t.c.old_code == old))
        conn.execute(insert(t).values(code=new, old_code=old, valid_from=vf, source="bse_code_map"))
        stats.code_map_rows += 1


# ---------------------------------------------------------------------------
# 一次运行
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RunResult:
    run_id: int
    status: str
    snaps: dict[str, Snap]
    stats: dict[str, Any]


def sources_to_retry(conn: Connection, trade_date: dt.date) -> list[str]:
    """07:30 补拉：该交易日所有运行里都没有成功过的每日来源。"""
    done = {
        r.src
        for r in conn.execute(
            text(
                "SELECT DISTINCT kv.key AS src FROM market.master_runs mr, "
                "jsonb_each(mr.stats->'sources') kv "
                "WHERE mr.stats->>'trade_date' = :d AND kv.value->>'status' = 'ok'"
            ),
            {"d": trade_date.isoformat()},
        )
    }
    return [s for s in DAILY_SOURCES if s not in done]


def apply_run(
    conn: Connection,
    fetched: Sequence[Fetched],
    cfg: SecuritiesMaster,
    *,
    trigger: str,
    trade_date: dt.date,
    now: dt.datetime | None = None,
    raw_root: Path | None,
    force_rebuild: bool = False,
) -> RunResult:
    """写一次 ``master_runs`` 并合并；不 commit。``bootstrap`` 不查行数下降。"""
    now = now or dt.datetime.now(dt.UTC)
    run_id = int(
        conn.execute(
            insert(master_runs).values(trigger=trigger, started_at=now).returning(master_runs.c.id)
        ).scalar_one()
    )
    snaps = {
        f.source: take_snapshot(
            conn,
            f,
            cfg,
            trade_date=trade_date,
            now=now,
            raw_root=raw_root,
            check_drop=trigger != "bootstrap",
        )
        for f in fetched
    }
    stats = Stats()
    merge_lists(conn, snaps, cfg, trade_date=trade_date, stats=stats)
    merge_delists(conn, snaps, trade_date=trade_date, stats=stats)
    rn = snaps.get("szse_rename")
    if rn is not None and rn.status == "ok" and (rn.is_new or force_rebuild):
        rebuild_szse_names(conn, rn, trade_date=trade_date, stats=stats)
    cm = snaps.get("bse_code_map")
    if cm is not None and cm.status == "ok":
        merge_code_map(conn, cm, trade_date=trade_date, stats=stats)

    oks = [s for s in snaps.values() if s.status == "ok"]
    status = "ok" if len(oks) == len(snaps) else ("failed" if not oks else "partial")
    if not snaps:
        status = "ok"
    st: dict[str, Any] = {
        "trade_date": trade_date.isoformat(),
        "sources": {
            s.source: {
                "status": s.status,
                "reason": s.reason,
                "rows": s.row_count,
                "snapshot_id": s.snapshot_id,
            }
            for s in snaps.values()
        },
        "rejected": sorted(s.source for s in snaps.values() if s.status == "rejected"),
        **stats.as_dict(),
    }
    conn.execute(
        update(master_runs)
        .where(master_runs.c.id == run_id)
        .values(
            finished_at=func.now(),
            status=status,
            snapshot_ids=[s.snapshot_id for s in snaps.values() if s.snapshot_id is not None],
            stats=st,
        )
    )
    return RunResult(run_id, status, snaps, st)


def record_failed_run(conn: Connection, trigger: str, trade_date: dt.date, error: str) -> int:
    """重试用尽后记一条 ``status='failed'`` 的运行（只记异常类型）。"""
    return int(
        conn.execute(
            insert(master_runs)
            .values(
                trigger=trigger,
                finished_at=func.now(),
                status="failed",
                stats={"trade_date": trade_date.isoformat(), "error": error[:64]},
            )
            .returning(master_runs.c.id)
        ).scalar_one()
    )


# ---------------------------------------------------------------------------
# 原始文件清理
# ---------------------------------------------------------------------------


class MasterRootMissingError(FileNotFoundError):
    """主数据快照根目录不存在（不含路径）。"""


def purge_snapshots(
    conn: Connection,
    root: Path,
    *,
    now: dt.datetime | None = None,
    keep_days: int = RAW_KEEP_DAYS,
) -> int:
    """删除超过 ``keep_days`` 天的原始快照文件，``raw_path`` 置空；另清掉无记录的过期孤儿文件。"""
    if not root.is_dir():
        raise MasterRootMissingError("主数据快照根目录不存在")
    now = now or dt.datetime.now(dt.UTC)
    cutoff = now - dt.timedelta(days=keep_days)
    rows = conn.execute(
        select(master_snapshots.c.id, master_snapshots.c.raw_path).where(
            and_(master_snapshots.c.fetched_at < cutoff, master_snapshots.c.raw_path.is_not(None))
        )
    ).all()
    base = root.resolve()
    n = 0
    for r in rows:
        p = (root / r.raw_path).resolve()
        if base not in p.parents:
            continue  # 防御：raw_path 不得跳出根目录
        p.unlink(missing_ok=True)
        conn.execute(
            update(master_snapshots).where(master_snapshots.c.id == r.id).values(raw_path=None)
        )
        n += 1
    ts_cut = cutoff.timestamp()
    for p in root.glob("*/*"):
        if p.is_file() and p.stat().st_mtime < ts_cut:
            p.unlink(missing_ok=True)
            n += 1
    return n
