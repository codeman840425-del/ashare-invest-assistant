"""T-B100 importer module execution and SecurityProfile HTTP/ACL; synthetic data only."""

# ruff: noqa: S101, ANN401
from __future__ import annotations

import datetime as dt
import os
import socket
import subprocess
import sys
import threading
import uuid
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, insert, select, text, update
from sqlalchemy.exc import DBAPIError

from app.auth.deps import get_engine, get_session_store
from app.auth.sessions import SESSION_COOKIE, Session
from app.config import Settings
from app.db.tables.licences import user_data_licence_holds, user_data_licences
from app.db.tables.market import (
    master_runs,
    master_snapshots,
    securities,
    security_code_history,
    security_name_history,
)
from app.db.tables.users import users
from app.main import create_app
from app.strategy.cards.persistence import validate_batch
from app.strategy.cards.preflight import feature_registry
from selfchecks.test_tb89_full_migrations import deploy_grants

ROOT = Path(__file__).resolve().parents[3]
DSN = "postgresql+psycopg://postgres@127.0.0.1:55498/tb100_test"
AT = dt.datetime(2031, 1, 2, 10, tzinfo=dt.UTC)
OFFICIAL_CARD_KEYS = ("hold_risk_monitor", "sw_ma_trend_pullback", "st_pullback_ma")


def official_card_paths() -> list[Path]:
    return [ROOT / "docs/strategies/cards" / (key + ".md") for key in OFFICIAL_CARD_KEYS]


def expected_preflight_summary(card_paths: list[Path], catalog: Path) -> str:
    """Derive the CLI summary from each card's validation fixtures (not a frozen total).

    34 was H-01 11 + W-01 15 + S-01 8 as of 055105a; current S-01 has FX1–FX10.
    """
    staged = validate_batch(
        [path.read_text(encoding="utf-8") for path in card_paths],
        feature_registry(catalog.read_text(encoding="utf-8")),
    )
    golden = sum(len(item.blocks["validation"]["fixtures"]) for item in staged)
    return f"formal cards validated: {len(staged)}; golden passed: {golden}"


def test_importer_module_executes_three_card_golden_preflight() -> None:
    cards = official_card_paths()
    catalog = ROOT / "docs/strategies/feature_spec.md"
    args = [sys.executable, "-m", "app.cli.cards_import"]
    for path in cards:
        args.extend(["--card", str(path)])
    args.extend(
        [
            "--catalog",
            str(catalog),
            "--market-rules",
            str(ROOT / "config/market_rules.yaml"),
        ]
    )
    result = subprocess.run(  # noqa: S603 - fixed interpreter/module and repository-owned paths
        args,
        cwd=ROOT / "src/backend",
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=90,
        check=False,
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    assert result.returncode == 0, result.stderr
    assert expected_preflight_summary(cards, catalog) in result.stdout
    assert "lifecycle remains draft; no gates granted" in result.stdout


@pytest.fixture(scope="module")
def database() -> Any:
    if os.environ.get("TB100_ISOLATED_DATABASE_URL") != DSN:
        pytest.skip("explicit disposable tb100_test on loopback:55498 required")
    engine = create_engine(DSN, hide_parameters=True)
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "src/backend/migrations"))
    cfg.cmd_opts = Namespace(x=["url=" + DSN])
    command.upgrade(cfg, "head")
    with engine.begin() as conn:
        assert conn.execute(text("SELECT current_database()")).scalar_one() == "tb100_test"
        deploy_grants(conn)
        snapshots = []
        sources = ("sse_list", "szse_list", "bse_list")
        for source in sources:
            snapshots.append(
                conn.execute(
                    insert(master_snapshots)
                    .values(
                        source=source,
                        url="synthetic:tb100",
                        fetched_at=AT,
                        trade_date=AT.date(),
                        row_count=4,
                        sha256=uuid.uuid4().hex * 2,
                        parse_status="ok",
                    )
                    .returning(master_snapshots.c.id)
                ).scalar_one()
            )
        conn.execute(
            insert(master_runs).values(
                trigger="manual",
                started_at=AT,
                finished_at=AT,
                status="ok",
                snapshot_ids=snapshots,
                stats={"sources": {source: {"status": "ok"} for source in sources}},
            )
        )
        for code, kind, exchange in (
            ("999001.SH", "stock", "SH"),
            ("999002.SH", "etf", "SH"),
            ("999003.BJ", "stock", "BJ"),
            ("999005.SH", "index", "SH"),
        ):
            conn.execute(
                insert(securities).values(
                    code=code,
                    type=kind,
                    name="合成证券" + code[:6],
                    exchange=exchange,
                    board="main" if kind == "stock" and exchange == "SH" else None,
                    list_date=dt.date(2020, 1, 2),
                    list_date_basis="listing",
                    listing_status="listed",
                    risk_flag="st" if kind == "stock" else None,
                    master_source="exchange",
                    master_as_of=AT,
                )
            )
        conn.execute(
            insert(security_name_history).values(
                code="999001.SH",
                name="合成曾用名",
                valid_from=dt.date(2020, 1, 2),
                valid_until=dt.date(2021, 1, 2),
                source="exchange_diff",
                snapshot_id=snapshots[0],
            )
        )
        conn.execute(
            insert(security_code_history).values(
                code="999003.BJ",
                old_code="999004.BJ",
                valid_from=dt.date(2020, 1, 2),
                source="bse_code_map",
            )
        )
    yield engine
    engine.dispose()


