# ruff: noqa: S101, ANN401, ANN202, S603, S607, S106, PT018, PT022, SIM222, E501, I001
"""T-B126：/watchlist 列表、添加、删除。契约只读参照 4c89336:docs/contracts/watchlist.md。

隔离 PG：仅在 o61-pg 127.0.0.1:55461 自建临时库，用后删除。
不连接、不删除 o53/o55/o57/o60、tt51_tpl、o61_tmp_0030。
"""

from __future__ import annotations

import json
import re
import subprocess
import uuid
from argparse import Namespace
from collections.abc import Iterator
from typing import Any
from unittest import mock

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from psycopg import sql
from sqlalchemy import create_engine, func, insert, select, text
from sqlalchemy.engine import Engine, URL

from app.auth.deps import get_engine, get_redis, get_session_store
from app.auth.sessions import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE, Session
from app.config import Settings
from app.db.migration_check import BACKEND, require_single_head, script_directory
from app.db.tables.market import securities, security_code_history
from app.db.tables.membership import entitlement_overrides
from app.db.tables.realtime import user_realtime_prefs
from app.db.tables.research import watchlist_items
from app.db.tables.strategy import symbol_horizon_assessments
from app.db.tables.users import users
from app.main import create_app

HOST = "127.0.0.1"
PORT = 55461
USER = "postgres"
FORBIDDEN_DBS = frozenset({"tt51_tpl", "o61_tmp_0030"})
_SAFE_TMP = re.compile(r"^o61_tmp_b126_[a-z0-9]+$")
_O61 = "o61-pg"

STOCKS = ("600000.SH", "600001.SH", "600002.SH", "000001.SZ", "510300.SH", "600006.SH")
INDEX = "000300.SH"
DELISTED = "000002.SZ"
UNKNOWN = "600999.SH"
OLD_BJ = "430001.BJ"
NEW_BJ = "830001.BJ"


class _MemRedis:
    """仅覆盖 idempotency.run 与队列探测所需的 set/get/delete/lpush。"""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self.lpushed: list[Any] = []

    def set(self, name: str, value: object, nx: bool = False, ex: object = None) -> bool:
        key = str(name)
        if nx and key in self._data:
            return False
        self._data[key] = value if isinstance(value, str) else str(value)
        return True

    def get(self, name: str) -> str | None:
        return self._data.get(str(name))

    def delete(self, name: str) -> int:
        return 1 if self._data.pop(str(name), None) is not None else 0

    def lpush(self, name: str, *values: object) -> int:
        self.lpushed.append((name, values))
        return len(values)


def _require_o61() -> None:
    proc = subprocess.run(
        ["docker", "ps", "--no-trunc", "--format", "{{.ID}} {{.Names}}"],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        pytest.fail("无法查询 docker 以核验 55461 归属")
    hits: list[str] = []
    for line in proc.stdout.splitlines():
        cid, _, name = line.partition(" ")
        inspect = subprocess.run(
            ["docker", "inspect", cid], text=True, capture_output=True, check=False
        )
        if inspect.returncode != 0 or not inspect.stdout.strip():
            continue
        info = json.loads(inspect.stdout)[0]
        mode = (info.get("HostConfig") or {}).get("NetworkMode")
        cmd = " ".join(str(x) for x in (info.get("Config") or {}).get("Cmd") or [])
        if mode == "host" and f"port={PORT}" in cmd:
            hits.append(name.lstrip("/"))
    if hits != [_O61]:
        pytest.fail(f"拒绝建库：{HOST}:{PORT} 归属 {hits or '未知'}，须为 {_O61}")


def _admin():
    return psycopg.connect(
        host=HOST, port=PORT, user=USER, dbname="postgres", autocommit=True
    )


def _url(dbname: str) -> URL:
    return URL.create(
        "postgresql+psycopg", username=USER, password=None, host=HOST, port=PORT, database=dbname
    )


def _create_temp_db() -> str:
    _require_o61()
    name = "o61_tmp_b126_" + uuid.uuid4().hex[:10]
    assert _SAFE_TMP.fullmatch(name)
    assert name not in FORBIDDEN_DBS
    with _admin() as admin:
        existing = {r[0] for r in admin.execute("SELECT datname FROM pg_database")}
        for banned in FORBIDDEN_DBS:
            assert banned in existing or True  # 存在与否都不碰
        assert name not in existing
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    return name


def _drop_temp_db(name: str) -> None:
    assert _SAFE_TMP.fullmatch(name) and name not in FORBIDDEN_DBS
    with _admin() as admin:
        admin.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
        )


