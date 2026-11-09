# ruff: noqa: S101, ANN401
"""T-B97: fictional master rows, disposable PostgreSQL only, no provider IO."""

from __future__ import annotations

import datetime as dt
import os
import runpy
import socket
import uuid
from argparse import Namespace
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, insert, select, text, update
from sqlalchemy.exc import ProgrammingError

from app.cli.security_search_terms import main
from app.config_files import SecuritiesConfig
from app.db.tables.market import (
    master_runs,
    master_snapshots,
    securities,
    security_code_history,
    security_name_history,
    security_search_terms,
)
from app.master import sync
from app.master.search import search
from app.master.terms import generate, initials, rebuild

DSN = "postgresql+psycopg://postgres@127.0.0.1:55497/tb97_test"
ROOT = Path(__file__).resolve().parents[3]
CODES = ("600091.SH", "600092.SH", "920094.BJ")


@pytest.fixture(scope="module")
def engine() -> Any:
    if os.environ.get("TB97_ISOLATED_DATABASE_URL") != DSN:
        pytest.skip("requires disposable T-B97 database on dedicated port 55497")
    engine = create_engine(DSN, hide_parameters=True)
    with engine.connect() as conn:
        assert conn.execute(text("select current_database()")).scalar_one() == "tb97_test"
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "src/backend/migrations"))
    cfg.cmd_opts = Namespace(x=["url=" + DSN])
    command.upgrade(cfg, "head")
    now = dt.datetime.now(dt.UTC)
    with engine.begin() as conn:
        for code, name in zip(CODES, ("合成重庆银行", "*ST合成银行", "合成北方"), strict=True):
            conn.execute(
                insert(securities).values(
                    code=code,
                    name=name,
                    type="stock",
                    exchange=code[-2:],
                    listing_status="listed",
                    master_source="exchange",
                )
            )
        conn.execute(
            insert(security_name_history).values(
                code=CODES[0],
                name="往日合成",
                valid_from=dt.date(2020, 1, 1),
                valid_until=dt.date(2021, 1, 1),
                source="exchange_diff",
            )
        )
        conn.execute(
            insert(security_code_history).values(
                code=CODES[2],
                old_code="830094.BJ",
                valid_from=dt.date(2020, 1, 1),
                source="bse_code_map",
            )
        )
        snapshots = []
        for source in ("sse_list", "szse_list", "bse_list"):
            snapshots.append(
                conn.execute(
                    insert(master_snapshots)
                    .values(
                        source=source,
                        url="https://example.invalid/synthetic",
                        fetched_at=now,
                        trade_date=dt.date(2026, 11, 9),
                        row_count=1,
                        sha256=uuid.uuid4().hex * 2,
                        parse_status="ok",
                    )
                    .returning(master_snapshots.c.id)
                ).scalar_one()
            )
        conn.execute(
            insert(master_runs).values(
                trigger="bootstrap",
                status="ok",
                started_at=now,
                finished_at=now,
                snapshot_ids=snapshots,
                stats={
                    "sources": {
                        source: {"status": "ok"} for source in ("sse_list", "szse_list", "bse_list")
                    }
                },
            )
        )
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    original = socket.socket.connect

    def connect(sock: Any, address: Any) -> Any:
        assert address[:2] == ("127.0.0.1", 55497), "T-B97 denies all non-test networking"
        return original(sock, address)

    monkeypatch.setattr(socket.socket, "connect", connect)


def config() -> SecuritiesConfig:
    import yaml

    return SecuritiesConfig.model_validate(
        yaml.safe_load(
            (ROOT / "config/securities.yaml").read_text(encoding="utf-8"),
        )
    )


def test_phrase_default_variants_cap_nfkc_and_declared_kinds() -> None:
    assert initials("重庆银行")[0] == "CQYH"
    assert len(initials("重重重重重", maximum=3)) == 3
    assert len(initials("重重重重重", maximum=100)) == 16
    assert initials("ＡI股1")[0] == "AIG1"
    rows = generate("*ST示例", ["旧示例"], ["830094.BJ"])
    assert {row.term_kind for row in rows} == {
        "name",
        "name_initials",
        "former_name",
        "former_initials",
        "former_code",
    }
    assert any(row.term == "STSL" and not row.is_st_stripped for row in rows)
    assert any(row.term == "SL" and row.is_st_stripped for row in rows)
    assert any(row.term == "示例" and row.is_st_stripped for row in rows)
    assert all(row.source_name == "*ST示例" for row in rows if row.term == "SL")
    assert len({(row.term_kind, row.term, row.source_name) for row in rows}) == len(rows)
    assert all(
        row.term.isalnum() and row.term.isascii() and row.term == row.term.upper()
        for row in rows
        if row.term_kind in {"name_initials", "former_initials"}
    )
    with pytest.raises(ValueError, match="initials maximum must be positive"):
        initials("合成", 0)