@pytest.fixture
def env(database: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    original, original_pair = socket.socket.connect, socket.socketpair
    local = threading.local()

    def pair(*args: Any, **kwargs: Any) -> Any:
        local.self_pipe = True
        try:
            return original_pair(*args, **kwargs)
        finally:
            local.self_pipe = False

    def connect(sock: Any, address: Any) -> Any:
        assert address[:2] == ("127.0.0.1", 55498) or (
            getattr(local, "self_pipe", False) and address[0] == "127.0.0.1"
        ), "T-B100 forbids non-test network"
        return original(sock, address)

    monkeypatch.setattr(socket, "socketpair", pair)
    monkeypatch.setattr(socket.socket, "connect", connect)
    a, b, lid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with database.begin() as conn:
        for ident in (a, b):
            conn.execute(
                insert(users).values(
                    id=ident,
                    username="tb100_" + ident.hex[:12],
                    display_name="纯合成用户",
                    password_hash=uuid.uuid4().hex,
                    role="user",
                    status="approved",
                )
            )
        conn.execute(
            insert(user_data_licences).values(
                id=lid,
                user_id=a,
                provider="mairui",
                ciphertext=uuid.uuid4().bytes * 4,
                licence_hmac=uuid.uuid4().bytes * 2,
                seal_key_version=1,
                tier="free",
                status="active",
            )
        )
    sessions = {
        str(ident): Session("synthetic", str(ident), "synthetic-csrf", AT.isoformat())
        for ident in (a, b)
    }
    settings = Settings(_env_file=None, app_env="test", session_cookie_secure=False)
    app = create_app(settings)
    api_engine = create_engine(DSN.replace("postgres@", "aia_api@"), hide_parameters=True)
    app.dependency_overrides[get_engine] = lambda: api_engine
    app.dependency_overrides[get_session_store] = lambda: SimpleNamespace(
        get=lambda sid: sessions.get(sid),
        revoke_user=lambda uid: None,
    )
    client = TestClient(app, raise_server_exceptions=False)
    client.cookies.set(SESSION_COOKIE, str(a))
    yield SimpleNamespace(owner=database, api=api_engine, client=client, a=a, b=b, lid=lid)
    client.close()
    api_engine.dispose()


def test_profile_public_fields_owned_gaps_and_private_etag(env: Any) -> None:
    e = env
    result = e.client.get("/api/v1/securities/999001.SH")
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["name"] == "合成证券999001"
    assert body["former_names"] == [{"name": "合成曾用名", "until": "2021-01-02"}]
    assert body["master_as_of"] == "2031-01-02"
    assert body["data_status"] == "partial"
    assert body["data_as_of"] is None
    assert {gap["reason"] for gap in body["gaps"]} == {"not_yet_published"}
    assert set(body) == {
        "security_code",
        "name",
        "type",
        "exchange",
        "board",
        "list_date",
        "list_date_basis",
        "delist_date",
        "listing_status",
        "risk_flag",
        "former_names",
        "code_history",
        "master_as_of",
        "attribution",
        "industry",
        "concepts",
        "total_shares",
        "float_shares",
        "suspended",
        "sources",
        "data_status",
        "data_as_of",
        "gaps",
    }
    assert "private" in result.headers["cache-control"]
    tag = result.headers["etag"]
    assert tag.startswith('W/"')
    assert (
        e.client.get("/api/v1/securities/999001.SH", headers={"If-None-Match": tag}).status_code
        == 304
    )
    e.client.cookies.set(SESSION_COOKIE, str(e.b))
    other = e.client.get("/api/v1/securities/999001.SH", headers={"If-None-Match": tag})
    assert other.status_code == 200
    assert {gap["reason"] for gap in other.json()["gaps"]} == {"data_licence_unavailable"}
    assert other.json()["industry"] is None
    with e.api.connect() as conn, pytest.raises(DBAPIError):
        conn.execute(select(user_data_licences.c.ciphertext))


@pytest.mark.parametrize("code", ["999002.SH", "999005.SH"])
def test_profile_etf_and_index_do_not_invent_nonapplicable_gaps(env: Any, code: str) -> None:
    response = env.client.get("/api/v1/securities/" + code)
    assert response.status_code == 200
    body = response.json()
    assert body["board"] is None
    assert body["list_date_basis"] is None
    assert body["industry"] is None
    assert body["concepts"] == []
    assert [gap["key"] for gap in body["gaps"]] == ["suspended"]


def test_profile_old_and_unknown_codes_are_404_and_search_is_not_shadowed(env: Any) -> None:
    e = env
    old = e.client.get("/api/v1/securities/999004.BJ")
    assert old.status_code == 404
    assert old.json()["error"]["details"]["superseded_by"] == "999003.BJ"
    assert e.client.get("/api/v1/securities/888888.SH").status_code == 404
    current = e.client.get("/api/v1/securities/999003.BJ").json()
    assert current["code_history"] == [{"security_code": "999004.BJ", "until": None}]
    search = e.client.get("/api/v1/securities/search?q=999001")
    assert search.status_code == 200, search.text
    assert search.json()["items"][0]["security_code"] == "999001.SH"


@pytest.mark.parametrize("case", ["held", "paused", "expired", "pending"])
def test_profile_unusable_owned_licence_never_reads_other_user_data(env: Any, case: str) -> None:
    e = env
    with e.owner.begin() as conn:
        if case == "held":
            conn.execute(insert(user_data_licence_holds).values(user_id=e.a))
        else:
            changes = {
                "paused": {"paused_until": dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)},
                "expired": {"expires_on": dt.date(2001, 1, 1)},
                "pending": {"status": "pending_verification"},
            }
            conn.execute(
                update(user_data_licences)
                .where(user_data_licences.c.id == e.lid)
                .values(**changes[case])
            )
    response = e.client.get("/api/v1/securities/999001.SH")
    assert response.status_code == 200
    assert {gap["reason"] for gap in response.json()["gaps"]} == {"data_licence_unavailable"}


def test_profile_authentication_precedes_conditional_response(env: Any) -> None:
    e = env
    e.client.cookies.clear()
    response = e.client.get("/api/v1/securities/999001.SH", headers={"If-None-Match": "*"})
    assert response.status_code == 401
    e.client.cookies.set(SESSION_COOKIE, str(e.a))
    with e.owner.begin() as conn:
        conn.execute(update(users).where(users.c.id == e.a).values(status="pending"))
    assert e.client.get("/api/v1/securities/999001.SH").status_code == 403
