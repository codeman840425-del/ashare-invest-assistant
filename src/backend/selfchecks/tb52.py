# ruff: noqa: E501, S608  自检脚本：检查描述保持单行
"""T-B52 自检（隔离 PG / Redis，见 ``_common``；**全部为虚构数据**，不访问任何外部接口）。

所有数据库写入都在一个最终回滚的事务里完成（worker / CLI 的事务用 SAVEPOINT 代替）：

- 整份拒收 4 种：empty / drop_pct / key_missing / parse_error（被拒来源不改动其字段、不计入连续缺失）；
- 合并规则：简称带"退" → delisting_period；风险警示前缀；终止上市名单 → delisted（当前名单优先）；
  连续 ``missing_after_snapshots`` 个成功快照日缺失才 missing_from_list，重新出现即恢复；
  同一代码出现在两所名单 → 不合并；同一天第二次变化就地改；相同 sha 复用快照；
- 历史表：深交所简称变更表重建简称 / 风险警示历史；北交所代码对照；北交所平移股 neeq_select；
- 07:30 补拉只拉上一交易日没有成功的来源；钟点排程、10 分钟重试 3 次、Redis 锁、对账链；
- 首次导入不触发 reconcile_vendor（AST + 运行时队列）；日志只含 URL / 行数 / sha256；
- 原始快照 90 天清理；``MASTER_SNAPSHOT_PATH`` 默认值。
"""

from __future__ import annotations

import ast
import datetime as dt
import io
import json
import logging
import os
import re
import sys
import tempfile
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import redis as redislib
from _common import DB, RURL, check, engine, finish
from sqlalchemy import Connection, text

from app.cli import master_bootstrap
from app.config import Settings
from app.master import sync
from app.master.sources import (
    BSE_CODE_MAP_URL,
    FetchError,
    Part,
    bse_page_url,
    sse_delist_url,
    sse_list_url,
    szse_url,
)
from app.master.validate import validate
from app.workers import jobs

BACKEND = Path(__file__).resolve().parents[1]
ROOT = Path(tempfile.mkdtemp(prefix="tb52-master-"))
settings = Settings(database_url=DB, redis_url=RURL, master_snapshot_path=ROOT)  # type: ignore[call-arg]
cfg = settings.business.securities.master
BJT = sync.BEIJING
rds = redislib.Redis.from_url(RURL)
rds.flushdb()

# ---------------------------------------------------------------- 日志捕获
LOGS: list[str] = []