def _alembic(url: URL) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.cmd_opts = Namespace(x=["url=" + url.render_as_string(hide_password=False)])
    return cfg


def _upgrade(url: URL, revision: str) -> None:
    command.upgrade(_alembic(url), revision)


def _downgrade(url: URL, revision: str) -> None:
    command.downgrade(_alembic(url), revision)


def _seed_master(conn: Any) -> None:
    rows = [
        ("600000.SH", "stock", "合成浦发", "SH", "listed"),
        ("600001.SH", "stock", "合成邯钢", "SH", "listed"),
        ("600002.SH", "stock", "合成齐鲁", "SH", "listed"),
        ("000001.SZ", "stock", "合成平安", "SZ", "listed"),
        ("510300.SH", "etf", "合成沪深300ETF", "SH", "listed"),
        ("600006.SH", "stock", "合成缺失", "SH", "missing_from_list"),
        (INDEX, "index", "沪深300", "SH", "listed"),
        (DELISTED, "stock", "已退市合成", "SZ", "delisted"),
        (NEW_BJ, "stock", "北交所新码", "BJ", "listed"),
    ]
    for code, typ, name, exch, status in rows:
        conn.execute(
            insert(securities).values(
                code=code,
                type=typ,
                name=name,
                exchange=exch,
                board="main" if typ != "etf" else None,
                listing_status=status,
            )
        )
    conn.execute(
        insert(security_code_history).values(
            code=NEW_BJ,
            old_code=OLD_BJ,
            valid_from=__import__("datetime").date(2020, 1, 1),
            source="bse_code_map",
        )
    )


def _insert_user(conn: Any, ident: uuid.UUID, username: str, status: str = "approved") -> None:
    conn.execute(
        insert(users).values(
            id=ident,
            username=username,
            display_name=username,
            role="user",
            status=status,
            password_hash="x",
        )
    )


@pytest.fixture(scope="module")
def world() -> Iterator[dict[str, Any]]:
    name = _create_temp_db()
    url = _url(name)
    engine: Engine | None = None
    client: TestClient | None = None
    try:
        _upgrade(url, "head")
        engine = create_engine(url, hide_parameters=True)
        ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
        now = __import__("datetime").datetime.now(__import__("datetime").UTC)
        with engine.begin() as conn:
            _seed_master(conn)
            for i, ident in enumerate(ids):
                _insert_user(conn, ident, f"tb126u{i}{ident.hex[:8]}")
        csrf = "tb126-csrf-token"
        sessions = {
            str(ident): Session("synthetic", str(ident), csrf, now.isoformat()) for ident in ids
        }
        store = mock.Mock()
        store.get.side_effect = lambda sid: sessions.get(sid)
        store.revoke_user.return_value = None
        redis = _MemRedis()
        settings = Settings(
            _env_file=None,
            app_env="test",
            session_cookie_secure=False,
            database_url=None,
            redis_url=None,
        )
        app = create_app(settings)
        app.dependency_overrides[get_engine] = lambda: engine
        app.dependency_overrides[get_session_store] = lambda: store
        app.dependency_overrides[get_redis] = lambda: redis
        client = TestClient(app)
        yield {
            "engine": engine,
            "client": client,
            "ids": ids,
            "csrf": csrf,
            "redis": redis,
            "settings": settings,
            "caps": settings.business.realtime.watchlist,
        }
    finally:
        if client is not None:
            client.close()
        if engine is not None:
            engine.dispose()
        _drop_temp_db(name)


@pytest.fixture
def api(world: dict[str, Any]) -> Iterator[dict[str, Any]]:
    engine: Engine = world["engine"]
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM app.watchlist_items"))
        conn.execute(text("DELETE FROM app.entitlement_overrides"))
        conn.execute(text("DELETE FROM app.user_realtime_prefs"))
        conn.execute(text("DELETE FROM app.symbol_horizon_assessments"))
    world["redis"].lpushed.clear()
    world["redis"]._data.clear()
    yield world


