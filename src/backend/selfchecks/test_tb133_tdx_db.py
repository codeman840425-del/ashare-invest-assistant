# ruff: noqa: S101, ANN401, E501, PT018, S608
"""T-B133：迁移 0033 / 0034 与通达信导入的连库自检（合成样本，不用真实样本）。

契约只读参照 ``git show 362ad41:docs/contracts/daily-bars-tdx.md`` §4、§6、§8 与
``git show 362ad41:docs/contracts/intraday-bars.md`` §1.3、§2.2、§5.1 M1/M2。
隔离 PG：仅在 o61-pg 127.0.0.1:55461 自建临时库 ``o61_tmp_b133_*``，用后删除（DROP DATABASE）。
不连接、不删除其他库；不起实例、不 down -v；不出网、不调用麦蕊。
"""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import re
import uuid
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from psycopg import sql
from sqlalchemy import create_engine, insert, select, text
from sqlalchemy.engine import URL, Engine
from sqlalchemy.exc import IntegrityError

from app.cli import tdx_import
from app.db.migration_check import require_single_head, script_directory
from app.db.tables.market import daily_bars, minute5_bars, minute_bars, trading_calendar
from app.db.tables.realtime import pipeline_runs
from app.ingest.tdx_local import BEIJING
from app.marketdata.daily_snapshot import _load_bars
from selfchecks.test_tb127_daily_bars import _admin, _downgrade, _require_o61, _upgrade, _url
from selfchecks.test_tb133_tdx_local import good_day, lc_rec, make_root, open_days, write

_SAFE_TMP = re.compile(r"^o61_tmp_b133_[a-z0-9]+$")
FORBIDDEN_DBS = frozenset({"tt51_tpl", "o61_tmp_0030", "o61_tmp_0029", "tb70_replay"})
NOW = dt.datetime(2026, 11, 10, 20, 0, tzinfo=BEIJING)


@contextlib.contextmanager
def temp_db() -> Iterator[URL]:
    _require_o61()
    name = "o61_tmp_b133_" + uuid.uuid4().hex[:10]
    assert _SAFE_TMP.fullmatch(name) and name not in FORBIDDEN_DBS
    with _admin() as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        yield _url(name)
    finally:
        assert _SAFE_TMP.fullmatch(name)
        with _admin() as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )


@pytest.fixture(scope="module")
def head_db() -> Iterator[Engine]:
    with temp_db() as url:
        _upgrade(url, "head")
        engine = create_engine(url)
        try:
            yield engine
        finally:
            engine.dispose()


def _version(engine: Engine) -> str:
    with engine.connect() as conn:
        return str(conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one())


def _daily_row(code: str, day: dt.date, source: str | None) -> dict[str, Any]:
    return {
        "code": code,
        "trade_date": day,
        "adj_type": "none",
        "open": 1,
        "high": 1,
        "low": 1,
        "close": 1,
        "source": source,
    }


def _minute_row(code: str, ts: dt.datetime, source: str | None) -> dict[str, Any]:
    return {"code": code, "ts": ts, "open": 1, "high": 1, "low": 1, "close": 1, "source": source}


def test_single_head_is_0034() -> None:
    assert require_single_head(script_directory()) == "0034"


def test_migration_0033_allows_tdx_local() -> None:
    with temp_db() as url:
        _upgrade(url, "0033")
        engine = create_engine(url)
        try:
            assert _version(engine) == "0033"
            with engine.begin() as conn:
                conn.execute(
                    insert(daily_bars).values(
                        **_daily_row("600000.SH", dt.date(2023, 1, 3), "tdx_local")
                    )
                )
            with pytest.raises(IntegrityError), engine.begin() as conn:
                conn.execute(
                    insert(daily_bars).values(
                        **_daily_row("600000.SH", dt.date(2023, 1, 4), "bogus")
                    )
                )
            with pytest.raises(RuntimeError, match="refusing downgrade 0033"):
                _downgrade(url, "0032")
            assert _version(engine) == "0033"
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM market.daily_bars WHERE source = 'tdx_local'"))
                conn.execute(
                    insert(daily_bars).values(
                        **_daily_row("600000.SH", dt.date(2023, 1, 5), "mairui")
                    )
                )
            _downgrade(url, "0032")
            assert _version(engine) == "0032"
            with pytest.raises(IntegrityError), engine.begin() as conn:
                conn.execute(
                    insert(daily_bars).values(
                        **_daily_row("600000.SH", dt.date(2023, 1, 6), "tdx_local")
                    )
                )
        finally:
            engine.dispose()


