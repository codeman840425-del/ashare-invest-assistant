"""Pure synthetic T-B70 tests; integration requires dedicated networkless tb70 DB/Redis.

Setup: team/reports/T-B70.md. Never imports legacy fixture files or private samples.
"""

# ruff: noqa: S101, S108, ANN401
from __future__ import annotations

import datetime as dt
import secrets
import socket
import uuid
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, insert, select, text

from app.common.errors import AppError, ErrorCode
from app.config import Settings
from app.db.tables.reviews import data_snapshots
from app.db.tables.users import users
from app.importing.parsers.tdx import TRADES
from app.importing.preview import PreviewContext, PreviewOptions, preview_bytes
from app.importing.text import display_width
from app.main import create_app
from app.replay.baseline import (
    CLOCK,
    INSTRUMENTS,
    load,
    manifest_hash,
    payload,
    positions_file,
    read,
    require_isolated,
)
from app.schemas.enums import RegistrationMode

DB = "postgresql+psycopg://postgres@/tb70_replay?host=/tmp/tb70-pg-socket"
REDIS = "unix:///tmp/tb70-redis-socket/redis.sock?db=0"


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    attempts: list[str] = []
    original = socket.socket.connect

    def connect(sock: socket.socket, address: Any) -> Any:
        if sock.family != socket.AF_UNIX:
            attempts.append("denied")
            raise AssertionError("T-B70 forbids IP network access")
        return original(sock, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    yield attempts
    assert attempts == []


def test_synthetic_manifest() -> None:
    bundle = payload()
    assert manifest_hash(bundle) == manifest_hash(payload())
    assert bundle["simulation"]
    assert bundle["provider"] == "system"
    assert bundle["epistemic_type"] == "hypothesis"
    assert {item["security_code"] for item in bundle["instruments"]} == {
        code for code, _, _ in INSTRUMENTS
    }
    assert len(bundle["sessions"]) == 100
    for item in bundle["instruments"]:
        assert len(item["bars"]) >= 80
        assert item["normal_limit_pct"] == "20"
        assert item["limit_exception"] is None
        assert item["adjust"] == "none"
        assert item["volume_unit"] == "share"
        dates = [bar["trade_date"] for bar in item["bars"]]
        assert dates == sorted(set(dates))
        gap_dates = {gap["trade_date"] for gap in item["gaps"]}
        assert not gap_dates.intersection(dates)
        for bar in item["bars"]:
            o, h, low, c, prev = (
                Decimal(bar[key])
                for key in (
                    "open",
                    "high",
                    "low",
                    "close",
                    "pre_close",
                )
            )
            assert 0 < low <= min(o, c) <= max(o, c) <= h
            assert prev * Decimal("0.8") <= low <= h <= prev * Decimal("1.2")
            assert Decimal(bar["amount"]) == c * Decimal(bar["volume"])
            assert dt.datetime.fromisoformat(bar["first_seen_at"]) <= CLOCK
    assert {gap["reason"] for item in bundle["instruments"] for gap in item["gaps"]} == {
        "suspended",
        "delisted",
        "no_source",
    }


@pytest.mark.parametrize("encoding", ["utf-8", "gbk"])
def test_positions_preview(encoding: str) -> None:
    result = preview_bytes(
        positions_file(encoding),
        "positions",
        PreviewOptions(),
        PreviewContext(
            account_id="synthetic-tb70",
            today=CLOCK.date(),
            uploaded_at=CLOCK,
            holder_hmac=lambda value: manifest_hash({"synthetic": value}),
        ),
    )
    assert result.status == "previewed"
    assert result.parser_id == "tdx_positions_v1"
    assert len(result.rows) == 4
    assert not any(row.has_error for row in result.rows)
    assert {row.normalized["security_code"] for row in result.rows if row.normalized} == {
        code[:6] for code, _, _ in INSTRUMENTS
    }
    assert "SYNTHETIC" not in str([row.raw_masked for row in result.rows])


def _migration_head() -> str:
    """Read this checkout's migration graph without a DB or locale-dependent ini."""
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "migrations")
    )
    heads = ScriptDirectory.from_config(config).get_heads()
    assert len(heads) == 1, f"T-B70 requires a unique migration head; found {heads}"
    return heads[0]


def test_migration_head_matches_checkout() -> None:
    assert _migration_head()  # Resolves the checked-out graph without connecting to PostgreSQL.


@pytest.mark.parametrize("heads", [[], ["synthetic-head-a", "synthetic-head-b"]])
def test_migration_head_rejects_non_unique_graph(
    monkeypatch: pytest.MonkeyPatch, heads: list[str],
) -> None:
    monkeypatch.setattr(ScriptDirectory, "get_heads", lambda _self: heads)
    with pytest.raises(AssertionError, match="unique migration head"):
        _migration_head()