def test_rebuild_search_names_initials_former_fuzzy_and_idempotent(engine: Any) -> None:
    cfg = config().search
    owner = uuid.uuid4()
    with engine.begin() as conn:
        first = rebuild(conn, CODES, maximum=cfg.initials_max_variants)
        assert first["changed_securities"] == 3
        before = conn.execute(
            select(security_search_terms).order_by(security_search_terms.c.id)
        ).all()
        assert rebuild(conn, CODES)["changed_securities"] == 0
        assert (
            conn.execute(select(security_search_terms).order_by(security_search_terms.c.id)).all()
            == before
        )
        assert rebuild(conn, [])["securities"] == 0
        for query, expected_code, kind, matched in (
            ("600091", CODES[0], "code_exact", None),
            ("合成重庆银行", CODES[0], "name_exact", None),
            ("重庆", CODES[0], "name_contains", None),
            ("hccqyh", CODES[0], "initials_exact", "合成重庆银行"),
            ("hccq", CODES[0], "initials_prefix", "合成重庆银行"),
            ("hcyh", CODES[1], "initials_exact", "*ST合成银行"),
            ("wrhc", CODES[0], "former_name", "往日合成"),
            ("830094", CODES[2], "former_code", "830094.BJ"),
            ("合成重庆银航", CODES[0], "fuzzy", None),
        ):
            result = search(
                conn, owner, cfg, q=query, types="stock,cdr,etf", include_delisted=False, limit=20
            )
            item = next(item for item in result["items"] if item["security_code"] == expected_code)
            assert item["match_kind"] == kind, (query, item)
            assert item["matched_text"] == matched


def test_rename_rebuild_is_scoped_and_transactional(engine: Any) -> None:
    with engine.connect() as conn:
        before = conn.execute(
            select(security_search_terms).where(security_search_terms.c.code == CODES[1])
        ).all()
    with engine.begin() as conn:
        conn.execute(
            update(securities).where(securities.c.code == CODES[0]).values(name="合成新名")
        )
        assert rebuild(conn, [CODES[0]])["changed_securities"] == 1
        names = set(
            conn.execute(
                select(security_search_terms.c.term).where(
                    security_search_terms.c.code == CODES[0],
                    security_search_terms.c.term_kind == "name",
                )
            ).scalars()
        )
        assert names == {"合成新名"}
        assert (
            conn.execute(
                select(security_search_terms).where(security_search_terms.c.code == CODES[1])
            ).all()
            == before
        )
    with engine.connect() as conn:
        transaction = conn.begin()
        conn.execute(
            update(securities).where(securities.c.code == CODES[0]).values(name="回滚合成")
        )
        rebuild(conn, [CODES[0]])
        transaction.rollback()
    with engine.connect() as conn:
        assert (
            conn.execute(
                select(securities.c.name).where(securities.c.code == CODES[0])
            ).scalar_one()
            == "合成新名"
        )


def test_cli_guards_dry_run_apply_and_opt_in_sync(
    engine: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for module in ("app.cli.security_search_terms", "app.cli.calendar_seed"):
        monkeypatch.setattr("sys.argv", [module])
        with pytest.raises(SystemExit) as result:
            runpy.run_module(module, run_name="__main__")
        assert result.value.code == 0
    assert "calendar validated" in capsys.readouterr().out
    with pytest.raises(SystemExit) as result:
        main(["--apply"])
    assert result.value.code == 2
    monkeypatch.setenv("DATABASE_URL", DSN)
    assert main(["--apply", "--codes", CODES[0]]) == 0
    cfg = config()
    with engine.begin() as conn:
        unchanged = sync.apply_run(
            conn, [], cfg.master, trigger="manual", trade_date=dt.date(2026, 11, 9), raw_root=None
        )
        assert "search_terms" not in unchanged.stats
        explicit = sync.apply_run(
            conn,
            [],
            cfg.master,
            trigger="manual",
            trade_date=dt.date(2026, 11, 9),
            raw_root=None,
            rebuild_search_terms=True,
            initials_max_variants=cfg.search.initials_max_variants,
        )
        assert explicit.stats["search_terms"]["changed_securities"] == 0


def test_read_only_role_cannot_generate_terms(engine: Any) -> None:
    role = "tb97_reader_" + uuid.uuid4().hex
    with engine.begin() as conn:
        conn.execute(text(f"create role {role} nologin"))
        conn.execute(text(f"grant usage on schema market to {role}"))
        conn.execute(text(f"grant select on all tables in schema market to {role}"))
        before = conn.execute(select(security_search_terms)).all()
    try:
        # Role selection and the denied write must share a transaction that rolls back.
        with pytest.raises(ProgrammingError), engine.begin() as conn:  # noqa: PT012
            conn.execute(text(f"set local role {role}"))
            rebuild(conn, [CODES[0]])
        with engine.connect() as conn:
            assert conn.execute(select(security_search_terms)).all() == before
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"revoke all on all tables in schema market from {role}"))
            conn.execute(text(f"revoke all on schema market from {role}"))
            conn.execute(text(f"drop role {role}"))