def test_migration_0034_minute_bars_source_and_licence(head_db: Engine) -> None:
    ts = dt.datetime(2026, 11, 2, 9, 31, tzinfo=BEIJING)
    with head_db.begin() as conn:
        for n, source in enumerate(("mairui", "tdx_local", "pro_latest", None)):
            conn.execute(insert(minute_bars).values(**_minute_row(f"60000{n}.SH", ts, source)))
        cols = {
            r.column_name: r.is_nullable
            for r in conn.execute(
                text(
                    "SELECT column_name, is_nullable FROM information_schema.columns WHERE table_schema='market' AND table_name='minute_bars'"
                )
            )
        }
        assert cols["source_licence_id"] == "YES"
        pk = conn.execute(
            text(
                "SELECT array_agg(a.attname ORDER BY k.ord) FROM pg_index i "
                "JOIN LATERAL unnest(i.indkey) WITH ORDINALITY k(attnum, ord) ON true "
                "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum "
                "WHERE i.indrelid = 'market.minute_bars'::regclass AND i.indisprimary"
            )
        ).scalar_one()
        assert pk == ["code", "ts"]
        conn.execute(text("DELETE FROM market.minute_bars"))
    with pytest.raises(IntegrityError), head_db.begin() as conn:
        conn.execute(insert(minute_bars).values(**_minute_row("600000.SH", ts, "bogus")))


def test_migration_0034_minute5_bars_hypertable(head_db: Engine) -> None:
    with head_db.connect() as conn:
        dim = conn.execute(
            text(
                "SELECT column_name, time_interval FROM timescaledb_information.dimensions "
                "WHERE hypertable_schema='market' AND hypertable_name='minute5_bars'"
            )
        ).one()
        assert dim.column_name == "ts" and dim.time_interval == dt.timedelta(days=7)
        pk = conn.execute(
            text(
                "SELECT array_agg(a.attname ORDER BY k.ord) FROM pg_index i "
                "JOIN LATERAL unnest(i.indkey) WITH ORDINALITY k(attnum, ord) ON true "
                "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum "
                "WHERE i.indrelid = 'market.minute5_bars'::regclass AND i.indisprimary"
            )
        ).scalar_one()
        assert pk == ["code", "ts"]


def test_migration_up_down_up_and_0034_downgrade_refuses_with_rows() -> None:
    with temp_db() as url:
        _upgrade(url, "head")
        engine = create_engine(url)
        try:
            assert _version(engine) == "0034"
            _downgrade(url, "0032")
            assert _version(engine) == "0032"
            _upgrade(url, "head")
            assert _version(engine) == "0034"
            ts = dt.datetime(2026, 11, 2, 9, 35, tzinfo=BEIJING)
            for table, source in (
                (minute_bars, "tdx_local"),
                (minute_bars, "mairui"),
                (minute5_bars, "tdx_local"),
            ):
                with engine.begin() as conn:
                    conn.execute(insert(table).values(**_minute_row("600000.SH", ts, source)))
                with pytest.raises(RuntimeError, match="refusing downgrade 0034"):
                    _downgrade(url, "0033")
                assert _version(engine) == "0034"
                with engine.begin() as conn:
                    conn.execute(text(f"DELETE FROM market.{table.name}"))
            with engine.begin() as conn:
                conn.execute(
                    insert(minute_bars).values(**_minute_row("600000.SH", ts, "pro_latest"))
                )
            _downgrade(url, "0033")
            assert _version(engine) == "0033"
            _upgrade(url, "head")
            assert _version(engine) == "0034"
        finally:
            engine.dispose()


