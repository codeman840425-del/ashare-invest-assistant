"""T-T24：删除用户数据 CLI（plan §7.3，T-B16-core 45589c2 / r2 8fd9502，迁移 0011/0013）集成测试。

一次性库（T-T23/T-T22 的 ``authdb``：testcontainers 上的临时库，模块结束 DROP），绝不连共享库
（be-b03a-pg / aia-t01）。``aia_maint`` 角色在测试容器里临时创建（随机口令，只存在于本进程内存与
``tmp_path`` 下的 DSN 文件），授予 app/ops/market 三个 schema 的 DML——这是测试侧近似；正式授权由运维在
``deploy/db/roles/grants.sql`` 落地（plan §7.3 第 5 点，尚未提交）。

覆盖：
- 参数：非法 uuid → 2；不存在的用户 → 1 拒绝。
- dry-run：rc 0、只读（目标用户各表行数不变）、输出不含证书原文。
- 守卫：未配置 aia_maint 时 ``--execute`` → 1；确认串不匹配 → 1；两者都不改库。
- 0013 触发器：非 aia_maint 角色把 users.status 置 purging → 拒绝；INSERT 直接写 purging → 拒绝。
- 执行：rc 0；用户行、证书行、暂停记录物理删除；指向该用户的审计 actor/target 置 NULL；
  结束审计 ``admin.user_data_deleted`` 只含行数、不含 user_id / 用户名；会话失效、Redis 中无该用户键；
  ``ops.pending_file_purges`` 先重试并删除；旁观用户数据不受影响；全程输出不含证书原文。

origin（0cb78ad）没有该 CLI / 迁移 0011–0013 → imperative xfail，owner：T-B16（45589c2 / 8fd9502），
运维推送到 origin。
"""

from __future__ import annotations

import importlib
import importlib.util
import secrets
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pytest

_spec = importlib.util.spec_from_file_location("tt24_cli_t23", Path(__file__).with_name("test_contract_v028_t_t23.py"))
_t23 = importlib.util.module_from_spec(_spec)
try:
    _spec.loader.exec_module(_t23)  # type: ignore[union-attr]
except pytest.skip.Exception as exc:
    pytest.skip(str(exc), allow_module_level=True)

authdb, sql, app_client, mkuser, session, make_settings = (
    _t23.authdb, _t23.sql, _t23.app_client, _t23.mkuser, _t23.session, _t23.make_settings)
API, Rec, fake_licence, put, leak_count = _t23.API, _t23.Rec, _t23.fake_licence, _t23.put, _t23.leak_count

O_B16 = "后端 T-B16（删除用户数据 CLI 45589c2 / r2 8fd9502、迁移 0011/0013；在本地 main，未推 origin）"
MAINT = "aia_maint"

pytestmark = [pytest.mark.integration]


def _cli() -> Any:
    try:
        return importlib.import_module("app.cli.delete_user_data")
    except ModuleNotFoundError:
        pytest.xfail(O_B16 + "：app.cli.delete_user_data 不存在")


def _require_0013(sql: Callable[..., Any]) -> None:
    v = sql("SELECT version_num FROM alembic_version")[0][0]
    if v < "0013":
        pytest.xfail(f"{O_B16}：库 head = {v}")


def _dsn(url: str, user: str, pw: str) -> str:
    p = urlsplit(url)
    host = p.hostname or "localhost"
    netloc = f"{user}:{pw}@{host}" + (f":{p.port}" if p.port else "")
    return urlunsplit(("postgresql+psycopg", netloc, p.path, p.query, p.fragment))


def _mk_role(authdb: SimpleNamespace, name: str) -> str:
    """测试容器内临时角色（集群级，随机口令），授予本库 app/ops/market 的 DML；返回 DSN。"""
    import psycopg

    pw = secrets.token_hex(16)
    with psycopg.connect(authdb.url, autocommit=True) as c:
        exists = c.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,)).fetchone()
        verb = "ALTER" if exists else "CREATE"
        c.execute(f"{verb} ROLE {name} LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '{pw}'")
        c.execute(f'GRANT CONNECT ON DATABASE "{authdb.name}" TO {name}')
        for s in ("app", "ops", "market"):
            c.execute(f"GRANT USAGE ON SCHEMA {s} TO {name}")
            c.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {s} TO {name}")
            c.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {s} TO {name}")
            c.execute(f"GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA {s} TO {name}")
    return _dsn(authdb.url, name, pw)


@pytest.fixture(scope="module")
def roles(authdb: SimpleNamespace) -> Iterator[SimpleNamespace]:
    yield SimpleNamespace(maint=_mk_role(authdb, MAINT), other=_mk_role(authdb, "tt24_notmaint"))