def _login(client: TestClient, user_id: uuid.UUID, csrf: str, *, writes: bool = False) -> dict[str, str]:
    client.cookies.set(SESSION_COOKIE, str(user_id))
    client.cookies.set(CSRF_COOKIE, csrf)
    headers = {CSRF_HEADER: csrf} if writes else {}
    return headers


def _err(resp: Any) -> dict[str, Any]:
    body = resp.json()["error"]
    return body


def _post(api: dict[str, Any], body: dict[str, Any], *, user: int = 0, headers: dict[str, str] | None = None) -> Any:
    client, ids, csrf = api["client"], api["ids"], api["csrf"]
    h = _login(client, ids[user], csrf, writes=True)
    if headers:
        h.update(headers)
    return client.post("/api/v1/watchlist", json=body, headers=h)


def _get(api: dict[str, Any], *, user: int = 0) -> Any:
    client, ids, csrf = api["client"], api["ids"], api["csrf"]
    _login(client, ids[user], csrf)
    return client.get("/api/v1/watchlist")


def _delete(api: dict[str, Any], code: str, *, user: int = 0) -> Any:
    client, ids, csrf = api["client"], api["ids"], api["csrf"]
    h = _login(client, ids[user], csrf, writes=True)
    return client.delete("/api/v1/watchlist/" + code, headers=h)


def test_unauthenticated_is_401(api: dict[str, Any]) -> None:
    client: TestClient = api["client"]
    client.cookies.clear()
    for resp in (
        client.get("/api/v1/watchlist"),
        client.post("/api/v1/watchlist", json={"security_code": "600000.SH"}),
        client.delete("/api/v1/watchlist/600000.SH"),
    ):
        assert resp.status_code == 401
        assert _err(resp)["code"] == "AUTH_REQUIRED"


def test_list_add_delete_roundtrip(api: dict[str, Any]) -> None:
    added = _post(api, {"security_code": "600000"})
    assert added.status_code == 201, added.text
    body = added.json()
    assert body["security_code"] == "600000.SH"
    assert body["name"] == "合成浦发"
    assert body["group"] is None and body["note"] is None
    assert body["focus"] is False
    assert body["refresh_tier"] is None
    assert body["added_at"]
    listed = _get(api)
    assert listed.status_code == 200
    payload = listed.json()
    assert [i["security_code"] for i in payload["items"]] == ["600000.SH"]
    assert payload["caps"]["watchlist"] == api["caps"].per_user_cap
    assert payload["caps"]["focus"] == api["caps"].focus_cap
    deleted = _delete(api, "600000")
    assert deleted.status_code == 204
    assert deleted.content in {b"", b"null", b"null\n"} or not deleted.content
    after = _get(api)
    assert after.json()["items"] == []
    with api["engine"].connect() as conn:
        row = conn.execute(select(watchlist_items).where(watchlist_items.c.security_code == "600000.SH")).one()
        assert row.removed_at is not None


def test_get_sort_added_at_asc_skips_removed_and_others(api: dict[str, Any]) -> None:
    _post(api, {"security_code": "600000.SH"})
    _post(api, {"security_code": "600001.SH"})
    _post(api, {"security_code": "600002.SH"})
    assert _delete(api, "600001.SH").status_code == 204
    # 他人行不得出现
    assert _post(api, {"security_code": "000001.SZ"}, user=1).status_code == 201
    listed = _get(api)
    assert [i["security_code"] for i in listed.json()["items"]] == ["600000.SH", "600002.SH"]
    empty = _get(api, user=2)
    assert empty.status_code == 200
    assert empty.json()["items"] == []
    assert empty.json()["caps"]["watchlist"] == api["caps"].per_user_cap