class _Deps(tdx_import.DbDeps):
    """真实库读写，只把 owned 与推荐 D 固定（不播种用户 / 持仓 / 3 年日历）。"""

    owned = frozenset({"600000.SH", "000001.SZ"})
    recommended = dt.date(2023, 11, 9)

    def owned_codes(self, now_bj: dt.datetime) -> frozenset[str]:
        return self.owned

    def recommended_daily_until(self, now_bj: dt.datetime) -> dt.date | None:
        return self.recommended


def _seed(engine: Engine, days: list[dt.date]) -> None:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM market.daily_bars"))
        conn.execute(text("DELETE FROM market.minute_bars"))
        conn.execute(text("DELETE FROM market.minute5_bars"))
        conn.execute(text("DELETE FROM market.trading_calendar"))
        conn.execute(
            text(
                "DELETE FROM market.securities WHERE code IN ('600000.SH','000001.SZ','000001.SH')"
            )
        )
        conn.execute(text("DELETE FROM app.pipeline_runs WHERE step LIKE 'tdx_local.%'"))
        start, end = min(days) - dt.timedelta(10), dt.date(2026, 11, 11)
        conn.execute(
            insert(trading_calendar),
            [
                {
                    "date": start + dt.timedelta(n),
                    "is_open": (start + dt.timedelta(n)).weekday() < 5,
                }
                for n in range((end - start).days + 1)
            ],
        )
        conn.execute(
            text(
                "INSERT INTO market.securities (code, type, name, exchange, listing_status) VALUES "
                "('600000.SH','stock','合成甲','SH','listed'),('000001.SZ','stock','合成乙','SZ','listed'),"
                "('000001.SH','index','合成指数','SH','listed')"
            )
        )


def _cli(fn: Any, engine: Engine, argv: list[str]) -> tuple[int, dict[str, str]]:
    buf = io.StringIO()
    with engine.begin() as conn, contextlib.redirect_stdout(buf):
        code = fn(argv, now=NOW, deps=_Deps(conn), run_id=uuid.uuid4().hex[:8])
    out = {}
    for line in buf.getvalue().splitlines():
        key, _, value = line.partition("=")
        out[key] = value
    return code, out


def test_tdx_daily_apply_do_nothing_idempotent_and_snapshot_excludes(
    head_db: Engine, tmp_path: Path
) -> None:
    days = open_days(dt.date(2023, 10, 2), dt.date(2023, 10, 13))
    _seed(head_db, days)
    root = make_root(tmp_path)
    write(root, "sh/lday/sh600000.day", b"".join(good_day(d) for d in days))
    write(root, "sh/lday/sh000001.day", b"".join(good_day(d) for d in days))
    with head_db.begin() as conn:
        conn.execute(
            insert(daily_bars).values(
                code="600000.SH",
                trade_date=days[0],
                adj_type="none",
                open=Decimal("10"),
                high=Decimal("10.2"),
                low=Decimal("9.8"),
                close=Decimal("10.11"),
                volume=Decimal(100000),
                amount=Decimal(1005000),
                source="mairui",
            )
        )
    audit = tmp_path / "audit"
    audit.mkdir()
    # dry-run：零写入
    code, out = _cli(
        tdx_import.daily_main,
        head_db,
        ["--root", str(root), "--audit-dir", str(audit), "--until", "2023-11-09"],
    )
    assert code == 0 and out["would_insert"] == str(len(days) - 1) and out["conflicts"] == "1"
    with head_db.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM market.daily_bars")).scalar_one() == 1
        assert (
            conn.execute(
                text("SELECT count(*) FROM app.pipeline_runs WHERE step LIKE 'tdx_local.%'")
            ).scalar_one()
            == 0
        )
    code, out = _cli(
        tdx_import.daily_main,
        head_db,
        ["--root", str(root), "--audit-dir", str(audit), "--until", "2023-11-09", "--apply"],
    )
    assert (
        code == 0
        and out["inserted"] == str(len(days) - 1)
        and out["skipped"] == str({"non_a_share": 1})
    )
    with head_db.connect() as conn:
        rows = conn.execute(select(daily_bars).order_by(daily_bars.c.trade_date)).all()
        assert len(rows) == len(days)
        assert rows[0].source == "mairui" and rows[0].close == Decimal("10.1100")  # 原行不变
        assert {r.source for r in rows[1:]} == {"tdx_local"}
        assert all(
            r.is_suspended is None and r.pre_close is None and r.source_licence_id is None
            for r in rows[1:]
        )
        run = conn.execute(
            select(pipeline_runs).where(pipeline_runs.c.step == "tdx_local.import_day")
        ).one()
        assert run.status == "ok" and run.stats["conflicts"] == 1 and run.stats["manifest_sha256"]
        loaded = _load_bars(
            conn, ["600000.SH"], days[-1]
        )  # daily-bars-tdx §4：快照侧排除 tdx_local
        assert [r.trade_date for r in loaded["600000.SH"]] == [days[0]]
    code, out = _cli(
        tdx_import.daily_main,
        head_db,
        ["--root", str(root), "--audit-dir", str(audit), "--until", "2023-11-09", "--apply"],
    )
    assert (
        code == 0
        and out["inserted"] == "0"
        and out["rerun"] == str({"added": 0, "removed": 0, "changed": 0})
    )
    with head_db.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM market.daily_bars")).scalar_one() == len(
            days
        )


