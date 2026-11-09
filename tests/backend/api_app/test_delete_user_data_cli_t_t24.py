"""T-T24：删除用户数据 CLI（plan §7.3，T-B16-core 45589c2 / r2 8fd9502，迁移 0011/0013）集成测试。

一次性库（T-T23/T-T22 的 ``authdb``：testcontainers 上的临时库，模块结束 DROP），绝不连共享库
（be-b03a-pg / aia-t01）。``aia_maint`` 角色在测试容器里临时创建（随机口令，只存在于本进程内存与
``tmp_path`` 下 0600 的 DSN 文件，经 ``AIA_MAINT_DATABASE_URL_FILE`` 交给 CLI；T-B49 起 CLI 只认 _FILE），
非超级用户、NOINHERIT；被测树有 ``deploy/db/roles/grants.sql`` 时按其中 ``$maint$`` 段原样授权（运维 T-O11），
没有时（origin 0cb78ad）退回授予 app/ops/market 三个 schema 的 DML 的测试侧近似。DSN / 口令从不打印。

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
import re
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


GRANTS = _t23.REPO / "deploy" / "db" / "roles" / "grants.sql"
#: grants.sql 的 $maint$ / $o33$ / $o60_gate_funcs$ 自检会检查 aia_api / aia_ingest；测试库里换成 NOLOGIN 占位角色。
_MAINT_STUBS = {"aia_api": "tt24_api_stub", "aia_ingest": "tt24_ingest_stub"}
#: T-A76 §7 C：夹具须依次套用这三段（生产 $o33$ 才给 batches 列级 SELECT+DELETE）。
_MAINT_GRANT_TAGS = ("maint", "o33", "o60_gate_funcs")


def _stub_api_ingest_roles(block: str) -> str:
    """把块内 aia_api / aia_ingest 标识符（引号内外）换成占位角色；不碰 aia_maint。"""
    for old, new in _MAINT_STUBS.items():
        block = re.sub(rf"(?<!\w){re.escape(old)}(?!\w)", new, block)
    return block


def _maint_grants_block() -> str | None:
    """grants.sql 中 ``$maint$`` + ``$o33$`` + ``$o60_gate_funcs$``（T-A76 C）；被测树缺任一段则 None。"""
    if not GRANTS.is_file():
        return None
    text = GRANTS.read_text(encoding="utf-8")
    parts: list[str] = []
    for tag in _MAINT_GRANT_TAGS:
        m = re.search(rf"DO \${tag}\$.*?\n\${tag}\$;", text, re.S)
        if m is None:
            return None
        parts.append(_stub_api_ingest_roles(m.group(0)))
    return "\n".join(parts)


def _assert_maint_vendor_batch_privs(c: Any) -> None:
    """T-A76 §7：aia_maint 对 batches 仅 SELECT(source_licence_id)+DELETE；对 list_rows 无权限。"""
    if c.execute("SELECT to_regclass('market.master_vendor_batches')").fetchone()[0] is None:
        return
    assert c.execute(
        "SELECT has_column_privilege('aia_maint','market.master_vendor_batches','source_licence_id','SELECT')"
    ).fetchone()[0] is True
    assert c.execute(
        "SELECT has_table_privilege('aia_maint','market.master_vendor_batches','DELETE')"
    ).fetchone()[0] is True
    # 不得有表级 SELECT（只能列级）
    assert c.execute(
        "SELECT has_table_privilege('aia_maint','market.master_vendor_batches','SELECT')"
    ).fetchone()[0] is False
    if c.execute("SELECT to_regclass('market.master_vendor_list_rows')").fetchone()[0] is not None:
        for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert c.execute(
                "SELECT has_table_privilege('aia_maint','market.master_vendor_list_rows',%s)", (priv,)
            ).fetchone()[0] is False


def _mk_maint_role(authdb: SimpleNamespace) -> str:
    """aia_maint：按 grants.sql 角色属性与 $maint$+$o33$+$o60_gate_funcs$ 授权（T-A76 C）；无 grants 时退回 DML 近似。
    连续套用两遍模拟 db-roles 重跑，并断言 batches 列级权限稳定。返回 DSN（不打印）。"""
    block = _maint_grants_block()
    if block is None:
        return _mk_role(authdb, MAINT)
    import psycopg

    pw = secrets.token_hex(16)
    with psycopg.connect(authdb.url, autocommit=True) as c:
        for stub in _MAINT_STUBS.values():
            if not c.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (stub,)).fetchone():
                c.execute(f"CREATE ROLE {stub} NOLOGIN")
        verb = "ALTER" if c.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (MAINT,)).fetchone() else "CREATE"
        c.execute(f"{verb} ROLE {MAINT} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS "
                  f"NOINHERIT PASSWORD '{pw}'")
        c.execute(block)  # type: ignore[arg-type]
        c.execute(block)  # 第二遍：db-roles 重跑后权限不变（T-A76 §7 验收 2）
        attrs = c.execute("SELECT rolsuper, rolbypassrls, rolinherit FROM pg_roles WHERE rolname = %s",
                          (MAINT,)).fetchone()
        assert attrs == (False, False, False), "aia_maint 必须是非超级用户、NOBYPASSRLS、NOINHERIT"
        _assert_maint_vendor_batch_privs(c)
    return _dsn(authdb.url, MAINT, pw)


def _mk_role(authdb: SimpleNamespace, name: str, *, dml: bool = True) -> str:
    """测试容器内临时角色（集群级，随机口令），授予本库 app/ops/market 的 DML（``dml=False`` 只授 SELECT）；返回 DSN。"""
    import psycopg

    pw = secrets.token_hex(16)
    with psycopg.connect(authdb.url, autocommit=True) as c:
        exists = c.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,)).fetchone()
        verb = "ALTER" if exists else "CREATE"
        c.execute(f"{verb} ROLE {name} LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '{pw}'")
        c.execute(f'GRANT CONNECT ON DATABASE "{authdb.name}" TO {name}')
        for s in ("app", "ops", "market"):
            c.execute(f"GRANT USAGE ON SCHEMA {s} TO {name}")
            c.execute(f"GRANT {'SELECT, INSERT, UPDATE, DELETE' if dml else 'SELECT'} ON ALL TABLES IN SCHEMA {s} TO {name}")
            c.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {s} TO {name}")
            c.execute(f"GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA {s} TO {name}")
    return _dsn(authdb.url, name, pw)


@pytest.fixture(scope="module")
def roles(authdb: SimpleNamespace) -> Iterator[SimpleNamespace]:
    yield SimpleNamespace(maint=_mk_maint_role(authdb), other=_mk_role(authdb, "tt24_notmaint"),
                          ro=_mk_role(authdb, "tt24_readonly", dml=False))


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


def use_maint_dsn(cli: SimpleNamespace, dsn: str, name: str = "maint.dsn") -> Path:
    """按 T-B49（review m1）口径交 aia_maint DSN：写入一次性目录里的密钥文件（0600）并设
    ``AIA_MAINT_DATABASE_URL_FILE``；明文环境变量 ``AIA_MAINT_DATABASE_URL`` 一律清掉（新 CLI 见到即拒绝）。"""
    f = cli.tmp / name
    f.write_text(dsn, encoding="utf-8")
    f.chmod(0o600)
    cli.mp.delenv("AIA_MAINT_DATABASE_URL", raising=False)
    cli.mp.setenv("AIA_MAINT_DATABASE_URL_FILE", str(f))
    return f


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
                                  roles: SimpleNamespace, capsys: pytest.CaptureFixture[str]) -> None:
    before = _footprint(sql, victim.uid)
    assert before["users"] == 1 and before["licences"] >= 1 and before["holds"] == 1
    # T-B49（review-a8e055b m2）：dry-run 只用 aia_maint（_FILE）或只读角色
    use_maint_dsn(cli, roles.maint)
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
    use_maint_dsn(cli, roles.other, "other.dsn")
    r = _run(cli, capsys, "--user-id", victim.uid, "--execute", confirm=victim.uid)
    # 旧 CLI：确认后 current_user 检查拒绝；T-B49 起预检查的 dry-run 角色判定先拒（有写权限，非只读角色）
    assert r.rc == 1 and ("不是 aia_maint" in r.err or "不是只读角色" in r.err), r.err[-400:]
    assert _footprint(sql, victim.uid) == before
    assert victim.s.client.get(f"{API}/me").status_code == 200, "守卫失败时不得吊销会话"


#: T-B49（6670b10，review-a8e055b m2）：dry-run 只允许 aia_maint 或只读角色。本用例随 6670b10 一起推送，故严格断言
#: （origin 0cb78ad 上预期失败，直到 6670b10 推送）。
@pytest.mark.parametrize("who", ["superuser_database_url", "writer_file", "readonly_file"])
def test_cli_dry_run_role_gate(cli: SimpleNamespace, victim: SimpleNamespace, roles: SimpleNamespace,
                               sql: Callable[..., Any], capsys: pytest.CaptureFixture[str], who: str) -> None:
    """dry-run 角色判定：超级用户（DATABASE_URL 回落）与有写权限的角色拒绝（rc=1，不打印计划）；只读角色允许。
    无论放行与否，库都不变、不回显证书明文。"""
    before = _footprint(sql, victim.uid)
    if who == "writer_file":
        use_maint_dsn(cli, roles.other, "other.dsn")
    elif who == "readonly_file":
        use_maint_dsn(cli, roles.ro, "ro.dsn")
    r = _run(cli, capsys, "--user-id", victim.uid)
    assert _footprint(sql, victim.uid) == before
    assert leak_count(victim.lic, r.text) == 0
    if who == "readonly_file":
        assert r.rc == 0, r.text[-800:]
        assert "dry-run" in r.out
        return
    assert r.rc == 1 and "拒绝" in r.err and "app.user_data_licences" not in r.out


#: T-B49（6670b10，review m1）：aia_maint DSN 只认 AIA_MAINT_DATABASE_URL_FILE，明文环境变量拒绝。严格断言，随 6670b10 推送。
def test_cli_refuses_plaintext_maint_dsn_env(cli: SimpleNamespace, victim: SimpleNamespace, roles: SimpleNamespace,
                                             sql: Callable[..., Any], capsys: pytest.CaptureFixture[str]) -> None:
    """T-B49：设置了明文 ``AIA_MAINT_DATABASE_URL`` → 拒绝（不回落、不连库），--execute 不删任何行；拒绝信息只点名
    变量，不回显 DSN。"""
    before = _footprint(sql, victim.uid)
    cli.mp.delenv("AIA_MAINT_DATABASE_URL_FILE", raising=False)
    cli.mp.setenv("AIA_MAINT_DATABASE_URL", roles.maint)
    try:
        r = _run(cli, capsys, "--user-id", victim.uid, "--execute", confirm=victim.uid)
        refused, text = r.rc != 0, r.text
    except SystemExit as exc:
        refused, text = True, str(exc) + capsys.readouterr().err
    assert refused, "明文 AIA_MAINT_DATABASE_URL 被接受并执行（T-B49 未落地）"
    assert "AIA_MAINT_DATABASE_URL" in text
    assert roles.maint.split("@")[0].rsplit(":", 1)[-1] not in text, "拒绝信息不得回显 DSN 口令"
    assert _footprint(sql, victim.uid) == before


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
    use_maint_dsn(cli, roles.maint)
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


def _licence_id(sql: Callable[..., Any], uid: str) -> str:
    rows = sql("SELECT id::text FROM app.user_data_licences WHERE user_id = :u AND deleted_at IS NULL", u=uid)
    assert rows, "victim 应有活证书"
    return rows[0][0]


def _seed_vendor_batch(sql: Callable[..., Any], licence_id: str, code: str = "600000.SH") -> tuple[str, int]:
    """插入 master_run + batch + list_row；返回 (batch_id, master_run_id)。"""
    run = sql(
        "INSERT INTO market.master_runs (trigger, status) VALUES ('manual', 'ok') RETURNING id"
    )[0][0]
    bid = sql(
        "INSERT INTO market.master_vendor_batches "
        "(master_run_id, source_licence_id, status, attempt, requested_at, deadline_at, datasets) "
        "VALUES (:r, CAST(:lic AS uuid), 'fetched', 1, now(), now() + interval '1 hour', '[]'::jsonb) "
        "RETURNING id::text",
        r=run, lic=licence_id,
    )[0][0]
    sql(
        "INSERT INTO market.master_vendor_list_rows (batch_id, dataset, security_code) "
        "VALUES (CAST(:b AS uuid), 'hslt_list', :c)",
        b=bid, c=code,
    )
    return bid, int(run)


def test_cli_execute_deletes_vendor_batches_keeps_bystander(
    cli: SimpleNamespace, victim: SimpleNamespace, roles: SimpleNamespace,
    sql: Callable[..., Any], capsys: pytest.CaptureFixture[str],
) -> None:
    """T-A76 §7：目标证书的 batches+list_rows 删除；旁观证书的保留；master_runs 保留。"""
    vic_lic = _licence_id(sql, victim.uid)
    by_lic = _licence_id(sql, victim.by.user.id)
    vb, vr = _seed_vendor_batch(sql, vic_lic, "600000.SH")
    bb, br = _seed_vendor_batch(sql, by_lic, "000001.SZ")
    assert sql("SELECT count(*) FROM market.master_vendor_batches WHERE id = CAST(:b AS uuid)", b=vb)[0][0] == 1
    assert sql("SELECT count(*) FROM market.master_vendor_list_rows WHERE batch_id = CAST(:b AS uuid)", b=vb)[0][0] == 1
    use_maint_dsn(cli, roles.maint)
    r = _run(cli, capsys, "--user-id", victim.uid, "--execute", confirm=victim.uid)
    assert r.rc == 0, r.text[-1500:]
    assert sql("SELECT count(*) FROM market.master_vendor_batches WHERE id = CAST(:b AS uuid)", b=vb)[0][0] == 0
    assert sql("SELECT count(*) FROM market.master_vendor_list_rows WHERE batch_id = CAST(:b AS uuid)", b=vb)[0][0] == 0
    assert sql("SELECT count(*) FROM market.master_vendor_batches WHERE id = CAST(:b AS uuid)", b=bb)[0][0] == 1
    assert sql("SELECT count(*) FROM market.master_vendor_list_rows WHERE batch_id = CAST(:b AS uuid)", b=bb)[0][0] == 1
    assert sql("SELECT count(*) FROM market.master_runs WHERE id = :r", r=vr)[0][0] == 1
    assert sql("SELECT count(*) FROM market.master_runs WHERE id = :r", r=br)[0][0] == 1


def test_cli_drift_unguarded_market_table_permission_denied(
    cli: SimpleNamespace, victim: SimpleNamespace, roles: SimpleNamespace,
    sql: Callable[..., Any], capsys: pytest.CaptureFixture[str],
) -> None:
    """T-A76 §7 漂移反例 1：新建带 source_licence_id 的 market 表且未授 aia_maint → dry-run/execute 均 permission denied，数据不变。"""
    tbl = "market.tt40_drift_batches"
    sql(f"CREATE TABLE {tbl} (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), "
        f"source_licence_id uuid NOT NULL REFERENCES app.user_data_licences(id))")
    try:
        lic = _licence_id(sql, victim.uid)
        sql(f"INSERT INTO {tbl} (source_licence_id) VALUES (CAST(:l AS uuid))", l=lic)
        before_users = sql("SELECT count(*) FROM app.users WHERE id = :u", u=victim.uid)[0][0]
        before_rows = sql(f"SELECT count(*) FROM {tbl}")[0][0]
        use_maint_dsn(cli, roles.maint)
        denied = False
        try:
            r = _run(cli, capsys, "--user-id", victim.uid)
            text = r.text
            if r.rc != 0 and ("permission denied" in text.lower() or "InsufficientPrivilege" in text):
                denied = True
            elif r.rc == 0:
                try:
                    r2 = _run(cli, capsys, "--user-id", victim.uid, "--execute", confirm=victim.uid)
                    text = r2.text
                    denied = r2.rc != 0 and (
                        "permission denied" in text.lower() or "InsufficientPrivilege" in text
                    )
                except Exception as exc:  # dry-run 放过时 execute 可能直接抛
                    denied = (
                        "permission denied" in str(exc).lower()
                        or "InsufficientPrivilege" in type(exc).__name__
                    )
        except Exception as exc:
            denied = (
                "permission denied" in str(exc).lower()
                or "InsufficientPrivilege" in type(exc).__name__
            )
        assert denied, "未授权 market 新表应触发 permission denied"
        assert sql("SELECT count(*) FROM app.users WHERE id = :u", u=victim.uid)[0][0] == before_users
        assert sql(f"SELECT count(*) FROM {tbl}")[0][0] == before_rows
    finally:
        sql(f"DROP TABLE IF EXISTS {tbl}")


def test_cli_drift_noncascade_fk_rolls_back(
    cli: SimpleNamespace, victim: SimpleNamespace, roles: SimpleNamespace,
    sql: Callable[..., Any], capsys: pytest.CaptureFixture[str],
) -> None:
    """T-A76 §7 漂移反例 2：引用 batches 的非级联外键表 → --execute IntegrityError 整笔回滚。"""
    tbl = "market.tt40_nocascade"
    vic_lic = _licence_id(sql, victim.uid)
    bid, _ = _seed_vendor_batch(sql, vic_lic, "600519.SH")
    sql(
        f"CREATE TABLE {tbl} (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), "
        "batch_id uuid NOT NULL REFERENCES market.master_vendor_batches(id))"  # 默认 NO ACTION，非 CASCADE
    )
    try:
        sql(f"INSERT INTO {tbl} (batch_id) VALUES (CAST(:b AS uuid))", b=bid)
        before_users = sql("SELECT count(*) FROM app.users WHERE id = :u", u=victim.uid)[0][0]
        before_batches = sql(
            "SELECT count(*) FROM market.master_vendor_batches WHERE source_licence_id = CAST(:l AS uuid)",
            l=vic_lic,
        )[0][0]
        use_maint_dsn(cli, roles.maint)
        text = ""
        rc = 0
        try:
            r = _run(cli, capsys, "--user-id", victim.uid, "--execute", confirm=victim.uid)
            rc, text = r.rc, r.text
        except Exception as exc:
            rc, text = 1, f"{type(exc).__name__}: {exc}"
        assert rc != 0, text[-800:]
        # T-A77：不得单凭「回滚」放行（任意库错误都会带这词）；须是外键/完整性违例。
        low = text.lower()
        assert (
            "foreignkeyviolation" in low.replace(" ", "")
            or "foreign key" in low
            or "integrityerror" in low.replace(" ", "")
            or ("integrity" in low and ("foreign" in low or "violat" in low or "constraint" in low))
        ), text[-800:]
        assert sql("SELECT count(*) FROM app.users WHERE id = :u", u=victim.uid)[0][0] == before_users
        assert sql(
            "SELECT count(*) FROM market.master_vendor_batches WHERE source_licence_id = CAST(:l AS uuid)",
            l=vic_lic,
        )[0][0] == before_batches
    finally:
        sql(f"DROP TABLE IF EXISTS {tbl}")