def test_duplicate_add_is_409_and_idempotency_key_replays_201(api: dict[str, Any]) -> None:
    first = _post(api, {"security_code": "600000.SH"})
    assert first.status_code == 201
    with api["engine"].connect() as conn:
        existing_id = conn.execute(
            select(watchlist_items.c.id).where(
                watchlist_items.c.user_id == api["ids"][0],
                watchlist_items.c.security_code == "600000.SH",
                watchlist_items.c.removed_at.is_(None),
            )
        ).scalar_one()
    # 规范化后同一代码
    dup = _post(api, {"security_code": "sh600000"})
    assert dup.status_code == 409
    err = _err(dup)
    assert err["code"] == "CONFLICT"
    assert err["details"]["field"] == "security_code"
    assert err["details"]["existing_id"] == str(existing_id)
    # 他人已有不影响本人
    assert _post(api, {"security_code": "600000.SH"}, user=1).status_code == 201
    key = {"Idempotency-Key": "watchlist-k1"}
    body = {"security_code": "600001.SH"}
    a = _post(api, body, headers=key)
    b = _post(api, body, headers=key)
    assert a.status_code == 201 and b.status_code == 201
    assert a.json() == b.json()
    with api["engine"].connect() as conn:
        n = conn.execute(
            select(func.count())
            .select_from(watchlist_items)
            .where(
                watchlist_items.c.user_id == api["ids"][0],
                watchlist_items.c.security_code == "600001.SH",
                watchlist_items.c.removed_at.is_(None),
            )
        ).scalar_one()
        assert n == 1


def test_delete_missing_or_others_is_404_invalid_is_400(api: dict[str, Any]) -> None:
    assert _delete(api, "600000.SH").status_code == 404
    assert _err(_delete(api, "600000.SH"))["code"] == "NOT_FOUND"
    assert _post(api, {"security_code": "000001.SZ"}, user=1).status_code == 201
    assert _delete(api, "000001.SZ").status_code == 404
    with api["engine"].connect() as conn:
        n = conn.execute(
            select(func.count())
            .select_from(watchlist_items)
            .where(watchlist_items.c.security_code == "000001.SZ", watchlist_items.c.removed_at.is_(None))
        ).scalar_one()
        assert n == 1
    assert _post(api, {"security_code": "600000.SH"}).status_code == 201
    assert _delete(api, "600000.SH").status_code == 204
    assert _delete(api, "600000.SH").status_code == 404
    bad = _delete(api, "60000X")
    assert bad.status_code == 400
    err = _err(bad)
    assert err["code"] == "VALIDATION_ERROR"
    assert err["details"]["fields"][0]["field"] == "security_code"
    assert err["details"]["fields"][0]["issue"] == "invalid"


def test_invalid_and_ineligible_codes_rejected(api: dict[str, Any]) -> None:
    cases = [
        ({"security_code": "ABC"}, "invalid"),
        ({"security_code": UNKNOWN}, "unknown_security"),
        ({"security_code": INDEX}, "security_type_not_supported"),
        ({"security_code": DELISTED}, "delisted"),
        ({"security_code": OLD_BJ}, "superseded"),
    ]
    for body, issue in cases:
        resp = _post(api, body)
        assert resp.status_code == 400, (body, resp.text)
        fields = _err(resp)["details"]["fields"]
        assert fields[0]["field"] == "security_code"
        assert fields[0]["issue"] == issue
        if issue == "superseded":
            assert fields[0]["superseded_by"] == NEW_BJ
    # ETF 与 missing_from_list 允许
    assert _post(api, {"security_code": "510300.SH"}).status_code == 201
    assert _post(api, {"security_code": "600006.SH"}).status_code == 201
    with api["engine"].connect() as conn:
        n = conn.execute(select(func.count()).select_from(watchlist_items)).scalar_one()
        assert n == 2


def test_group_note_rules_and_unknown_key(api: dict[str, Any]) -> None:
    only = _post(api, {"security_code": "600000.SH"})
    assert only.status_code == 201
    assert only.json()["group"] is None and only.json()["note"] is None
    empty = _post(api, {"security_code": "600001.SH", "group": ""})
    assert empty.status_code == 201 and empty.json()["group"] is None
    long_note = _post(api, {"security_code": "600002.SH", "note": "汉" * 501})
    assert long_note.status_code == 400
    field = _err(long_note)["details"]["fields"][0]
    assert field == {"field": "note", "issue": "too_long"}
    extra = _post(api, {"security_code": "600002.SH", "focus": True})
    assert extra.status_code == 400
    with api["engine"].connect() as conn:
        assert (
            conn.execute(
                select(func.count())
                .select_from(watchlist_items)
                .where(watchlist_items.c.security_code == "600002.SH")
            ).scalar_one()
            == 0
        )


