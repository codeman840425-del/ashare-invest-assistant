"""T-T86 / PN-03 §12：十七个原入口逐一接线；仅虚构数据与隔离资源。
PR162 契约未合入；5个已确认实现FAIL以strict xfail关联T-B168，环境缺工具单列。D0–D3/代码全合成。
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import os
import random
import shutil
import socket
import struct
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from app.aggregates.calendar import market_clock, seed_calendar
from app.api.v1 import aggregates as aggregates_api
from app.auth import deps
from app.auth.deps import AuthContext
from app.cli import __main__ as cli_main
from app.cli import calendar_seed, tb143_export
from app.common.errors import AppError, ErrorCode, install_exception_handlers
from app.config import load_yaml_dir
from app.config_files import BusinessConfig
from app.db.tables.market import daily_bars, securities, trading_calendar
from app.db.tables.research import watchlist_items
from app.db.tables.reviews import data_snapshots
from app.db.tables.users import users
from app.features.pipeline import prepare
from app.ingest.tdx_local import DAY_LAYOUT
from app.marketdata.daily_snapshot import _sessions, build_owned_snapshot
from app.reference_files import CalendarReference
from app.reports.service import covered
from app.schemas.enums import MarketSession
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, insert, select

ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "src/backend"
D0, D1, D2, D3 = (dt.date(2030, 12, 30) + dt.timedelta(days=n) for n in range(4))
DAYS = (D0, D1, D2, D3)
CODE_A, CODE_B = "699001.SH", "920999.BJ"
BEIJING = dt.timezone(dt.timedelta(hours=8))
RULES = BusinessConfig.model_validate(load_yaml_dir(ROOT / "config")).market_rules
_RNG = random.Random(160)
KEYS = tuple(_RNG.getrandbits(32) for _ in range(1042))


def _at(day: dt.date, hour: int = 17, minute: int = 30) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(hour, minute), BEIJING)


def _seed(opens=(D0, D2), *, end=D2) -> CalendarReference:
    return CalendarReference(
        coverage_start=D0.isoformat(),
        coverage_end=end.isoformat(),
        open_days=[day.isoformat() for day in opens],
        source="fake",
    )


def _write_seed(directory: Path, value: CalendarReference) -> None:
    directory.mkdir(exist_ok=True)
    (directory / "trading_calendar.json").write_text(
        json.dumps(value.model_dump(), ensure_ascii=False), encoding="utf-8"
    )


@pytest.fixture(scope="session")
def pn03_engine(pg_url: str):
    """pg_url 只会返回测试容器/显式测试库；迁移参数不回落到 Settings/.env。"""
    config = Config(str(BACKEND / "alembic.ini"))
    config.cmd_opts = SimpleNamespace(x=[f"url={pg_url}"])
    command.upgrade(config, "head")
    engine = create_engine(pg_url)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def pn03_cleanup(pn03_engine):
    yield
    with pn03_engine.begin() as conn:
        conn.execute(delete(trading_calendar).where(trading_calendar.c.date.in_(DAYS)))


@pytest.fixture(autouse=True)
def pn03_no_external(monkeypatch):
    original = socket.socket.connect

    def guarded(sock, address):
        host = address[0] if isinstance(address, tuple) else address
        if isinstance(host, str) and (
            host in {"127.0.0.1", "localhost", "::1"} or host.startswith("/")
        ):
            return original(sock, address)
        pytest.fail(f"PN-03 禁止外呼：{host!r}")

    monkeypatch.setattr(socket.socket, "connect", guarded)
    from app.ingest import egress

    monkeypatch.setattr(
        egress, "mairui_get", lambda *a, **k: pytest.fail("禁止真调麦蕊")
    )


@pytest.fixture
def conn(pn03_engine):
    with pn03_engine.connect() as connection:
        transaction = connection.begin()
        yield connection
        transaction.rollback()


def _bar(
    code: str, day: dt.date, close="10", *, seen: dt.datetime | None = None
) -> dict:
    return {
        "code": code,
        "trade_date": day,
        "adj_type": "none",
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 100,
        "amount": 1000,
        "source": "fake",
        "fetched_at": seen or _at(day, 17, 15),
        "is_suspended": False,
    }


def _instrument(code=CODE_A, bars=(D0, D2)) -> dict:
    return {
        "security_code": code,
        "adjust": "none",
        "currency": "CNY",
        "price_unit": "CNY/share",
        "volume_unit": "share",
        "amount_unit": "CNY",
        "bars": [
            {
                **_bar(code, day, "10" if day == D0 else "20"),
                "trade_date": day.isoformat(),
                "first_seen_at": _at(day, 17, 15).isoformat(),
                "is_final": True,
            }
            for day in bars
        ],
        "gaps": [],
    }


def _prepare(*, factors=(), instrument=None, as_of=None):
    return prepare(
        instrument or _instrument(),
        [D0.isoformat(), D2.isoformat()],
        as_of=as_of or _at(D0),
        factors=list(factors),
        registry={},
    )


@pytest.mark.xfail(strict=True, reason="T-B168: seed_calendar 冲突未拒")
def test_pn03_entry_seed_calendar(conn) -> None:
    assert seed_calendar(conn, _seed()) == 3
    rows = conn.execute(
        select(trading_calendar).order_by(trading_calendar.c.date)
    ).all()
    assert [(row.date, row.is_open) for row in rows] == [
        (D0, True),
        (D1, False),
        (D2, True),
    ]
    with pytest.raises(ValueError):
        seed_calendar(conn, _seed(opens=(D2,)))
    assert (
        conn.execute(
            select(trading_calendar.c.is_open).where(trading_calendar.c.date == D0)
        ).scalar_one()
        is True
    )


def test_pn03_entry_market_clock(conn) -> None:
    seed_calendar(conn, _seed())
    closed = market_clock(conn, _at(D1, 12), RULES)
    assert (closed.trade_date, closed.session) == (D0, MarketSession.NON_TRADING_DAY)
    a = market_clock(conn, _at(D0, 9, 30), RULES)
    b = market_clock(conn, _at(D0, 9, 30).astimezone(dt.UTC), RULES)
    assert a == b
    conn.execute(delete(trading_calendar).where(trading_calendar.c.date == D1))
    for when in (_at(D1, 12), _at(D3, 12)):
        with pytest.raises(AppError) as caught:
            market_clock(conn, when, RULES)
        assert caught.value.code is ErrorCode.CALENDAR_NOT_COVERED


def test_pn03_entry_covered(conn) -> None:
    seed_calendar(conn, _seed())
    assert covered(conn, D0) is True and covered(conn, D1) is False
    with pytest.raises(AppError) as caught:
        covered(conn, D3)
    assert caught.value.details["issue"] == "CALENDAR_NOT_COVERED"


def test_pn03_entry_sessions() -> None:
    days = [day.isoformat() for day in (D0, D2)]
    assert _sessions({D0: True, D1: False, D2: True}, D0, D2) == days
    assert _sessions({D0: True, D2: True}, D0, D2) is None


def test_pn03_entry_owned_snapshot(conn) -> None:
    owner = uuid.uuid4()
    seed_calendar(conn, _seed())
    conn.execute(
        insert(users).values(
            id=owner,
            username="pn03_" + owner.hex[:24],
            display_name="合成用户",
            password_hash="not-a-password",
            role="user",
            status="approved",
        )
    )
    conn.execute(
        insert(securities).values(
            code=CODE_A,
            type="stock",
            name="合成A",
            exchange="SH",
            board="main",
            listing_status="listed",
        )
    )
    conn.execute(
        insert(watchlist_items).values(
            id=uuid.uuid4(), user_id=owner, security_code=CODE_A
        )
    )
    conn.execute(insert(daily_bars), [_bar(CODE_A, D0), _bar(CODE_A, D2, "20")])
    identifier, issues = build_owned_snapshot(conn, owner, D2, now=_at(D2))
    assert identifier is not None and issues == ()
    items = (
        conn.execute(select(data_snapshots).where(data_snapshots.c.id == identifier))
        .one()
        .items
    )
    result = _prepare(
        instrument=items["instruments"][0],
        as_of=_at(D2),
        factors=items["instruments"][0].get("factors", []),
    )
    assert result["raw_close"] == 20 and result["features"]["f.close_qfq"] is None
    assert result["gaps"] == [
        f"adjust_factor_missing:{D0}",
        f"adjust_factor_missing:{D2}",
    ]
    conn.execute(delete(trading_calendar).where(trading_calendar.c.date == D1))
    assert build_owned_snapshot(conn, owner, D2, now=_at(D2)) == (
        None,
        ("calendar_not_covered",),
    )


@pytest.mark.xfail(strict=True, reason="T-B168: prepare 缺 available_at 仍 KeyError")
def test_pn03_entry_prepare() -> None:
    early = {
        "date": D0.isoformat(),
        "value": "1",
        "available_at": _at(D0, 16).isoformat(),
    }
    late = {
        "date": D2.isoformat(),
        "value": "2",
        "available_at": _at(D2, 16).isoformat(),
    }
    first = _prepare(factors=[early, late])
    assert first["features"]["f.close_qfq"] == 10
    second = _prepare(factors=[early, late], as_of=_at(D2))
    equivalent = _prepare(factors=[early, late], as_of=_at(D2).astimezone(dt.UTC))
    assert second["features"] == equivalent["features"]
    assert second["series"]["f.close_qfq"] == [5, 20]
    missing_time = _prepare(factors=[{"date": D0.isoformat(), "value": "3"}])
    assert missing_time["features"]["f.close_qfq"] is None
    assert missing_time["gaps"] == [f"adjust_factor_missing:{D0}"]
    bj = _prepare(instrument=_instrument(CODE_B, (D0,)))
    assert bj["features"]["f.close_qfq"] is None
    assert bj["gaps"] == [f"adjust_factor_missing:{D0}"]


@pytest.mark.xfail(strict=True, reason="T-B168: calendar_seed CLI 冲突未拒")
def test_pn03_entry_calendar_seed_cli(
    tmp_path, monkeypatch, capsys, pn03_engine
) -> None:
    config = tmp_path / "config"
    _write_seed(config, _seed())
    argv = ["--config-dir", str(config)]
    assert cli_main.main(["calendar-seed", *argv]) == 0
    assert calendar_seed.main(argv) == 0
    assert "dry-run" in capsys.readouterr().out
    with pn03_engine.connect() as connection:
        assert connection.execute(select(trading_calendar)).first() is None
    monkeypatch.setenv(
        "DATABASE_URL", pn03_engine.url.render_as_string(hide_password=False)
    )
    assert calendar_seed.main([*argv, "--apply"]) == 0
    with pn03_engine.connect() as connection, pytest.raises(AppError):
        market_clock(connection, _at(D0 - dt.timedelta(days=1)), RULES)
    _write_seed(config, _seed(opens=(D2,)))
    with pytest.raises(ValueError):
        calendar_seed.main([*argv, "--apply"])
    with pn03_engine.connect() as connection:
        assert (
            connection.execute(
                select(trading_calendar.c.is_open).where(trading_calendar.c.date == D0)
            ).scalar_one()
            is True
        )


def _encrypt_record(clear: bytes) -> bytes:
    result = bytearray()
    for offset in range(0, 24, 8):
        a, b = struct.unpack_from("<II", clear, offset)
        left, right = b, a ^ KEYS[0]
        for j in range(1, 17):
            old = right
            f = (KEYS[274 + ((old >> 16) & 255)] + KEYS[18 + (old >> 24)]) & 0xFFFFFFFF
            f = (f ^ KEYS[530 + ((old >> 8) & 255)]) & 0xFFFFFFFF
            f = (f + KEYS[786 + (old & 255)]) & 0xFFFFFFFF
            left, right = old, (left ^ f ^ KEYS[j]) & 0xFFFFFFFF
        result.extend(struct.pack("<II", left ^ KEYS[17], right))
    return bytes(result) + clear[24:]


def _gbbq_zip(path: Path) -> str:
    clear = struct.pack("<B7sIBffff", 1, b"699001", 20301230, 1, 2.0, 8.0, 0.1, 0.1)
    data = struct.pack("<I", 1) + _encrypt_record(clear)
    with ZipFile(path, "w") as archive:
        archive.writestr("gbbq", data)
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.xfail(strict=True, reason="T-B168: GBBQ 因子缺 available_at 仍 KeyError")
def test_pn03_entry_gbbq_cli(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(tb143_export, "load_pytdx_keys", lambda: KEYS)
    archive = tmp_path / "gbbq.zip"
    digest = _gbbq_zip(archive)
    base = ["gbbq", "--zip", str(archive), "--generator", "c" * 40]
    bad = tmp_path / "bad"
    assert (
        tb143_export.main([*base, "--expected-sha256", "0" * 64, "--out", str(bad)])
        == 2
    )
    assert json.loads((bad / "summary.json").read_text())["gbbq"]["status"] == "refused"
    assert not (bad / "ex_rights_events.csv").exists()
    good = tmp_path / "good"
    assert (
        tb143_export.main([*base, "--expected-sha256", digest, "--out", str(good)]) == 0
    )
    with (good / "ex_rights_events.csv").open(encoding="utf-8", newline="") as stream:
        [row] = list(csv.DictReader(stream))
    assert row["code"] == CODE_A and row["snapshot_sha256"] == digest
    result = _prepare(factors=[{"date": row["ex_date"], "value": "1"}])
    assert result["gaps"] == [f"adjust_factor_missing:{D0}"]


def _day_record(day: dt.date) -> bytes:
    return DAY_LAYOUT.pack(
        int(day.strftime("%Y%m%d")), 1234, 1234, 1234, 1234, 8638.0, 700, 0
    )


def _day_inputs(directory: Path, days: tuple[dt.date, ...]) -> list[str]:
    archive, eligible = directory / "day.zip", directory / "eligible.txt"
    with ZipFile(archive, "w") as bundle:
        bundle.writestr(
            "sh/lday/sh699001.day", b"".join(_day_record(day) for day in days)
        )
    eligible.write_text(CODE_A, encoding="utf-8")
    return [
        "day",
        "--zip",
        str(archive),
        "--eligible-codes",
        str(eligible),
        "--generator",
        "c" * 40,
    ]


def test_pn03_entry_day_cli(tmp_path, conn) -> None:
    before = dt.date(2023, 11, 13)
    early = before - dt.timedelta(days=3)
    base = _day_inputs(tmp_path, (early, before))
    all_out = tmp_path / "all"
    assert tb143_export.main([*base, "--out", str(all_out)]) == 0
    summary = json.loads((all_out / "summary.json").read_text())["day"]
    assert summary["before"] is None and summary["counts"]["rows_exported"] == 2
    filtered = tmp_path / "filtered"
    assert (
        tb143_export.main(
            [*base, "--before", before.isoformat(), "--out", str(filtered)]
        )
        == 0
    )
    with (filtered / "daily_bars.csv").open(encoding="utf-8", newline="") as stream:
        [row] = list(csv.DictReader(stream))
    assert row["trade_date"] == early.isoformat()
    summary = json.loads((filtered / "summary.json").read_text())["day"]
    assert summary["before"] == before.isoformat()
    assert summary["counts"]["record:filtered_before"] == 1
    assert conn.execute(select(trading_calendar)).first() is None


def _probe_schema(conn) -> str:
    schema = "pn03_" + uuid.uuid4().hex
    conn.execute(f'CREATE SCHEMA "{schema}"')
    conn.execute(f'''CREATE TABLE "{schema}".daily_bars (
      code text, trade_date date, adj_type text, open numeric, high numeric, low numeric,
      close numeric, volume numeric, amount numeric, pre_close numeric, is_suspended boolean,
      source text, source_licence_id uuid, fetched_at timestamptz,
      PRIMARY KEY (code, trade_date, adj_type))''')
    conn.execute(f'''CREATE TABLE "{schema}".ex_rights_events (
      code text, ex_date date, cash_per_share numeric, rights_price numeric,
      bonus_ratio numeric, rights_ratio numeric, source text, snapshot_sha256 text,
      registered_at timestamptz DEFAULT now(), PRIMARY KEY (code, ex_date, snapshot_sha256))''')
    conn.execute(f'''CREATE TABLE "{schema}".minute_file_catalog (
      source text, code text, kind text, date_from date, date_to date, rel_path text,
      sha256 text, row_count bigint, splice_segment text, generator text,
      registered_at timestamptz DEFAULT now(), PRIMARY KEY (source, code, kind, rel_path))''')
    return schema


def _run_sql(conn, schema: str, name: str, rows: dict[str, list], before="2031-01-01"):
    source = (BACKEND / "probes" / name).read_text(encoding="utf-8")
    source = source.replace("market.", f'"{schema}".').replace(
        ":'before'", f"'{before}'"
    )
    stages_day = name == "tb143_load_day.sql"
    pending: list[str] = []
    for line in source.splitlines():
        if not stages_day and (
            line.startswith("\\")
            or line
            in (
                "BEGIN;",
                "COMMIT;",
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ;",
            )
        ):
            continue
        if line.startswith("COPY "):
            if pending:
                conn.execute("\n".join(pending))
            pending = []
            table = line.split()[1]
            stream = io.StringIO()
            csv.writer(stream).writerows(rows[table])
            with conn.cursor().copy(
                f"COPY {table} FROM STDIN WITH (FORMAT csv, HEADER true)"
            ) as copy:
                copy.write(stream.getvalue())
        else:
            pending.append(line)
    conn.execute("\n".join(pending))
    if stages_day:
        return conn.execute("SELECT * FROM pg_temp.day_stage").fetchall()
    counts = conn.execute("SELECT * FROM load_counts").fetchall()
    conn.execute(
        "DROP VIEW IF EXISTS catalog_effective; DROP VIEW IF EXISTS mairui_count"
    )
    conn.execute(
        "DROP TABLE IF EXISTS gbbq_stage, catalog_stage, day_stage, load_params, "
        "load_counts, mairui_before, mairui_after"
    )
    return counts


def _event_rows(duplicate=False) -> dict[str, list]:
    event = [CODE_A, D0.isoformat(), 0.2, 8, 0.1, 0.1, "tdx_gbbq", "b" * 64]
    catalog = [
        "hf_1min",
        CODE_A,
        "1m",
        D0.isoformat(),
        D1.isoformat(),
        "hf/fake.parquet",
        "a" * 64,
        1,
        "hf_1m",
        "c" * 40,
    ]
    return {
        "gbbq_stage": [
            [
                "code",
                "ex_date",
                "cash_per_share",
                "rights_price",
                "bonus_ratio",
                "rights_ratio",
                "source",
                "snapshot_sha256",
            ],
            event,
            *([event] if duplicate else []),
        ],
        "catalog_stage": [
            [
                "source",
                "code",
                "kind",
                "date_from",
                "date_to",
                "rel_path",
                "sha256",
                "row_count",
                "splice_segment",
                "generator",
            ],
            catalog,
        ],
    }


@pytest.mark.xfail(
    strict=True, reason="T-B168: load_meta 因子缺 available_at 仍 KeyError"
)
def test_pn03_entry_load_meta_sql(pg_conn) -> None:
    schema = _probe_schema(pg_conn)
    counts = _run_sql(
        pg_conn, schema, "tb143_load_meta.sql", _event_rows(duplicate=True)
    )
    assert counts == [("ex_rights_events", 2, 1, 1), ("minute_file_catalog", 1, 1, 0)]
    row = pg_conn.execute(
        f'SELECT ex_date, snapshot_sha256, registered_at FROM "{schema}".ex_rights_events'
    ).fetchone()
    assert row[0] == D0 and row[1] == "b" * 64 and row[2] is not None
    result = _prepare(factors=[{"date": row[0].isoformat(), "value": "1"}])
    assert result["gaps"] == [f"adjust_factor_missing:{D0}"]


@pytest.mark.parametrize("before", [None, D2.isoformat()], ids=["default", "explicit"])
def test_pn03_entry_day_runner_ps1(tmp_path, before) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    original = {"all.bin": b"synthetic archive\n", "SUMS": b"synthetic manifest\n"}
    for name, content in original.items():
        (artifacts / name).write_bytes(content)

    bindir = tmp_path / "bin"
    bindir.mkdir()
    calls = tmp_path / "external-calls"
    for name in ("docker", "psql"):
        if os.name == "nt":
            (bindir / f"{name}.cmd").write_text(
                f'@echo {name}>>"%PN03_CALLS%"\n@exit /b 1\n', encoding="utf-8"
            )
        else:
            command = bindir / name
            command.write_text(f'#!/bin/sh\necho {name} >> "$PN03_CALLS"\nexit 1\n')
            command.chmod(0o755)
    env = dict(
        os.environ,
        PATH=str(bindir) + os.pathsep + os.environ["PATH"],
        PN03_CALLS=str(calls),
    )
    shell = shutil.which("pwsh") or shutil.which("powershell")
    assert shell is not None, "原 PS1 入口需要 pwsh/powershell"
    lock, log = tmp_path / "lock", tmp_path / "runner.log"
    argv = [
        shell,
        "-NoProfile",
        "-File",
        str(BACKEND / "probes/tb143_day_load_runner.ps1"),
        "-Dir",
        str(artifacts),
        "-AllSha",
        hashlib.sha256(original["all.bin"]).hexdigest(),
        "-BundleSizes",
        str(len(original["all.bin"])),
        "-Lock",
        str(lock),
        "-Log",
        str(log),
        "-PauseSeconds",
        "0",
    ]
    if before is not None:
        argv += ["-Before", before]
    completed = subprocess.run(
        argv, check=False, env=env, capture_output=True, text=True, timeout=30
    )
    output = completed.stdout + completed.stderr
    assert completed.returncode == 1, output
    assert "legacy tb143 load path is disabled" in output
    assert "python -m app.cli daily-bars-import-tdx" in output
    assert "python -m app.cli.tb143_day_load" in output
    assert not calls.exists() and not lock.exists() and not log.exists()
    assert {path.name: path.read_bytes() for path in artifacts.iterdir()} == original


@pytest.mark.parametrize(
    "invalid_offset", [None, 0, 1], ids=["valid", "at-before", "after-before"]
)
def test_pn03_entry_load_day_sql(pg_conn, invalid_offset) -> None:
    before = dt.date(2023, 11, 13)
    early = before - dt.timedelta(days=1)
    header = [
        "code",
        "trade_date",
        "adj_type",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
    ]
    valid = (CODE_A, early, "none", 10, 12, 9, 11, 40, 440)
    rows = [header, valid]
    # 只在隔离测试事务中写入虚构的既有行，回滚后不留状态。
    pg_conn.execute(
        "INSERT INTO market.daily_bars (code, trade_date, close, source) "
        "VALUES (%s, %s, 20, 'fake')",
        (CODE_A, early),
    )
    pg_conn.execute(
        "INSERT INTO market.trading_calendar (date, is_open) VALUES (%s, true)",
        (early,),
    )
    bars_query = "SELECT * FROM market.daily_bars ORDER BY code, trade_date, adj_type"
    calendar_query = "SELECT * FROM market.trading_calendar ORDER BY date"
    before_bars = pg_conn.execute(bars_query).fetchall()
    before_calendar = pg_conn.execute(calendar_query).fetchall()

    if invalid_offset is None:
        assert _run_sql(
            pg_conn,
            "market",
            "tb143_load_day.sql",
            {"day_stage": rows},
            before.isoformat(),
        ) == [valid]
    else:
        invalid_date = before + dt.timedelta(days=invalid_offset)
        rows.append((CODE_B, invalid_date, "none", 10, 12, 9, 11, 40, 440))
        with (
            pytest.raises(
                psycopg.errors.RaiseException, match="日线日期必须全部小于 before"
            ),
            pg_conn.transaction(),
        ):
            _run_sql(
                pg_conn,
                "market",
                "tb143_load_day.sql",
                {"day_stage": rows},
                before.isoformat(),
            )
        assert pg_conn.execute(
            "SELECT to_regclass('pg_temp.day_stage')"
        ).fetchone() == (None,)

    assert pg_conn.execute(bars_query).fetchall() == before_bars
    assert pg_conn.execute(calendar_query).fetchall() == before_calendar


def test_pn03_entry_research_calendar(tmp_path) -> None:
    original = ROOT / "docs/strategies/calendar/build_trading_calendar_2026.py"
    before = original.read_bytes()
    copied = tmp_path / original.name
    copied.write_bytes(before)
    completed = subprocess.run(
        [sys.executable, str(copied)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    value = json.loads(
        (tmp_path / "trading_calendar_2026.json").read_text(encoding="utf-8")
    )
    model = CalendarReference.model_validate(value)
    assert model.coverage_start == "2026-01-01" and model.coverage_end == "2026-12-31"
    assert "merged_calendar" not in value["source"] and "C8" not in value["source"]
    assert not (tmp_path / "merged_calendar.json").exists()
    assert original.read_bytes() == before


def _require_pg17() -> None:
    programs = ("initdb", "pg_ctl", "postgres", "psql")
    if os.name == "nt":
        if shutil.which("wsl.exe") is None:
            pytest.skip("PG17 自检需要 WSL 与隔离 PG17；当前无 wsl.exe")
        command = (
            "for p in initdb pg_ctl postgres psql; do "
            "test -x /usr/lib/postgresql/17/bin/$p || exit 1; done"
        )
        try:
            probe = subprocess.run(
                ["wsl.exe", "bash", "-lc", command],
                check=False,
                capture_output=True,
                timeout=15,
            )
            available = probe.returncode == 0
        except (OSError, subprocess.SubprocessError):
            available = False
        if not available:
            pytest.skip("PG17 自检需要可用 WSL 与隔离 PG17；当前环境不满足")
    elif not all(
        os.access(f"/usr/lib/postgresql/17/bin/{program}", os.X_OK)
        for program in programs
    ):
        pytest.skip("PG17 自检需要隔离 PG17；CI 仅提供 PG16")


def test_pn03_entry_pg_selfcheck() -> None:
    _require_pg17()
    script = BACKEND / "probes/tb143_pg_selfcheck.sh"
    target = str(script)
    if os.name == "nt":
        target = subprocess.check_output(
            ["wsl.exe", "wslpath", "-a", script.as_posix()], text=True
        ).strip()
    completed = subprocess.run(
        ["bash", target],
        check=False,
        capture_output=True,
        timeout=120,
        env={"PATH": os.environ.get("PATH", "")},
    )
    encoding = "utf-16" if b"\0" in completed.stdout + completed.stderr else "utf-8"
    stdout = completed.stdout.decode(encoding, errors="replace")
    stderr = completed.stderr.decode(encoding, errors="replace")
    assert completed.returncode == 0, stdout + stderr
    assert "PASS:" in stdout and "CLEANUP:" in stdout
    source = script.read_text(encoding="utf-8")
    assert "trading_calendar" not in source and "available_at" not in source


def _http_client(pn03_engine, monkeypatch, when: dt.datetime) -> TestClient:
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(aggregates_api.router, prefix="/api/v1")
    owner = uuid.uuid4()
    app.dependency_overrides[deps.get_engine] = lambda: pn03_engine
    app.dependency_overrides[deps.get_settings] = lambda: SimpleNamespace(
        business=BusinessConfig.model_validate(load_yaml_dir(ROOT / "config"))
    )
    app.dependency_overrides[deps.current_auth] = lambda: AuthContext(
        user=SimpleNamespace(id=owner), session=None
    )

    class FrozenDateTime(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return when.astimezone(tz) if tz else when.replace(tzinfo=None)

    monkeypatch.setattr(
        aggregates_api, "dt", SimpleNamespace(datetime=FrozenDateTime, UTC=dt.UTC)
    )
    return TestClient(app, raise_server_exceptions=False)


def _check_http(pn03_engine, monkeypatch, path: str) -> None:
    with pn03_engine.begin() as connection:
        seed_calendar(connection, _seed())
    client = _http_client(pn03_engine, monkeypatch, _at(D1, 12))
    with client:
        closed = client.get("/api/v1" + path)
        assert closed.status_code == 200, closed.text
        assert closed.json()["trade_date"] == D0.isoformat()
        assert closed.json()["session"] == "non_trading_day"
        with pn03_engine.begin() as connection:
            connection.execute(
                delete(trading_calendar).where(trading_calendar.c.date == D1)
            )
        missing = client.get("/api/v1" + path)
        assert missing.status_code == 503, missing.text
        assert missing.json()["error"]["code"] == "CALENDAR_NOT_COVERED"


def test_pn03_entry_today_http(pn03_engine, monkeypatch) -> None:
    _check_http(pn03_engine, monkeypatch, "/today")


def test_pn03_entry_terminal_http(pn03_engine, monkeypatch) -> None:
    _check_http(pn03_engine, monkeypatch, "/terminal")


def test_pn03_entry_overview_http(pn03_engine, monkeypatch) -> None:
    _check_http(pn03_engine, monkeypatch, "/market/overview")