class _Cap(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        LOGS.append(record.getMessage())


_lg = logging.getLogger("app.master.sync")
_lg.addHandler(_Cap())
_lg.setLevel(logging.INFO)

# ---------------------------------------------------------------- 虚构数据构造
FILL_SH = [(f"60{i:04d}", f"填充沪{i}") for i in range(3910, 4030)]
FILL_SZ = [(f"00{i:04d}", f"填充深{i}") for i in range(2510, 2630)]
FILL_BJ = [(f"92{i:04d}", f"填充北{i}") for i in range(510, 630)]


def sse_list_json(rows: list[tuple[str, str, str]]) -> bytes:
    return json.dumps(
        {
            "result": [
                {
                    "A_STOCK_CODE": c,
                    "SEC_NAME_CN": n,
                    "COMPANY_ABBR": n,
                    "LIST_DATE": "20200102",
                    "STOCK_TYPE": t,
                }
                for c, n, t in rows
            ]
        }
    ).encode()


def sh_parts(extra: list[tuple[str, str]], star: list[tuple[str, str]]) -> list[Part]:
    main = [(c, n, "1") for c, n in FILL_SH + extra]
    return [
        Part(sse_list_url("1"), sse_list_json(main)),
        Part(sse_list_url("8"), sse_list_json([(c, n, "8") for c, n in star])),
    ]


def sse_delist_json(rows: list[tuple[str, str, str]]) -> list[Part]:
    body = json.dumps(
        {
            "result": [
                {"A_STOCK_CODE": c, "COMPANY_ABBR": n, "LIST_DATE": "20000104", "DELIST_DATE": d}
                for c, n, d in rows
            ]
        }
    ).encode()
    return [Part(sse_delist_url(), body)]


def xlsx(header: list[str], rows: list[list[str]]) -> bytes:
    def row(cells: list[str]) -> str:
        return (
            "<row>"
            + "".join(f'<c t="inlineStr"><is><t>{escape(v)}</t></is></c>' for v in cells)
            + "</row>"
        )

    sheet = (
        '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
        + row(header)
        + "".join(row(r) for r in rows)
        + "</sheetData></worksheet>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(
            zipfile.ZipInfo("xl/worksheets/sheet1.xml", (2020, 1, 1, 0, 0, 0)), sheet
        )  # 固定时间戳，内容相同则 sha 相同
    return buf.getvalue()


SZ_HEAD = ["板块", "公司全称", "A股代码", "A股简称", "A股上市日期"]


def sz_parts(extra: list[tuple[str, str, str]], *, empty: bool = False) -> list[Part]:
    rows = (
        []
        if empty
        else [["主板", "", c, n, "2011-03-01"] for c, n in FILL_SZ]
        + [[b, "", c, n, "2010-01-04"] for c, n, b in extra]
    )
    return [Part(szse_url("1110", "tab1"), xlsx(SZ_HEAD, rows))]


def sz_delist(rows: list[tuple[str, str, str]]) -> list[Part]:
    return [
        Part(
            szse_url("1793_ssgs", "tab2"),
            xlsx(
                ["证券代码", "证券简称", "上市日期", "终止上市日期"],
                [[c, n, "2001-02-05", d] for c, n, d in rows],
            ),
        )
    ]


def sz_rename(rows: list[tuple[str, str, str, str]]) -> list[Part]:
    return [
        Part(
            szse_url("SSGSGMXX", "tab2"),
            xlsx(["变更日期", "证券代码", "变更前简称", "变更后简称"], [list(r) for r in rows]),
        )
    ]


def bj_parts(extra: list[tuple[str, str, str]], blank_names: int = 0) -> list[Part]:
    content = [
        {"xxzqdm": c, "xxzqjc": "" if i < blank_names else n, "fxssrq": "20220103"}
        for i, (c, n) in enumerate(FILL_BJ)
    ]
    content += [{"xxzqdm": c, "xxzqjc": n, "fxssrq": d} for c, n, d in extra]
    return [
        Part(
            bse_page_url(1),
            ("cb(" + json.dumps([{"content": content, "totalPages": 1}]) + ")").encode(),
        )
    ]


def bj_map(rows: list[tuple[str, str, str, str]]) -> list[Part]:
    tr = "".join(
        f"<tr><td>{n}</td><td>{d}</td><td>{o}</td><td>{c}</td></tr>" for n, d, o, c in rows
    )
    return [
        Part(
            BSE_CODE_MAP_URL,
            f"<html><table><tr><th>证券简称</th><th>上市日期</th><th>旧代码</th><th>新代码</th></tr>{tr}</table></html>".encode(),
        )
    ]


SH1 = [("603901", "测试甲"), ("603902", "*ST测乙"), ("603903", "测试戊退"), ("603905", "两所重")]
STAR = [("688901", "测科丙"), ("689901", "测存丁")]
SZ1 = [("002901", "测深甲", "主板"), ("300901", "测创乙", "创业板"), ("603905", "两所重", "主板")]
SH_DEL = [
    ("603909", "测退己", "20200506"),
    ("603901", "测试甲", "20190101"),
    ("603908", "测未来", "20991231"),
]
SZ_DEL = [("002909", "测深退", "2019-01-02"), ("200909", "测深B", "2019-01-02")]
RENAME = [
    ("2015-01-05", "002901", "测深旧", "ST测深"),
    ("2018-03-01", "002901", "ST测深", "临时名"),
    ("2018-03-01", "002901", "ST测深", "测深甲"),  # 同一天保留最后一条
    ("2016-01-01", "002999", "无此证", "无此证2"),  # 不在主数据 → 跳过
]
BJ1 = [("920901", "测北甲", "20200727"), ("920902", "测北乙", "20230510")]
CMAP = [("测北甲", "2020-07-27", "830901", "920901"), ("无此证", "2021-01-04", "830999", "920999")]


def world(**over: Any) -> dict[str, Any]:  # noqa: ANN401
    w: dict[str, Any] = {
        "sse_list": sh_parts(SH1, STAR),
        "sse_delist": sse_delist_json(SH_DEL),
        "szse_list": sz_parts(SZ1),
        "szse_delist": sz_delist(SZ_DEL),
        "szse_rename": sz_rename(RENAME),
        "bse_list": bj_parts(BJ1),
        "bse_code_map": bj_map(CMAP),
    }
    w.update(over)
    return w


CALLS: list[str] = []


def fetcher_of(w: dict[str, Any]) -> Callable[[str], list[Part]]:
    def f(src: str) -> list[Part]:
        CALLS.append(src)
        v = w[src]
        if isinstance(v, Exception):
            raise v
        return list(v)

    return f


D1, D2, D3, D4 = (dt.date(2025, 3, d) for d in (3, 4, 5, 6))  # 周一至周四


def at(day: dt.date, hhmm: str = "18:05") -> dt.datetime:
    h, m = map(int, hhmm.split(":"))
    return dt.datetime.combine(day, dt.time(h, m), BJT)


def run(
    c: Connection,
    w: dict[str, Any],
    day: dt.date,
    trigger: str = "beat_1800",
    srcs: list[str] | None = None,
    now: dt.datetime | None = None,
) -> sync.RunResult:
    return sync.apply_run(
        c,
        sync.collect(fetcher_of(w), srcs or list(w)),
        cfg,
        trigger=trigger,
        trade_date=day,
        now=now or at(day),
        raw_root=ROOT,
        force_rebuild=trigger == "bootstrap",
    )


def sec(c: Connection, code: str) -> Any:  # noqa: ANN401
    return c.execute(text("select * from market.securities where code = :c"), {"c": code}).first()


def hist(c: Connection, table: str, code: str, col: str) -> list[tuple[Any, ...]]:
    return [
        tuple(r)
        for r in c.execute(
            text(
                f"select {col}, valid_from, valid_until from market.{table} where code = :c order by valid_from"
            ),
            {"c": code},
        )
    ]


# ---------------------------------------------------------------- 纯函数
check(
    sync.risk_flag("*ST测乙") == "star_st"
    and sync.risk_flag("ST测") == "st"
    and sync.risk_flag("ＳＴ测") == "st",
    "风险警示：*ST → star_st，ST（含全角）→ st",
)
check(
    sync.risk_flag("*ST测退") == "delisting" and sync.risk_flag("测试甲") is None,
    "风险警示：带退 → delisting（优先级最高），普通 → None",
)
check(
    sync.listing_status_for("测试戊退") == "delisting_period"
    and sync.listing_status_for("测试甲") == "listed",
    "当前名单简称带退 → delisting_period",
)
check(
    sync.snapshot_trade_date(at(D1, "17:59")) == dt.date(2025, 2, 28)
    and sync.snapshot_trade_date(at(D1, "18:00")) == D1,
    "快照交易日：18:00 前算上一工作日（周一 17:59 → 上周五）",
)
check(
    sync.snapshot_trade_date(at(D2, "07:30")) == D1
    and sync.snapshot_trade_date(at(dt.date(2025, 3, 8), "20:00")) == dt.date(2025, 3, 7),
    "快照交易日：07:30 补拉 → 上一交易日；周六 → 周五",
)
check(sync.sec_code("603901", "SH") == "603901.SH", "securities.code 带交易所后缀")
r100 = [
    master_bootstrap.sync.ListRow(f"60{i:04d}", f"名{i}", D1, "SH", "main", "stock")
    for i in range(100)
]  # type: ignore[attr-defined]
check(validate([], cfg, prev_ok_count=10, check_drop=True) == "empty", "校验 empty：0 行")
check(
    validate(r100[:97], cfg, prev_ok_count=100, check_drop=True) == "drop_pct",
    "校验 drop_pct：比上一份少 3% > 2%",
)
check(
    validate(r100[:97], cfg, prev_ok_count=100, check_drop=False) is None,
    "校验：首次导入不查行数下降",
)
check(validate(r100[:99], cfg, prev_ok_count=100, check_drop=True) is None, "校验：少 1% 不拒收")
miss = [*r100[:99], master_bootstrap.sync.ListRow("609999", "", D1, "SH", "main", "stock")]  # type: ignore[attr-defined]
check(
    validate(miss, cfg, prev_ok_count=None, check_drop=True) == "key_missing",
    "校验 key_missing：简称缺失 1% > 0.5%",
)
check(
    sync.resolve_master_root(None, "production") is None
    and sync.resolve_master_root(None, "local") == Path(tempfile.gettempdir()) / "aia-master",
    "MASTER_SNAPSHOT_PATH 未设置：生产 None，local 临时目录",
)

# ---------------------------------------------------------------- 静态：首次导入不触发对账、无响应缓存
src = (BACKEND / "app/cli/master_bootstrap.py").read_text(encoding="utf-8")
tree = ast.parse(src)
docs = {
    id(n.value)
    for n in ast.walk(tree)
    if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
}
names: set[str] = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Name):
        names.add(node.id)
    elif isinstance(node, ast.Attribute):
        names.add(node.attr)
    elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
        names.add(node.value)
    elif isinstance(node, ast.ImportFrom):
        names.add(node.module or "")