def test_focus_read_from_prefs_put_not_2xx(api: dict[str, Any]) -> None:
    assert _post(api, {"security_code": "600000.SH"}).status_code == 201
    with api["engine"].begin() as conn:
        conn.execute(
            insert(user_realtime_prefs).values(
                user_id=api["ids"][0], notify_cadence="1m", focus_codes=["600000.SH"]
            )
        )
    listed = _get(api).json()["items"]
    assert listed[0]["focus"] is True
    put = api["client"].request(
        "PUT",
        "/api/v1/watchlist/600000.SH/focus",
        json={"focus": True},
        headers=_login(api["client"], api["ids"][0], api["csrf"], writes=True),
    )
    assert put.status_code < 200 or put.status_code >= 300


def test_readd_inserts_new_row_without_old_group_note(api: dict[str, Any]) -> None:
    first = _post(api, {"security_code": "600000.SH", "group": "旧组", "note": "旧注"})
    assert first.status_code == 201
    with api["engine"].connect() as conn:
        old_id = conn.execute(
            select(watchlist_items.c.id).where(
                watchlist_items.c.user_id == api["ids"][0],
                watchlist_items.c.security_code == "600000.SH",
                watchlist_items.c.removed_at.is_(None),
            )
        ).scalar_one()
    assert _delete(api, "600000.SH").status_code == 204
    again = _post(api, {"security_code": "600000.SH", "note": "新注"})
    assert again.status_code == 201
    assert again.json()["note"] == "新注"
    assert again.json()["group"] is None
    items = _get(api).json()["items"]
    assert len(items) == 1 and items[0]["note"] == "新注"
    with api["engine"].connect() as conn:
        old = conn.execute(select(watchlist_items).where(watchlist_items.c.id == old_id)).one()
        assert old.removed_at is not None and old.note == "旧注"
        new_id = conn.execute(
            select(watchlist_items.c.id).where(
                watchlist_items.c.user_id == api["ids"][0],
                watchlist_items.c.security_code == "600000.SH",
                watchlist_items.c.removed_at.is_(None),
            )
        ).scalar_one()
        assert new_id != old_id


def test_others_data_invisible(api: dict[str, Any]) -> None:
    assert _post(api, {"security_code": "600000.SH"}, user=1).status_code == 201
    mine = _get(api, user=0)
    assert mine.json()["items"] == []
    assert _delete(api, "600000.SH", user=0).status_code == 404
    assert _post(api, {"security_code": "600000.SH"}, user=0).status_code == 201


def test_methods_not_allowed_and_refresh_tier_null_no_horizon_side_effects(api: dict[str, Any]) -> None:
    headers = _login(api["client"], api["ids"][0], api["csrf"], writes=True)
    get_item = api["client"].get("/api/v1/watchlist/600000.SH")
    assert get_item.status_code == 405
    assert "DELETE" in (get_item.headers.get("Allow") or "").upper()
    del_col = api["client"].delete("/api/v1/watchlist", headers=headers)
    assert del_col.status_code == 405
    allow = (del_col.headers.get("Allow") or "").upper()
    assert "GET" in allow and "POST" in allow
    with api["engine"].connect() as conn:
        before = conn.execute(select(func.count()).select_from(symbol_horizon_assessments)).scalar_one()
    created = _post(api, {"security_code": "600000.SH"})
    assert created.status_code == 201
    assert created.json()["refresh_tier"] is None
    assert all(i["refresh_tier"] is None for i in _get(api).json()["items"])
    with api["engine"].connect() as conn:
        after = conn.execute(select(func.count()).select_from(symbol_horizon_assessments)).scalar_one()
    assert after == before
    assert api["redis"].lpushed == []


