# ruff: noqa: E501, S608  自检脚本：检查描述保持单行；表名来自本文件常量
"""T-B51 自检（隔离 PG，见 ``_common``；只建表、不灌数据，不调用任何外部接口）：

- 迁移 0019 可升可降：降到 0018 恢复旧结构（旧 gin 索引、旧主键），再升回 head；
- 升级预检查：旧代码表有行 → 中文报错、不改结构；降级预检查：新表有数据 → 中文报错、不删数据；
- 有效期重叠写入被 ``EXCLUDE USING gist`` 拒绝（4 张历史表），相邻半开区间允许；
- 其他约束：快照 sha256 / ok 无 reject_reason、对账差异证书只属 mairui_*、field 只属 field_mismatch、
  开放差异部分唯一（NULLS NOT DISTINCT）、resolved 后可再开、词条 unique 与 ST 去除标记；
- 索引：旧 gin 已删、新 btree / text_pattern_ops / 部分 trgm 存在。
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _common import check, engine, finish, q
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

BACKEND = Path(__file__).resolve().parents[1]
CODE = q("select code from market.securities order by code limit 1").scalar_one()
SHA = "a" * 64


def alembic(*args: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "MAIRUI_LICENCE"}
    return subprocess.run(  # noqa: S603
        [str(BACKEND / ".venv/bin/alembic"), *args],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def head() -> str:
    return alembic("current").stdout.strip().split()[0]


def indexes(table: str) -> set[str]:
    return set(
        q(
            "select indexname from pg_indexes where schemaname = 'market' and tablename = :t",
            t=table,
        ).scalars()
    )


def rejects(sql: str, exc: type[Exception] = IntegrityError, **params: object) -> bool:
    """在一个回滚的事务里执行；被约束拒绝返回 True。"""
    with engine().connect() as c:
        tx = c.begin()
        try:
            c.execute(text(sql), params)
        except exc:
            tx.rollback()
            return True
        tx.rollback()
        return False


def in_tx(fn: Callable[..., object]) -> object:
    with engine().connect() as c:
        tx = c.begin()
        try:
            return fn(c)
        finally:
            tx.rollback()


# ---------------------------------------------------------------- 结构
check(head() == "0019", f"迁移在 head 0019（得 {head()}）")
check(
    q("select count(*) from pg_extension where extname in ('btree_gist', 'pg_trgm')").scalar_one()
    == 2,
    "扩展 btree_gist 与 pg_trgm 都在",
)
cols = set(
    q(
        "select column_name from information_schema.columns where table_schema = 'market' and table_name = 'securities'"
    ).scalars()
)
check(
    {"missing_since", "last_seen_on", "field_sources"} <= cols,
    "securities 加了 missing_since / last_seen_on / field_sources",
)
ix = indexes("securities")
check(
    "ix_securities_exchange_listing_status" in ix
    and "ix_securities_name_norm_trgm" not in ix
    and "ix_securities_name_initials" not in ix,
    "securities：新 btree (exchange, listing_status)，旧 gin 索引已删",
)
for t in (
    "security_name_history",
    "security_code_history",
    "security_risk_flag_history",
    "security_listing_status_history",
):
    pk = q(
        "select pg_get_constraintdef(oid) from pg_constraint where conrelid = cast(:t as regclass) and contype = 'p'",
        t=f"market.{t}",
    ).scalar_one()
    ex = q(
        "select count(*) from pg_constraint where conrelid = cast(:t as regclass) and contype = 'x'",
        t=f"market.{t}",
    ).scalar_one()
    check(
        pk == "PRIMARY KEY (code, valid_from)" and ex == 1,
        f"{t}：PK (code, valid_from) + 1 个排除约束",
    )
check(
    "ix_security_name_history_name" in indexes("security_name_history")
    and "ix_security_name_history_name_norm_trgm" not in indexes("security_name_history"),
    "name_history：btree(name)，旧 trgm 已删",
)
st = indexes("security_search_terms")
check(
    {
        "ix_security_search_terms_term_pattern",
        "ix_security_search_terms_term_trgm",
        "ix_security_search_terms_code",
    }
    <= st,
    "search_terms：text_pattern_ops / 部分 trgm / code 索引",
)
trgm_def = q(
    "select indexdef from pg_indexes where indexname = 'ix_security_search_terms_term_trgm'"
).scalar_one()
check(
    "gin_trgm_ops" in trgm_def and "WHERE" in trgm_def and "former_name" in trgm_def,
    "trgm 只覆盖 name / former_name（部分索引）",
)
uq_def = q(
    "select indexdef from pg_indexes where indexname = 'uq_security_reconciliation_diffs_open'"
).scalar_one()
check(
    "NULLS NOT DISTINCT" in uq_def and "status = 'open'" in uq_def,
    "对账差异开放部分唯一 NULLS NOT DISTINCT",
)
check(
    all(
        q(f"select count(*) from market.{t}").scalar_one() == 0
        for t in (
            "master_snapshots",
            "master_runs",
            "security_search_terms",
            "security_reconciliation_diffs",
            "security_listing_status_history",
        )
    ),
    "迁移不灌数据：新表为空",
)


# ---------------------------------------------------------------- 有效期重叠被拒
def snap(c: object) -> int:
    return c.execute(  # type: ignore[attr-defined]
        text(
            "insert into market.master_snapshots (source, url, fetched_at, trade_date, row_count, sha256, parse_status) "
            "values ('szse_rename', 'https://example.invalid/list.xlsx', now(), date '2026-10-30', 3, :s, 'ok') returning id"
        ),
        {"s": SHA},
    ).scalar_one()


HIST = {
    "security_name_history": ("name, source", "'虚构甲', 'exchange_diff'"),
    "security_code_history": ("old_code, source", "'830001.BJ', 'bse_code_map'"),
    "security_risk_flag_history": ("risk_flag", "'st'"),
    "security_listing_status_history": ("listing_status, reason", "'listed', 'exchange_list'"),
}
for t, (cs, vs) in HIST.items():

    def run(c: object, t: str = t, cs: str = cs, vs: str = vs) -> tuple[bool, bool, bool, bool]:
        c.execute(  # type: ignore[attr-defined]
            text(
                f"insert into market.{t} (code, valid_from, valid_until, {cs}) values (:c, date '2020-01-01', date '2021-01-01', {vs})"
            ),
            {"c": CODE},
        )
        vs2 = vs.replace("830001.BJ", "830002.BJ")
        vs3 = vs.replace("830001.BJ", "830003.BJ")
        vs4 = vs.replace("830001.BJ", "830004.BJ")
        # 相邻（半开区间首尾相接）允许
        sp = c.begin_nested()  # type: ignore[attr-defined]
        try:
            c.execute(
                text(
                    f"insert into market.{t} (code, valid_from, valid_until, {cs}) values (:c, date '2021-01-01', null, {vs2})"
                ),
                {"c": CODE},
            )  # type: ignore[attr-defined]
            adjacent_ok = True
            sp.commit()
        except DBAPIError:
            sp.rollback()
            adjacent_ok = False
        # 与 [2020-01-01, 2021-01-01) 重叠
        sp = c.begin_nested()  # type: ignore[attr-defined]
        try:
            c.execute(
                text(
                    f"insert into market.{t} (code, valid_from, valid_until, {cs}) values (:c, date '2020-06-01', date '2020-07-01', {vs3})"
                ),
                {"c": CODE},
            )  # type: ignore[attr-defined]
            overlap_rejected = False
            sp.commit()
        except DBAPIError as e:
            sp.rollback()
            overlap_rejected = f"ex_{t}_period" in str(e.orig)
        # 与开放区间 [2021-01-01, ∞) 重叠
        sp = c.begin_nested()  # type: ignore[attr-defined]
        try:
            c.execute(
                text(
                    f"insert into market.{t} (code, valid_from, valid_until, {cs}) values (:c, date '2025-01-01', null, {vs4})"
                ),
                {"c": CODE},
            )  # type: ignore[attr-defined]
            open_rejected = False
            sp.commit()
        except DBAPIError as e:
            sp.rollback()
            open_rejected = f"ex_{t}_period" in str(e.orig)
        # 区间倒置
        sp = c.begin_nested()  # type: ignore[attr-defined]
        try:
            c.execute(
                text(
                    f"insert into market.{t} (code, valid_from, valid_until, {cs}) values (:c, date '2010-01-01', date '2009-01-01', {vs4})"
                ),
                {"c": CODE},
            )  # type: ignore[attr-defined]
            order_rejected = False
            sp.commit()
        except DBAPIError:
            sp.rollback()
            order_rejected = True
        return adjacent_ok, overlap_rejected, open_rejected, order_rejected

    a, o, op_, od = in_tx(run)  # type: ignore[misc]
    check(a, f"{t}：相邻半开区间允许")
    check(o, f"{t}：重叠区间写入被排除约束拒绝")
    check(op_, f"{t}：与开放区间（valid_until null）重叠被拒")
    check(od, f"{t}：valid_until <= valid_from 被拒")


def other_code_ok(c: object) -> bool:
    other = c.execute(
        text("select code from market.securities where code <> :c order by code limit 1"),
        {"c": CODE},
    ).scalar_one()  # type: ignore[attr-defined]
    for code in (CODE, other):
        c.execute(  # type: ignore[attr-defined]
            text(
                "insert into market.security_listing_status_history (code, listing_status, valid_from, reason) values (:c, 'listed', date '2020-01-01', 'exchange_list')"
            ),
            {"c": code},
        )
    return True


check(in_tx(other_code_ok), "不同代码的同期区间互不影响")


def name_with_snapshot(c: object) -> bool:
    sid = snap(c)
    c.execute(  # type: ignore[attr-defined]
        text(
            "insert into market.security_name_history (code, name, valid_from, source, snapshot_id) values (:c, '虚构乙', date '2020-01-01', 'szse_ssgsgmxx', :s)"
        ),
        {"c": CODE, "s": sid},
    )
    return True


check(in_tx(name_with_snapshot), "name_history 引用 master_snapshots.id")
check(
    rejects(
        "insert into market.security_name_history (code, name, valid_from, source, snapshot_id) values (:c, 'x', date '2020-01-01', 'exchange_diff', 999999999)",
        c=CODE,
    ),
    "snapshot_id 外键：不存在的快照被拒",
)
check(
    rejects(
        "insert into market.security_name_history (code, name, valid_from, source) values (:c, 'x', date '2020-01-01', 'mairui')",
        c=CODE,
    ),
    "name_history.source 只允许 szse_ssgsgmxx / exchange_diff",
)
check(
    rejects(
        "insert into market.security_code_history (code, old_code, valid_from, source) values (:c, :c, date '2020-01-01', 'bse_code_map')",
        c=CODE,
    ),
    "code_history：old_code = code 被拒",
)


def old_code_unique(c: object) -> bool:
    other = c.execute(
        text("select code from market.securities where code <> :c order by code limit 1"),
        {"c": CODE},
    ).scalar_one()  # type: ignore[attr-defined]
    c.execute(
        text(
            "insert into market.security_code_history (code, old_code, valid_from, source) values (:c, '839999.BJ', date '2020-01-01', 'bse_code_map')"
        ),
        {"c": CODE},
    )  # type: ignore[attr-defined]
    try:
        with c.begin_nested():  # type: ignore[attr-defined]
            c.execute(
                text(
                    "insert into market.security_code_history (code, old_code, valid_from, source) values (:c, '839999.BJ', date '2020-01-01', 'bse_code_map')"
                ),
                {"c": other},
            )  # type: ignore[attr-defined]
    except IntegrityError:
        return True
    return False


check(in_tx(old_code_unique), "code_history：old_code 全局唯一")

# ---------------------------------------------------------------- master_snapshots / master_runs
SNAP_SQL = (
    "insert into market.master_snapshots (source, url, fetched_at, trade_date, sha256, parse_status, reject_reason) "
    "values (:src, 'https://example.invalid/x', now(), date '2026-10-30', :sha, :ps, :rr)"
)
check(
    rejects(SNAP_SQL, src="sse_list", sha="xyz", ps="ok", rr=None),
    "snapshots：sha256 须 64 位小写十六进制",
)
check(
    rejects(SNAP_SQL, src="sse_list", sha=SHA, ps="ok", rr="empty"),
    "snapshots：parse_status=ok 不得带 reject_reason",
)
check(
    rejects(SNAP_SQL, src="mairui", sha=SHA, ps="ok", rr=None), "snapshots：source 限 10 个公开来源"
)
check(
    rejects(SNAP_SQL, src="sse_list", sha=SHA, ps="rejected", rr="too_small"),
    "snapshots：reject_reason 限 4 种",
)
check(
    not rejects(SNAP_SQL, src="sse_list", sha=SHA, ps="rejected", rr="drop_pct"),
    "snapshots：rejected + drop_pct 可写",
)


def dup_snapshot(c: object) -> bool:
    p = {"src": "bse_list", "sha": SHA, "ps": "ok", "rr": None}
    c.execute(text(SNAP_SQL), p)  # type: ignore[attr-defined]
    try:
        with c.begin_nested():  # type: ignore[attr-defined]
            c.execute(text(SNAP_SQL), p)  # type: ignore[attr-defined]
    except IntegrityError:
        return True
    return False


check(in_tx(dup_snapshot), "snapshots：(source, sha256) 唯一，同一文件不重复入库")
check(
    not rejects("insert into market.master_runs (trigger) values ('bootstrap')"),
    "master_runs：运行中 status 可为 null，snapshot_ids / stats 有默认值",
)
check(
    rejects("insert into market.master_runs (trigger) values ('cron')"),
    "master_runs：trigger 限 4 种",
)

# ---------------------------------------------------------------- 对账差异
DIFF_SQL = (
    "insert into market.security_reconciliation_diffs (kind, source, security_code, field, source_licence_id, first_seen_on, last_seen_on, status, resolved_on) "
    "values (:k, :s, :code, :f, :lic, date '2026-10-30', date '2026-10-30', :st, :ro)"
)
LIC = uuid.uuid4()
base = {
    "k": "vendor_unknown",
    "s": "mairui_lists",
    "code": "689999.SH",
    "f": None,
    "lic": LIC,
    "st": "open",
    "ro": None,
}
check(not rejects(DIFF_SQL, **base), "diffs：mairui_lists + 证书 id 可写（代码不必在 securities）")
check(rejects(DIFF_SQL, **{**base, "lic": None}), "diffs：mairui_* 必须带 source_licence_id")
check(rejects(DIFF_SQL, **{**base, "s": "cninfo"}), "diffs：非 mairui 来源不得带证书 id")
check(rejects(DIFF_SQL, **{**base, "f": "name"}), "diffs：非 field_mismatch 不得带 field")
check(
    rejects(DIFF_SQL, **{**base, "k": "field_mismatch", "s": "cninfo", "lic": None}),
    "diffs：field_mismatch 必须带 field",
)
check(
    rejects(DIFF_SQL, **{**base, "k": "field_mismatch", "s": "cninfo", "lic": None, "f": "price"}),
    "diffs：field 限 5 个主数据字段",
)
check(rejects(DIFF_SQL, **{**base, "st": "resolved"}), "diffs：resolved 必须带 resolved_on")
check(rejects(DIFF_SQL, **{**base, "ro": "2026-10-31"}), "diffs：open 不得带 resolved_on")


def open_unique(c: object) -> tuple[bool, bool, bool]:
    p = {**base, "k": "field_mismatch", "s": "cninfo", "lic": None, "f": "name"}
    c.execute(text(DIFF_SQL), p)  # type: ignore[attr-defined]
    try:
        with c.begin_nested():  # type: ignore[attr-defined]
            c.execute(text(DIFF_SQL), p)  # type: ignore[attr-defined]
        dup_rejected = False
    except IntegrityError:
        dup_rejected = True  # licence 为 null 也算相同（NULLS NOT DISTINCT）
    c.execute(
        text(
            "update market.security_reconciliation_diffs set status = 'resolved', resolved_on = date '2026-10-31' where security_code = '689999.SH'"
        )
    )  # type: ignore[attr-defined]
    with c.begin_nested():  # type: ignore[attr-defined]
        c.execute(text(DIFF_SQL), p)  # type: ignore[attr-defined]
    reopen_ok = True
    # 不同证书各自一条开放差异
    q2 = {**base}
    c.execute(text(DIFF_SQL), q2)  # type: ignore[attr-defined]
    c.execute(text(DIFF_SQL), {**q2, "lic": uuid.uuid4()})  # type: ignore[attr-defined]
    return dup_rejected, reopen_ok, True


d, r_, per_lic = in_tx(open_unique)  # type: ignore[misc]
check(d, "diffs：同键开放差异唯一（licence null 也视为相同）")
check(r_, "diffs：resolved 后同键可再开一条")
check(per_lic, "diffs：不同证书各自一条开放差异")

# ---------------------------------------------------------------- 词条
TERM_SQL = (
    "insert into market.security_search_terms (code, term_kind, term, source_name, is_st_stripped, variant_rank, generator_version) "
    "values (:c, :k, :t, '*ST虚构', true, :r, 1)"
)
check(rejects(TERM_SQL, c=CODE, k="pinyin", t="xg", r=0), "terms：term_kind 限 5 种")
check(rejects(TERM_SQL, c=CODE, k="name_initials", t="xg", r=-1), "terms：variant_rank 不得为负")


def term_dup(c: object) -> bool:
    c.execute(text(TERM_SQL), {"c": CODE, "k": "name_initials", "t": "xg", "r": 0})  # type: ignore[attr-defined]
    c.execute(text(TERM_SQL), {"c": CODE, "k": "name_initials", "t": "xj", "r": 1})  # type: ignore[attr-defined]
    try:
        with c.begin_nested():  # type: ignore[attr-defined]
            c.execute(text(TERM_SQL), {"c": CODE, "k": "name_initials", "t": "xg", "r": 2})  # type: ignore[attr-defined]
    except IntegrityError:
        return True
    return False


check(in_tx(term_dup), "terms：(code, term_kind, term, source_name) 唯一，多音字变体各一行")
check(rejects(TERM_SQL, c="000000.XX", k="name", t="x", r=0), "terms：code 外键到 securities")

# ---------------------------------------------------------------- 升降级
r = alembic("downgrade", "0018")
check(r.returncode == 0 and head() == "0018", f"降级到 0018 成功（rc={r.returncode}）")
ix = indexes("securities")
check(
    {"ix_securities_name_norm_trgm", "ix_securities_name_initials"} <= ix
    and "ix_securities_exchange_listing_status" not in ix,
    "0018：securities 旧 gin 索引恢复、新 btree 删除",
)
check(
    q(
        "select to_regclass('market.master_snapshots') is null and to_regclass('market.security_search_terms') is null"
    ).scalar_one(),
    "0018：新表已删",
)
check(
    q(
        "select pg_get_constraintdef(oid) from pg_constraint where conname = 'pk_security_code_history'"
    ).scalar_one()
    == "PRIMARY KEY (old_code)"
    and "ix_security_name_history_name_norm_trgm" in indexes("security_name_history"),
    "0018：旧主键 / 旧 trgm 索引恢复",
)
other = q(
    "select code from market.securities where code <> :c order by code limit 1", c=CODE
).scalar_one()
q("insert into market.security_code_history (old_code, code) values ('839998.BJ', :c)", c=other)
r = alembic("upgrade", "head")
check(
    r.returncode != 0
    and "0019 预检查失败" in r.stderr
    and "security_code_history" in r.stderr
    and head() == "0018",
    "升级预检查：旧代码表有行 → 中文报错、停在 0018",
)
q("delete from market.security_code_history where old_code = '839998.BJ'")
r = alembic("upgrade", "head")
check(r.returncode == 0 and head() == "0019", f"清空后升级回 0019（rc={r.returncode}）")
q("insert into market.master_runs (trigger) values ('manual')")
r = alembic("downgrade", "0018")
check(
    r.returncode != 0
    and "0019 降级拒绝" in r.stderr
    and "master_runs=1" in r.stderr
    and head() == "0019",
    "降级预检查：新表有数据 → 中文报错、停在 0019",
)
check(q("select count(*) from market.master_runs").scalar_one() == 1, "降级被拒时数据未删")
q("delete from market.master_runs")
r = alembic("check")
check(
    r.returncode == 0 and "No new upgrade operations" in (r.stdout + r.stderr),
    "alembic check：模型与库一致",
)
finish()