@pytest.fixture
def integration(
    tmp_path: Path,
) -> Iterator[tuple[Any, TestClient, TestClient, uuid.UUID, uuid.UUID]]:
    if not Path("/tmp/tb70-pg-socket/.s.PGSQL.5432").exists():
        pytest.skip("dedicated networkless T-B70 PostgreSQL not provisioned")
    engine = create_engine(DB)
    with engine.begin() as conn:
        require_isolated(conn, app_env="test")
        assert (
            conn.execute(text("select version_num from public.alembic_version")).scalar_one()
            == "0020"  # Legacy fixture stays fixed; current-head consumers use tt21_integration.
        )
    settings = Settings(
        _env_file=None,
        database_url=SecretStr(DB),
        redis_url=REDIS,
        app_env="test",
        app_master_key=SecretStr(secrets.token_urlsafe(32)),
        registration_mode=RegistrationMode.CLOSED,
        session_cookie_secure=False,
        import_storage_path=tmp_path,
    )
    app = create_app(settings)
    clients = [TestClient(app), TestClient(app)]
    ids = [uuid.uuid4(), uuid.uuid4()]
    password = secrets.token_urlsafe(20) + "7a"
    for user_id, client in zip(ids, clients, strict=True):
        username = "tb70_" + user_id.hex[:12]
        with engine.begin() as conn:
            conn.execute(
                insert(users).values(
                    id=user_id,
                    username=username,
                    display_name="模拟回放",
                    password_hash=PasswordHasher().hash(password),
                    role="user",
                    status="approved",
                )
            )
        response = client.post(
            "/api/v1/auth/login", json={"username": username, "password": password}
        )
        assert response.status_code == 200
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    with engine.begin() as conn:
        for code, board, _ in INSTRUMENTS:
            conn.execute(
                text(
                    "insert into market.securities(code,type,name,exchange,board,listing_status) "
                    "values (:code,'stock','模拟证券',:exchange,:board,'listed') "
                    "on conflict do nothing"
                ),
                {"code": code, "exchange": code[-2:], "board": board},
            )
    yield engine, clients[0], clients[1], ids[0], ids[1]
    for client in clients:
        client.close()
    engine.dispose()


def test_snapshot_job_isolation_and_rollback(integration: Any) -> None:
    engine, _, _, owner, other = integration
    with engine.begin() as conn:
        first = load(conn, owner, app_env="test")
        assert first == load(conn, owner, app_env="test")
        second = load(conn, other, app_env="test")
        assert first != second
        assert read(conn, owner, first) == payload()
        assert read(conn, other, second) == payload()
        for who, snapshot in ((other, first), (owner, second), (owner, uuid.uuid4())):
            with pytest.raises(AppError) as error:
                read(conn, who, snapshot)
            assert error.value.code == ErrorCode.NOT_FOUND
        assert (
            conn.execute(
                select(data_snapshots.c.licence_id).where(
                    data_snapshots.c.id == first,
                )
            ).scalar_one()
            is None
        )
        with pytest.raises(ValueError, match="dedicated"):
            load(conn, owner, app_env="production")
    # A failed enclosing transaction must not leave a partially installed snapshot.
    user_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            insert(users).values(
                id=user_id,
                username="tb70_" + user_id.hex[:12],
                password_hash=PasswordHasher().hash(secrets.token_urlsafe(20)),
                role="user",
                status="approved",
            )
        )
    with engine.connect() as conn:
        transaction = conn.begin()
        rolled_back = load(conn, user_id, app_env="test")
        transaction.rollback()
        with pytest.raises(AppError):
            read(conn, user_id, rolled_back)


def trade_file() -> bytes:
    # Full invented execution inputs, only the four explicitly allowed codes.
    def line(values: tuple[str, ...]) -> str:
        return "".join(value + " " * (22 - display_width(value)) for value in values).rstrip()

    columns = tuple(
        column
        for column in TRADES.columns
        if column.field
        not in {
            "order_no",
            "declare_no",
            "seat",
        }
    )
    rows = [line(tuple(column.name for column in columns))]
    for index, (code, _, _) in enumerate(INSTRUMENTS, 1):
        values = {
            "trade_date": "20261020",
            "trade_time": "10:00:00",
            "security_code": code[:6],
            "name": f"模拟证券{index}",
            "biz": "证券买入",
            "qty": "200",
            "price": "10.00",
            "amount": "2000.00",
            "net_amount": "-2000.00",
            "balance": str(100000 - index * 2000),
            "trade_no": f"SIM{index}",
            "holder": f"SYNTHETIC{index}",
            "commission": "0",
            "stamp_tax": "0",
            "transfer_fee": "0",
            "other_fee": "0",
            "remark": "模拟回放",
        }
        rows.append(line(tuple(values[column.field] for column in columns)))
    return ("\r\n".join(rows) + "\r\n").encode()