check(
    not any("reconcile" in n or "app.workers" in n or "lpush" in n for n in names),
    "运维①：master_bootstrap 代码不引用 reconcile_vendor / worker 队列（AST）",
)
master_src = "".join(p.read_text(encoding="utf-8") for p in (BACKEND / "app/master").glob("*.py"))
check(
    "lru_cache" not in master_src and "Cache-Control" not in master_src,
    "运维③：主数据同步不引入任何响应缓存（检索接口的按用户缓存在 T-B54）",
)

# ---------------------------------------------------------------- 合并（回滚事务）
with engine().connect() as c:
    tx = c.begin()
    try:
        # D1 首次导入
        LOGS.clear()
        CALLS.clear()
        n_snap0 = c.execute(text("select count(*) from market.master_snapshots")).scalar() or 0
        r1 = run(c, world(), D1, "bootstrap")
        check(
            r1.status == "ok" and all(s.status == "ok" for s in r1.snaps.values()),
            f"D1 首次导入 7 个来源都 ok（{r1.status}）",
        )
        check(
            c.execute(
                text("select trigger from market.master_runs where id = :i"), {"i": r1.run_id}
            ).scalar()
            == "bootstrap",
            "master_runs.trigger = bootstrap",
        )
        a = sec(c, "603901.SH")
        check(
            a is not None
            and a.listing_status == "listed"
            and a.delist_date is None
            and a.board == "main"
            and a.type == "stock",
            "当前名单优先：603901 同时在终止上市名单 → 仍 listed",
        )
        check(
            a.master_source == "exchange"
            and a.last_seen_on == D1
            and a.name_norm == "测试甲"
            and a.list_date_basis == "listing",
            "securities：master_source / last_seen_on / name_norm / list_date_basis",
        )
        check(
            sec(c, "603902.SH").risk_flag == "star_st"
            and sec(c, "603903.SH").listing_status == "delisting_period"
            and sec(c, "603903.SH").risk_flag == "delisting",
            "*ST → star_st；简称带退 → delisting_period + delisting",
        )
        check(
            sec(c, "689901.SH").type == "cdr"
            and sec(c, "688901.SH").type == "stock"
            and sec(c, "688901.SH").board == "star",
            "科创板 689 段 → cdr，688 → stock / star",
        )
        d = sec(c, "603909.SH")
        check(
            d is not None
            and d.listing_status == "delisted"
            and d.delist_date == dt.date(2020, 5, 6),
            "终止上市名单 → delisted + delist_date",
        )
        check(
            hist(c, "security_listing_status_history", "603909.SH", "listing_status")
            == [("delisted", dt.date(2020, 5, 6), None)],
            "delisted 历史从终止日期开始",
        )
        check(
            sec(c, "603908.SH") is None and sec(c, "200909.SZ") is None,
            "未来终止日期不提前生效；深市 B 股不入库",
        )
        check(
            sec(c, "603905.SH") is None
            and sec(c, "603905.SZ") is None
            and "603905" in r1.stats["exchange_conflicts"],
            "同一代码出现在两所名单 → 本次不合并，记 stats",
        )
        check(
            sec(c, "002909.SZ").listing_status == "delisted"
            and sec(c, "300901.SZ").board == "chinext",
            "深市终止上市 / 创业板板块",
        )
        check(
            sec(c, "920901.BJ").list_date_basis == "neeq_select"
            and sec(c, "920902.BJ").list_date_basis == "listing",
            "北交所 2021-11-15 前上市 → neeq_select",
        )
        check(
            hist(c, "security_name_history", "002901.SZ", "name")
            == [
                ("测深旧", dt.date(2010, 1, 4), dt.date(2015, 1, 5)),
                ("ST测深", dt.date(2015, 1, 5), dt.date(2018, 3, 1)),
                ("测深甲", dt.date(2018, 3, 1), None),
            ],
            "简称变更表重建简称历史（首段从上市日、同日取最后一条）",
        )
        check(
            hist(c, "security_risk_flag_history", "002901.SZ", "risk_flag")
            == [
                ("st", dt.date(2015, 1, 5), dt.date(2018, 3, 1)),
                (None, dt.date(2018, 3, 1), None),
            ],
            "风险警示历史随简称重建（null = 摘帽）",
        )
        check(
            c.execute(
                text("select count(*) from market.security_name_history where code = '002999.SZ'")
            ).scalar()
            == 0,
            "变更表里主数据没有的代码跳过",
        )
        ch = c.execute(
            text(
                "select code, valid_from, valid_until from market.security_code_history where old_code = '830901.BJ'"
            )
        ).first()
        check(
            ch is not None
            and tuple(ch) == ("920901.BJ", dt.date(2020, 7, 27), None)
            and r1.stats["code_map_skipped"] == 1,
            "北交所代码对照：830901 → 920901；新代码不在主数据 → 跳过",
        )
        check(
            hist(c, "security_risk_flag_history", "603901.SH", "risk_flag") == [],
            "无风险警示的新证券不写 null 首行",
        )
        raws = (
            c.execute(
                text("select raw_path from market.master_snapshots where id = any(:ids)"),
                {"ids": list(r1.stats and [s.snapshot_id for s in r1.snaps.values()])},
            )
            .scalars()
            .all()
        )
        check(
            len(raws) == 7 and all(p and (ROOT / p).is_file() for p in raws),
            "7 份原始快照落盘，raw_path 指向文件",
        )
        pat = re.compile(
            r"^master 快照(拒收)? url=https://\S+ rows=(\d+|None) sha256=[0-9a-f]{64}$|^master 抓取失败 url=https://\S+ err=\w+$"
        )
        check(
            LOGS and all(pat.match(m) for m in LOGS),
            f"运维②：日志只含 URL / 行数 / sha256（{len(LOGS)} 条）",
        )
        check(not any("测" in m or "603901" in m for m in LOGS), "日志不含任何简称或代码")

        # D2：603902 消失；603901 改名 ST
        sh2 = sh_parts([("603901", "ST测试甲"), ("603903", "测试戊退")], STAR)
        r2 = run(c, world(sse_list=sh2), D2)
        check(r2.status == "ok" and r2.snaps["sse_list"].status == "ok", "D2 少 1 行（< 2%）不拒收")
        check(
            sec(c, "603902.SH").listing_status == "listed" and r2.stats["missing_pending"] >= 1,
            "D2 缺失 1 个成功快照日 → 仍 listed（待满 2 个）",
        )
        check(
            hist(c, "security_name_history", "603901.SH", "name")
            == [("测试甲", D1, D2), ("ST测试甲", D2, None)],
            "改名：关旧行、开新行 [D2, ∞)",
        )
        check(
            hist(c, "security_risk_flag_history", "603901.SH", "risk_flag") == [("st", D2, None)],
            "戴帽：风险警示历史从 D2 起 st",
        )
        same = (
            r2.snaps["sse_delist"].snapshot_id == r1.snaps["sse_delist"].snapshot_id
            and not r2.snaps["szse_rename"].is_new
        )
        n_snap = c.execute(text("select count(*) from market.master_snapshots")).scalar()
        check(
            same and n_snap == n_snap0 + 8,
            f"内容相同（同 sha）复用原快照行，只新增变化的 1 份（{n_snap0} → {n_snap}）",
        )
        # D2 同一天第二次：*ST
        sh2b = sh_parts([("603901", "*ST测试甲"), ("603903", "测试戊退")], STAR)
        run(c, world(sse_list=sh2b), D2, "manual", srcs=["sse_list"])
        check(
            hist(c, "security_name_history", "603901.SH", "name")
            == [("测试甲", D1, D2), ("*ST测试甲", D2, None)],
            "同一天第二次变化：就地改当天开的行",
        )
        check(
            hist(c, "security_risk_flag_history", "603901.SH", "risk_flag")
            == [("star_st", D2, None)]
            and sec(c, "603901.SH").risk_flag == "star_st",
            "同一天风险警示就地改为 star_st",
        )

        # D3：SH 第 2 个成功快照日仍缺 603902；SZ 整份 empty；BJ key_missing；SZ 终止名单 parse_error
        r3 = run(
            c,
            world(
                sse_list=sh2b,
                szse_list=sz_parts([], empty=True),
                szse_delist=[Part(szse_url("1793_ssgs", "tab2"), b"not-an-xlsx")],
                bse_list=bj_parts(BJ1, blank_names=2),
            ),
            D3,
        )
        s3 = r3.stats["sources"]
        check(
            s3["szse_list"]["status"] == "rejected" and s3["szse_list"]["reason"] == "empty",
            "拒收 empty：深市名单 0 行",
        )
        check(s3["bse_list"]["reason"] == "key_missing", "拒收 key_missing：北交所 2/122 简称缺失")
        pe = c.execute(
            text(
                "select parse_status, reject_reason, row_count from market.master_snapshots where id = :i"
            ),
            {"i": s3["szse_delist"]["snapshot_id"]},
        ).first()
        check(
            tuple(pe) == ("rejected", "parse_error", None),
            "拒收 parse_error：rejected、row_count 为空",
        )
        check(
            r3.status == "partial"
            and sorted(r3.stats["rejected"]) == ["bse_list", "szse_delist", "szse_list"],
            "有来源被拒 → 运行 partial，stats.rejected 列出",
        )
        b = sec(c, "603902.SH")
        check(
            b.listing_status == "missing_from_list" and b.missing_since == D3,
            "连续 2 个成功快照日缺失 → missing_from_list，missing_since = D3",
        )
        check(
            hist(c, "security_listing_status_history", "603902.SH", "listing_status")[-1]
            == ("missing_from_list", D3, None),
            "上市状态历史记 missing_from_list",
        )
        check(
            c.execute(
                text(
                    "select reason from market.security_listing_status_history where code = '603902.SH' and valid_from = :d"
                ),
                {"d": D3},
            ).scalar()
            == "missing_from_list",
            "历史 reason = missing_from_list",
        )
        check(
            sec(c, "002901.SZ").last_seen_on == D2
            and sec(c, "300901.SZ").listing_status == "listed",
            "被拒收的深市名单不改动深市证券（last_seen_on 仍 D2）",
        )
        check(
            sync.sources_to_retry(c, D3) == ["szse_delist", "szse_list", "bse_list"]
            or sorted(sync.sources_to_retry(c, D3)) == ["bse_list", "szse_delist", "szse_list"],
            "补拉清单 = 当日没有成功过的来源",
        )

        # D4：603902 重新出现；深市恢复但缺 300901（D3 拒收不计）；上交所终止名单抓取失败
        sz4 = sz_parts([("002901", "测深甲", "主板")])
        LOGS.clear()
        r4 = run(
            c,
            world(sse_list=sh_parts(SH1, STAR), szse_list=sz4, sse_delist=FetchError("http 503")),
            D4,
        )
        b = sec(c, "603902.SH")
        check(
            b.listing_status == "listed" and b.missing_since is None and b.last_seen_on == D4,
            "重新出现 → 恢复 listed，missing_since 清空",
        )
        check(
            hist(c, "security_listing_status_history", "603902.SH", "listing_status")[-1]
            == ("listed", D4, None),
            "恢复写入上市状态历史",
        )
        check(
            sec(c, "300901.SZ").listing_status == "listed",
            "被拒收的快照日不计入连续缺失（300901 仅缺 1 个成功日）",
        )
        check(
            r4.stats["sources"]["sse_delist"]["status"] == "fetch_failed"
            and r4.stats["sources"]["sse_delist"]["snapshot_id"] is None
            and r4.status == "partial",
            "抓取失败：不写快照行，stats 记 fetch_failed，运行 partial",
        )
        check(
            any(
                m.startswith("master 抓取失败 url=https://") and m.endswith("err=FetchError")
                for m in LOGS
            )
            and not any("503" in m for m in LOGS),
            "抓取失败日志只记 URL 与异常类型",
        )

        # 行数下降：beat 拒收，首次导入不查
        half = sh_parts(SH1[:2], [])
        f_half = sync.Fetched("sse_list", half)
        sp = c.begin_nested()
        rej = sync.take_snapshot(
            c, f_half, cfg, trade_date=D4, now=at(D4, "19:00"), raw_root=ROOT, check_drop=True
        )
        sp.rollback()
        sp = c.begin_nested()
        okb = sync.take_snapshot(
            c, f_half, cfg, trade_date=D4, now=at(D4, "19:00"), raw_root=ROOT, check_drop=False
        )
        sp.rollback()
        check(
            rej.status == "rejected" and rej.reason == "drop_pct" and okb.status == "ok",
            "拒收 drop_pct：beat 查行数下降，首次导入不查",
        )

        # 07:30 补拉（worker 任务，SAVEPOINT 代替提交）
        class FakeEng:
            def __init__(self, conn: Connection) -> None:
                self.c = conn

            @contextmanager
            def connect(self) -> Iterator[Connection]:
                yield self.c

            @contextmanager
            def begin(self) -> Iterator[Connection]:
                s = self.c.begin_nested()
                try:
                    yield self.c
                except BaseException:
                    s.rollback()
                    raise
                s.commit()

        TD = sync.snapshot_trade_date(dt.datetime.now(dt.UTC))
        run(
            c,
            world(bse_list=FetchError("x")),
            TD,
            srcs=["sse_list", "sse_delist", "szse_list", "szse_delist", "szse_rename", "bse_list"],
        )
        orig_engine, orig_fetcher = jobs._engine, jobs._master_fetcher
        jobs._engine = lambda s: FakeEng(c)  # type: ignore[assignment,return-value]
        jobs._master_fetcher = lambda: fetcher_of(world())  # type: ignore[assignment]
        try:
            CALLS.clear()
            n = jobs.sync_exchange_lists_task(settings, trigger="beat_0730")
            check(CALLS == ["bse_list"] and n == 1, f"07:30 补拉只拉 18:00 没成功的来源（{CALLS}）")
            CALLS.clear()
            check(
                jobs.sync_exchange_lists_task(settings, trigger="beat_0730") == 0 and CALLS == [],
                "全部成功后 07:30 不再抓取",
            )
            jobs._master_fetcher = lambda: fetcher_of(dict.fromkeys(world(), FetchError("x")))  # type: ignore[assignment]
            try:
                jobs.sync_exchange_lists_task(settings, trigger="manual")
                raised = False
            except jobs.MasterSyncFailedError:
                raised = True
            last = c.execute(
                text("select status from market.master_runs order by id desc limit 1")
            ).scalar()
            check(
                raised and last == "failed",
                "所有来源失败 → master_runs.status=failed 并抛错（触发重试）",
            )
        finally:
            jobs._engine, jobs._master_fetcher = orig_engine, orig_fetcher  # type: ignore[assignment]

        # 首次导入 CLI：不排任何任务
        rds.flushdb()
        res = master_bootstrap.run(
            c, settings, fetcher_of(world()), now=at(dt.date(2025, 3, 10), "19:00")
        )
        check(
            res.status == "ok"
            and rds.llen(jobs.QUEUE_KEY) == 0
            and rds.zcard(jobs.DELAYED_KEY) == 0,
            "运维①：首次导入运行后队列与延迟队列都为空（未触发 reconcile_vendor）",
        )

        # 清理 90 天前的原始文件
        old_rel = "sse_list/old.json"
        (ROOT / "sse_list").mkdir(parents=True, exist_ok=True)
        (ROOT / old_rel).write_bytes(b"{}")
        orphan = ROOT / "szse_list" / "orphan.json"
        orphan.parent.mkdir(parents=True, exist_ok=True)
        orphan.write_bytes(b"{}")
        old_ts = (dt.datetime.now(dt.UTC) - dt.timedelta(days=100)).timestamp()
        os.utime(orphan, (old_ts, old_ts))
        sid = c.execute(
            text(
                "insert into market.master_snapshots (source, url, fetched_at, trade_date, sha256, parse_status, raw_path) values ('sse_list', 'https://x', now() - interval '100 days', current_date - 100, :sha, 'ok', :p) returning id"
            ),
            {"sha": "b" * 64, "p": old_rel},
        ).scalar()
        fresh = sync.take_snapshot(
            c,
            sync.Fetched("sse_list", sh_parts([("603906", "测新庚")], STAR)),
            cfg,
            trade_date=TD,
            now=dt.datetime.now(BJT),
            raw_root=ROOT,
            check_drop=False,
        )
        keep = [
            c.execute(
                text("select raw_path from market.master_snapshots where id = :i"),
                {"i": fresh.snapshot_id},
            ).scalar()
        ]
        stale = [p for p in raws if p]
        n = sync.purge_snapshots(c, ROOT)
        check(
            n >= 2 and not (ROOT / old_rel).exists() and not orphan.exists(),
            "90 天前的原始文件与过期孤儿文件被删",
        )
        check(
            c.execute(
                text("select raw_path from market.master_snapshots where id = :i"), {"i": sid}
            ).scalar()
            is None,
            "被清理快照的 raw_path 置空",
        )
        check(
            keep and all((ROOT / p).is_file() for p in keep),
            f"90 天内的原始文件保留（{len(keep)} 份）",
        )
        check(
            not any((ROOT / p).exists() for p in stale if p not in keep),
            "2025-03 的自检快照文件（> 90 天）一并清理",
        )
        try:
            sync.purge_snapshots(c, ROOT / "nope")
            check(False, "根目录不存在 → 报错")
        except sync.MasterRootMissingError as exc:
            check("nope" not in str(exc), "根目录不存在 → MasterRootMissingError（消息不含路径）")
    finally:
        tx.rollback()