def test_lc_apply_tables_and_until_before_first_mairui(head_db: Engine, tmp_path: Path) -> None:
    days = open_days(dt.date(2026, 11, 2), dt.date(2026, 11, 10))
    _seed(head_db, days)
    first_mairui = dt.datetime(2026, 11, 5, 9, 31, tzinfo=BEIJING)
    with head_db.begin() as conn:
        conn.execute(insert(minute_bars).values(**_minute_row("600000.SH", first_mairui, "mairui")))
    root = tmp_path / "root"
    for market in ("sh", "sz", "bj"):
        for sub in ("minline", "fzline"):
            (root / market / sub).mkdir(parents=True)
    lc1 = b"".join(lc_rec(d, m, 9.5, 9.5, 9.5, 9.5, 950, 100) for d in days for m in (571, 572))
    lc5 = b"".join(lc_rec(d, 575, 9.5, 9.5, 9.5, 9.5, 950, 100) for d in days)
    write(root, "sh/minline/sh600000.lc1", lc1)
    write(root, "sh/fzline/sh600000.lc5", lc5)
    for kind in ("lc1", "lc5"):
        audit = tmp_path / f"audit_{kind}"
        audit.mkdir()
        code, out = _cli(
            tdx_import.intraday_main,
            head_db,
            ["--kind", kind, "--root", str(root), "--audit-dir", str(audit), "--apply"],
        )
        assert code == 0, out
    with head_db.connect() as conn:
        one = conn.execute(
            select(minute_bars)
            .where(minute_bars.c.source == "tdx_local")
            .order_by(minute_bars.c.ts)
        ).all()
        five = conn.execute(select(minute5_bars).order_by(minute5_bars.c.ts)).all()
    # 已有 mairui 起于 11-05 → 1 分钟与 5 分钟都只导到 11-04；.lc5 只进 minute5_bars。
    assert {r.ts.astimezone(BEIJING).date() for r in one} == {
        dt.date(2026, 11, 2),
        dt.date(2026, 11, 3),
        dt.date(2026, 11, 4),
    }
    assert len(one) == 6 and all(
        r.ts.astimezone(BEIJING).time() in (dt.time(9, 31), dt.time(9, 32)) for r in one
    )
    assert len(five) == 3 and {r.source for r in five} == {"tdx_local"}
    assert five[0].ts == dt.datetime(2026, 11, 2, 9, 35, tzinfo=BEIJING)
    with head_db.connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM market.minute_bars WHERE source='mairui'")
            ).scalar_one()
            == 1
        )
    for kind in ("lc1", "lc5"):
        audit = tmp_path / f"audit2_{kind}"
        audit.mkdir()
        code, out = _cli(
            tdx_import.intraday_main,
            head_db,
            ["--kind", kind, "--root", str(root), "--audit-dir", str(audit), "--apply"],
        )
        assert code == 0 and out["inserted"] == "0"