def test_real_import_preview_confirm_dedup_rebuild_revert(integration: Any) -> None:
    engine, client, stranger, _, _ = integration
    account = client.post("/api/v1/accounts", json={"broker_name": "模拟券商", "alias": "回放"})
    assert account.status_code == 201
    account_id = account.json()["id"]

    def upload(kind: str, content: bytes) -> str:
        response = client.post(
            "/api/v1/imports",
            data={
                "account_id": account_id,
                "kind": kind,
                "snapshot_as_of": "2026-10-21T08:00:00Z" if kind == "positions" else "",
            },
            files={"file": ("synthetic.txt", content, "text/plain")},
        )
        assert response.status_code == 201
        batch = response.json()["batch_id"]
        preview = client.get(f"/api/v1/imports/{batch}")
        assert preview.status_code == 200
        assert preview.json()["status"] == "previewed"
        rows = client.get(f"/api/v1/imports/{batch}/rows").json()["items"]
        assert len(rows) == 4
        assert not any(row["status"] == "error" for row in rows)
        return str(batch)

    def confirm(batch: str, key: str) -> Any:
        return client.post(
            f"/api/v1/imports/{batch}/confirm",
            json={
                "mode": "all",
                "acknowledge_warnings": True,
            },
            headers={"Idempotency-Key": key},
        )

    def holdings() -> list[tuple[str, str, str]]:
        with engine.connect() as conn:
            return [
                (str(row[0]), str(row[1]), str(row[2]))
                for row in conn.execute(
                    text(
                        "select security_code,quantity,avg_cost from app.holdings "
                        "where account_id=:id order by security_code"
                    ),
                    {"id": uuid.UUID(account_id)},
                )
            ]

    empty = holdings()
    trades_batch = upload("trades", trade_file())
    for path in (
        f"/imports/{trades_batch}",
        f"/imports/{trades_batch}/rows",
        f"/portfolio?account_id={account_id}",
        f"/imports?account_id={account_id}",
    ):
        assert stranger.get("/api/v1" + path).status_code == 404
    assert (
        stranger.post(
            f"/api/v1/imports/{trades_batch}/confirm",
            json={
                "mode": "all",
                "acknowledge_warnings": True,
            },
        ).status_code
        == 404
    )
    key = str(uuid.uuid4())
    committed = confirm(trades_batch, key)
    assert committed.status_code == 200
    assert committed.json()["written"]["trades"] == 4
    assert confirm(trades_batch, key).json() == committed.json()
    baseline = holdings()
    assert len(baseline) == 4
    duplicate = upload("trades", trade_file())
    assert confirm(duplicate, str(uuid.uuid4())).status_code == 422
    assert holdings() == baseline
    snapshot_batch = upload("positions", positions_file())
    committed_snapshot = confirm(snapshot_batch, str(uuid.uuid4()))
    assert committed_snapshot.status_code == 200
    assert committed_snapshot.json()["written"]["snapshot_positions"] == 4
    assert holdings() == baseline
    assert client.post(f"/api/v1/imports/{snapshot_batch}/revert").status_code == 200
    assert holdings() == baseline
    assert client.post(f"/api/v1/imports/{trades_batch}/revert").status_code == 200
    assert holdings() == empty
    with engine.connect() as conn:
        assert conn.execute(text("select count(*) from app.user_data_licences")).scalar_one() == 0


def test_cli_job(
    integration: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.replay.__main__ import main

    engine, _, _, owner, _ = integration
    monkeypatch.setattr(
        "sys.argv",
        [
            "replay",
            "--user",
            str(owner),
            "--database",
            "tb70_replay",
            "--socket",
            "/tmp/tb70-pg-socket",
        ],
    )
    main()
    output = capsys.readouterr().out
    assert "模拟回放 snapshot_id=" in output
    snapshot_id = uuid.UUID(output.strip().split("snapshot_id=")[-1])
    with engine.connect() as conn:
        assert read(conn, owner, snapshot_id) == payload()
    monkeypatch.setattr(
        "sys.argv",
        [
            "replay",
            "--user",
            str(owner),
            "--database",
            "production",
            "--socket",
            "/tmp/tb70-pg-socket",
        ],
    )
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