check(
    engine().connect().execute(text("select count(*) from market.master_runs")).scalar() == 0,
    "自检事务已回滚（master_runs 无残留）",
)

# ---------------------------------------------------------------- beat 钟点 / 重试 / 锁 / 对账链（Redis）
rds.flushdb()


def slots(day: dt.date, hhmm: str) -> list[tuple[str, dict[str, Any]]]:
    return [(t, a) for t, _, a in jobs.slot_jobs(settings, at(day, hhmm))]


MON, TUE, SAT, SUN = (
    dt.date(2026, 11, 2),
    dt.date(2026, 11, 3),
    dt.date(2026, 11, 7),
    dt.date(2026, 11, 8),
)
check(
    slots(MON, "18:00") == [(jobs.SYNC_LISTS, {"trigger": "beat_1800"})]
    and slots(MON, "18:14") == slots(MON, "18:00")
    and slots(MON, "18:15") == [],
    "周一 18:00–18:15 → 三所列表 beat_1800",
)
check(
    slots(MON, "07:30") == []
    and slots(TUE, "07:31") == [(jobs.SYNC_LISTS, {"trigger": "beat_0730"})]
    and slots(SAT, "07:30") != []
    and slots(SUN, "07:30") == [],
    "07:30 补拉只在周二至周六",
)
check(
    slots(SAT, "18:00") == [] and slots(SUN, "03:30") == [(jobs.PURGE_SNAPSHOTS, {})],
    "周六 18:00 不拉；每天 03:30 清理原始快照",
)
check(
    slots(MON, "18:30") == [(jobs.SYNC_CODE_MAP, {"trigger": "beat_1800"})]
    and slots(TUE, "18:30") == [],
    "每月第一个工作日 18:30 拉北交所代码对照",
)
q1 = jobs.beat_slots(settings, rds, at(MON, "18:01"))
q2 = jobs.beat_slots(settings, rds, at(MON, "18:05"))
check(q1 == [jobs.SYNC_LISTS] and q2 == [], "同一钟点只排一次（beat:slot 去重）")
body = json.loads(rds.lindex(jobs.QUEUE_KEY, 0))
check(
    body["task"] == jobs.SYNC_LISTS
    and body["args"] == {"trigger": "beat_1800"}
    and "attempt" not in body,
    "队列元素带 args.trigger",
)
rds.flushdb()