def test_cap_and_validation_order_400_400_409_403_201(api: dict[str, Any]) -> None:
    """鉴权之后：请求体 400 → 代码 400 → 重复 409 → 上限 403 → 201。"""
    with api["engine"].begin() as conn:
        conn.execute(
            insert(entitlement_overrides).values(
                user_id=api["ids"][0],
                key="watchlist.per_user_cap",
                value=2,
                created_by=api["ids"][0],
            )
        )
    # 请求体 400 优先于未知代码
    body_first = _post(api, {"security_code": UNKNOWN, "note": "汉" * 501})
    assert body_first.status_code == 400
    assert _err(body_first)["details"]["fields"][0] == {"field": "note", "issue": "too_long"}
    # 代码 400 优先于（若会撞到的）重复/上限：未知代码且尚未有行
    code_first = _post(api, {"security_code": UNKNOWN})
    assert code_first.status_code == 400
    assert _err(code_first)["details"]["fields"][0]["issue"] == "unknown_security"
    assert _post(api, {"security_code": "600000.SH"}).status_code == 201
    assert _post(api, {"security_code": "600001.SH"}).status_code == 201
    # 重复 409 优先于上限 403
    dup = _post(api, {"security_code": "sh600000"})
    assert dup.status_code == 409
    assert _err(dup)["code"] == "CONFLICT"
    # 上限 403
    over = _post(api, {"security_code": "600002.SH"})
    assert over.status_code == 403
    err = _err(over)
    assert err["code"] == "ENTITLEMENT_LIMIT_REACHED"
    assert err["details"]["key"] == "watchlist.per_user_cap"
    assert err["details"]["limit"] == 2
    assert err["details"]["current"] == 2
    assert _delete(api, "600001.SH").status_code == 204
    # 删一条后 201
    assert _post(api, {"security_code": "600002.SH"}).status_code == 201


def test_migration_0031_is_single_head() -> None:
    assert require_single_head(script_directory()) == "0031"
    script = script_directory()
    assert script.get_revision("0031").down_revision == "0030"


def test_migration_upgrade_downgrade_index() -> None:
    name = _create_temp_db()
    url = _url(name)
    engine = create_engine(url, hide_parameters=True)
    try:
        _upgrade(url, "0030")
        _upgrade(url, "0031")
        with engine.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM public.alembic_version")).scalar_one() == "0031"
            exists = conn.execute(
                text(
                    "SELECT 1 FROM pg_indexes WHERE schemaname='app' "
                    "AND indexname='uq_watchlist_items_user_code_active'"
                )
            ).scalar()
            assert exists == 1
        _downgrade(url, "0030")
        with engine.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM public.alembic_version")).scalar_one() == "0030"
            exists = conn.execute(
                text(
                    "SELECT 1 FROM pg_indexes WHERE schemaname='app' "
                    "AND indexname='uq_watchlist_items_user_code_active'"
                )
            ).scalar()
            assert exists is None
    finally:
        engine.dispose()
        _drop_temp_db(name)


def test_migration_aborts_on_duplicate_active_rows() -> None:
    name = _create_temp_db()
    url = _url(name)
    engine = create_engine(url, hide_parameters=True)
    try:
        _upgrade(url, "0030")
        uid = uuid.uuid4()
        with engine.begin() as conn:
            _insert_user(conn, uid, "tb126dup" + uid.hex[:8])
            for _ in range(2):
                conn.execute(
                    insert(watchlist_items).values(
                        user_id=uid, security_code="600000.SH", group_name=None, note=None
                    )
                )
        with pytest.raises(Exception, match="duplicate") as failed:
            _upgrade(url, "0031")
        # 不打印代码与用户
        assert "600000" not in str(failed.value)
        assert str(uid) not in str(failed.value)
        with engine.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM public.alembic_version")).scalar_one() == "0030"
            n = conn.execute(select(func.count()).select_from(watchlist_items)).scalar_one()
            assert n == 2
            exists = conn.execute(
                text(
                    "SELECT 1 FROM pg_indexes WHERE schemaname='app' "
                    "AND indexname='uq_watchlist_items_user_code_active'"
                )
            ).scalar()
            assert exists is None
    finally:
        engine.dispose()
        _drop_temp_db(name)


def test_existing_id_details_match_row(api: dict[str, Any]) -> None:
    created = _post(api, {"security_code": "600000.SH"})
    assert created.status_code == 201
    with api["engine"].connect() as conn:
        row_id = conn.execute(
            select(watchlist_items.c.id).where(
                watchlist_items.c.user_id == api["ids"][0],
                watchlist_items.c.security_code == "600000.SH",
                watchlist_items.c.removed_at.is_(None),
            )
        ).scalar_one()
    dup = _post(api, {"security_code": "600000.SH"})
    assert _err(dup)["details"]["existing_id"] == str(row_id)