@pytest.fixture
def cli(authdb: SimpleNamespace, sql: Callable[..., Any], monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path) -> SimpleNamespace:
    mod = _cli()
    _require_0013(sql)
    for k in ("AIA_MAINT_DATABASE_URL", "AIA_MAINT_DATABASE_URL_FILE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DATABASE_URL", authdb.url)
    monkeypatch.setenv("REDIS_URL", authdb.redis_url)
    imports = tmp_path / "imports"
    imports.mkdir()
    monkeypatch.setenv("AIA_IMPORTS_DIR", str(imports))
    return SimpleNamespace(mod=mod, imports=imports, tmp=tmp_path, mp=monkeypatch, db=authdb.url,
                           redis=authdb.redis_url)


def _run(cli: SimpleNamespace, capsys: pytest.CaptureFixture[str], *argv: str, confirm: str = "") -> SimpleNamespace:
    # 其它夹具（app_client/make_settings）可能在本夹具之后改写环境；每次调用前重设。
    cli.mp.setenv("DATABASE_URL", cli.db)
    cli.mp.setenv("REDIS_URL", cli.redis)
    cli.mp.setenv("AIA_IMPORTS_DIR", str(cli.imports))
    rc = cli.mod.main(list(argv), confirm=lambda _prompt: confirm)
    cap = capsys.readouterr()
    return SimpleNamespace(rc=rc, out=cap.out, err=cap.err, text=cap.out + cap.err)


def _footprint(sql: Callable[..., Any], uid: str) -> dict[str, int]:
    q = {
        "users": "SELECT count(*) FROM app.users WHERE id = :u",
        "licences": "SELECT count(*) FROM app.user_data_licences WHERE user_id = :u",
        "holds": "SELECT count(*) FROM app.user_data_licence_holds WHERE user_id = :u",
        "audit_actor": "SELECT count(*) FROM app.audit_logs WHERE actor_id = :u",
        "audit_target": "SELECT count(*) FROM app.audit_logs WHERE target_id = CAST(:u AS text)",
        "licence_events": "SELECT count(*) FROM ops.data_licence_events WHERE user_id = :u",
    }
    return {k: sql(v, u=uid)[0][0] for k, v in q.items()}


@pytest.fixture
def victim(session: Callable[..., SimpleNamespace], mkuser: Callable[..., Any], sql: Callable[..., Any]) -> SimpleNamespace:
    """目标用户：已登录（Redis 有会话）、设置过证书、被管理员暂停（审计 + 暂停记录），另有一位旁观用户。"""
    s = session()
    lic = fake_licence()
    assert put(Rec(s), lic).status_code == 202
    admin = session(mkuser(role="admin"))
    r = Rec(admin)("POST", f"/admin/data-licences/{s.user.id}/pause", json={"reason": "T-T24 理由文本"})
    assert r.status_code == 204, r.text[:300]
    by = session()
    blic = fake_licence()
    assert put(Rec(by), blic).status_code == 202
    return SimpleNamespace(s=s, uid=s.user.id, lic=lic, admin=admin, by=by, blic=blic)