calls: list[dict[str, Any]] = []
finals: list[str] = []


def boom(s: Settings, **kw: Any) -> int:  # noqa: ANN401
    calls.append(kw)
    raise RuntimeError("x")


def okay(s: Settings, **kw: Any) -> int:  # noqa: ANN401
    calls.append(kw)
    return 1


orig_task, orig_final = jobs.TASKS[jobs.SYNC_LISTS], jobs.RETRY_TASKS[jobs.SYNC_LISTS]
jobs.TASKS[jobs.SYNC_LISTS] = boom
jobs.RETRY_TASKS[jobs.SYNC_LISTS] = lambda s, a, e: finals.append(type(e).__name__)
try:
    jobs._push(rds, jobs.SYNC_LISTS, {"trigger": "beat_1800"})
    check(
        jobs.worker_tick(settings, rds) == [(jobs.SYNC_LISTS, "failed")]
        and rds.zcard(jobs.DELAYED_KEY) == 1,
        "第 1 次失败 → 进延迟队列",
    )
    t_now = dt.datetime.now(dt.UTC)
    check(jobs.beat_slots(settings, rds, t_now) == [], "10 分钟内不放回")
    check(
        jobs.beat_slots(settings, rds, t_now + dt.timedelta(seconds=601)) == [jobs.SYNC_LISTS],
        "10 分钟后 beat 放回队列",
    )
    jobs.worker_tick(settings, rds)
    jobs.beat_slots(settings, rds, t_now + dt.timedelta(seconds=1300))
    jobs.worker_tick(settings, rds)
    check(
        len(calls) == 3 and finals == ["RuntimeError"] and rds.zcard(jobs.DELAYED_KEY) == 0,
        "共 3 次后停止重试，并调用失败记录（master_runs failed）",
    )
    check(all(k == {"trigger": "beat_1800"} for k in calls), "重试保留 trigger")
    rds.set(jobs.LOCK_PREFIX + jobs.SYNC_LISTS, "other")
    jobs._push(rds, jobs.SYNC_LISTS, {"trigger": "manual"})
    check(
        jobs.worker_tick(settings, rds) == [(jobs.SYNC_LISTS, "locked")] and len(calls) == 3,
        "持锁时跳过（不重复运行）",
    )
    rds.delete(jobs.LOCK_PREFIX + jobs.SYNC_LISTS)
    jobs.TASKS[jobs.SYNC_LISTS] = okay
    recon: list[dict[str, Any]] = []
    jobs.TASKS[jobs.RECONCILE_VENDOR] = lambda s, **kw: recon.append(kw) or 0
    jobs._push(rds, jobs.SYNC_LISTS, {"trigger": "beat_1800"})
    done = jobs.worker_tick(settings, rds)
    check(
        [t for t, _ in done] == [jobs.SYNC_LISTS, jobs.RECONCILE_VENDOR]
        and recon == [{"trigger": "beat_1800"}]
        and not rds.exists(jobs.LOCK_PREFIX + jobs.SYNC_LISTS),
        "beat 触发成功后接着跑 reconcile_vendor（已注册时），锁已释放",
    )
    jobs._push(rds, jobs.SYNC_LISTS, {"trigger": "manual"})
    done = jobs.worker_tick(settings, rds)
    check([t for t, _ in done] == [jobs.SYNC_LISTS] and len(recon) == 1, "非 beat 触发不排对账")
finally:
    jobs.TASKS[jobs.SYNC_LISTS] = orig_task
    jobs.RETRY_TASKS[jobs.SYNC_LISTS] = orig_final
    jobs.TASKS.pop(jobs.RECONCILE_VENDOR, None)
check(jobs.RECONCILE_VENDOR not in jobs.TASKS, "T-B53 前 reconcile_vendor 未注册")
rds.flushdb()
finish()