def test_cli_bad_uuid_and_unknown_user(cli: SimpleNamespace, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(cli, capsys, "--user-id", "not-a-uuid").rc == 2
    r = _run(cli, capsys, "--user-id", str(uuid.uuid4()))
    assert r.rc == 1 and "拒绝" in r.err


def test_cli_dispatcher_usage(cli: SimpleNamespace, capsys: pytest.CaptureFixture[str]) -> None:
    disp = importlib.import_module("app.cli.__main__")
    assert disp.main([]) == 2
    assert disp.main(["nope"]) == 2
    assert disp.main(["delete-user-data", "--user-id", "x"]) == 2
    capsys.readouterr()


def test_cli_dry_run_is_read_only(cli: SimpleNamespace, victim: SimpleNamespace, sql: Callable[..., Any],
                                  capsys: pytest.CaptureFixture[str]) -> None:
    before = _footprint(sql, victim.uid)
    assert before["users"] == 1 and before["licences"] >= 1 and before["holds"] == 1
    r = _run(cli, capsys, "--user-id", victim.uid)
    assert r.rc == 0, r.text[-800:]
    assert "dry-run" in r.out and "app.user_data_licences" in r.out
    assert _footprint(sql, victim.uid) == before
    assert leak_count(victim.lic, r.text) == 0


def test_cli_execute_guards_change_nothing(cli: SimpleNamespace, victim: SimpleNamespace, roles: SimpleNamespace,
                                           sql: Callable[..., Any], capsys: pytest.CaptureFixture[str],
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    before = _footprint(sql, victim.uid)
    r = _run(cli, capsys, "--user-id", victim.uid, "--execute", confirm=victim.uid)
    assert r.rc == 1 and MAINT in r.err, "未配置 aia_maint 必须拒绝 --execute"
    f = cli.tmp / "maint.dsn"
    f.write_text(roles.maint, encoding="utf-8")
    monkeypatch.setenv("AIA_MAINT_DATABASE_URL_FILE", str(f))
    r = _run(cli, capsys, "--user-id", victim.uid, "--execute", confirm="wrong")
    assert r.rc == 1 and "确认不匹配" in r.err
    # 用非 aia_maint 的 DSN 冒充专用 DSN：current_user 检查拒绝
    monkeypatch.setenv("AIA_MAINT_DATABASE_URL_FILE", str(cli.tmp / "missing.dsn"))
    with pytest.raises(SystemExit):
        _run(cli, capsys, "--user-id", victim.uid)
    monkeypatch.delenv("AIA_MAINT_DATABASE_URL_FILE")
    monkeypatch.setenv("AIA_MAINT_DATABASE_URL", roles.other)
    r = _run(cli, capsys, "--user-id", victim.uid, "--execute", confirm=victim.uid)
    assert r.rc == 1 and "不是 aia_maint" in r.err
    assert _footprint(sql, victim.uid) == before
    assert victim.s.client.get(f"{API}/me").status_code == 200, "守卫失败时不得吊销会话"


def test_0013_trigger_only_maint_may_set_purging(victim: SimpleNamespace, roles: SimpleNamespace,
                                                 sql: Callable[..., Any]) -> None:
    import psycopg

    _cli()
    _require_0013(sql)
    plain = roles.other.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(plain) as c, pytest.raises(psycopg.Error):
        c.execute("UPDATE app.users SET status = 'purging' WHERE id = %s", (victim.uid,))
    with psycopg.connect(plain) as c, pytest.raises(psycopg.Error):
        c.execute("INSERT INTO app.users (username, password_hash, role, status) "
                  "VALUES (%s, 'x', 'user', 'purging')", ("tt24_" + secrets.token_hex(4),))
    # aia_maint 置 purging 后不删 users 行 → 提交时被延迟约束拒绝
    mplain = roles.maint.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(mplain) as c, pytest.raises(psycopg.Error):
        c.execute("UPDATE app.users SET status = 'purging' WHERE id = %s", (victim.uid,))
        c.commit()
    assert sql("SELECT status FROM app.users WHERE id = :u", u=victim.uid)[0][0] == "approved"


def test_cli_execute_purges_and_anonymizes(cli: SimpleNamespace, victim: SimpleNamespace, roles: SimpleNamespace,
                                           sql: Callable[..., Any], authdb: SimpleNamespace,
                                           capsys: pytest.CaptureFixture[str],
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    uid = victim.uid
    by_before = _footprint(sql, victim.by.user.id)
    stale = cli.imports / "stale-dir"
    stale.mkdir()
    (stale / "x.csv").write_text("x", encoding="utf-8")
    sql("INSERT INTO ops.pending_file_purges (path) VALUES (:p)", p=str(stale))
    t0 = sql("SELECT now()")[0][0]
    monkeypatch.setenv("AIA_MAINT_DATABASE_URL", roles.maint)
    r = _run(cli, capsys, "--user-id", uid, "--execute", confirm=uid)
    assert r.rc == 0, r.text[-1500:]
    assert "已提交" in r.out
    fp = _footprint(sql, uid)
    assert fp == {k: 0 for k in fp}, fp
    assert sql("SELECT count(*) FROM ops.pending_file_purges WHERE path = :p", p=str(stale))[0][0] == 0
    assert not stale.exists(), "pending_file_purges 应先重试删除"
    done = sql("SELECT actor_id, target_id, detail::text FROM app.audit_logs "
               "WHERE action = 'admin.user_data_deleted' AND at >= :t", t=t0)
    assert len(done) == 1 and done[0][0] is None and done[0][1] is None
    assert uid not in done[0][2] and victim.s.user.username not in done[0][2]
    assert '"rows"' in done[0][2]
    # 管理员对该用户的暂停审计：保留动作，但 detail 里不再有用户 id 与自由文本理由
    kept = sql("SELECT detail::text FROM app.audit_logs WHERE action LIKE 'data_licence.%' AND actor_id = :a "
               "AND at >= now() - interval '1 hour'", a=victim.admin.user.id)
    assert kept and all(uid not in d and "T-T24 理由文本" not in d for (d,) in kept)
    assert victim.s.client.get(f"{API}/me").status_code == 401, "会话应被吊销"
    assert list(authdb.redis.scan_iter(match=f"*{uid}*")) == []
    assert _footprint(sql, victim.by.user.id) == by_before, "旁观用户数据不得受影响"
    assert leak_count(victim.lic, r.text) == 0 and leak_count(victim.blic, r.text) == 0
    # 再跑一次：用户已不存在 → 拒绝
    r2 = _run(cli, capsys, "--user-id", uid, "--execute", confirm=uid)
    assert r2.rc == 1
