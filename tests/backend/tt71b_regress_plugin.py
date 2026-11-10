# ruff: noqa: S101
"""T-T71b 强制真跑插件（-p tt71b_regress_plugin）。默认不启用。

1. 把 tb70 integration 夹具里「alembic 恰为 0020」换成迁移图动态唯一 head
   （仍要求单头、根为 0001）。其他断言一字不改。
2. 会话结束时：四个回归文件中只要有 skip，整次运行非零退出。
3. 缺 socket 时 fail，不 skip（pytest_fixture_setup 替换，写法同 tt21_plugin）。
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

REGRESS_FILES = (
    "test_tb70_replay.py",
    "test_tb76_assembly.py",
    "test_tb76_daily.py",
    "test_p2n04_daily_dimensions.py",
)

_skips: list[str] = []


def _unique_head(migrations: Path) -> str:
    cfg = Config()
    cfg.set_main_option("script_location", str(migrations))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1, f"迁移图必须单头，实际 {heads}"
    bases = script.get_bases()
    assert bases == ["0001"] or (len(bases) == 1 and bases[0] == "0001"), f"根必须为 0001，实际 {bases}"
    head = script.get_current_head()
    assert head is not None
    return head


@pytest.fixture
def tt71b_integration(tmp_path: Path) -> Iterator[Any]:
    from pathlib import Path as P

    import selfchecks.test_tb70_replay as tb70
    from app.replay.baseline import require_isolated
    from sqlalchemy import create_engine

    if not P("/tmp/tb70-pg-socket/.s.PGSQL.5432").exists():
        pytest.fail("dedicated networkless T-B70 PostgreSQL not provisioned")
    migrations = P(tb70.__file__).resolve().parents[1] / "migrations"
    engine = create_engine(tb70.DB)
    with engine.begin() as conn:
        require_isolated(conn, app_env="test")
        assert (
            conn.execute(text("select version_num from public.alembic_version")).scalar_one()
            == _unique_head(migrations)
        )
    from argon2 import PasswordHasher

    from fastapi.testclient import TestClient
    from pydantic import SecretStr
    from sqlalchemy import insert

    from app.config import Settings
    from app.db.tables.users import users
    from app.main import create_app
    from app.schemas.enums import RegistrationMode

    settings = Settings(
        _env_file=None,
        database_url=SecretStr(tb70.DB),
        redis_url=tb70.REDIS,
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
        for code, board, _ in tb70.INSTRUMENTS:
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


@pytest.hookimpl(tryfirst=True)
def pytest_fixture_setup(fixturedef: Any, request: pytest.FixtureRequest) -> Any:
    # 只替换 tb70 integration 夹具（0020 → 动态唯一 head；缺 socket → fail），不改业务函数、不放宽原断言。
    path = str(Path(fixturedef.func.__code__.co_filename))
    if fixturedef.argname == "integration" and path.endswith("test_tb70_replay.py"):
        value = request.getfixturevalue("tt71b_integration")
        fixturedef.cached_result = (value, fixturedef.cache_key(request), None)
        return value
    return None


def _is_regress(report: pytest.TestReport) -> bool:
    nodeid = report.nodeid
    return any(name in nodeid for name in REGRESS_FILES)


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.when == "setup" or report.when == "call" or report.when == "teardown":
        if report.skipped and _is_regress(report):
            long = f"{report.nodeid} [{report.when}]"
            if long not in _skips:
                _skips.append(long)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if not _skips:
        return
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_line(
            "tt71b_regress_plugin: 四个回归文件出现 skip，整次失败：\n  " + "\n  ".join(_skips),
            red=True,
        )
    session.exitstatus = pytest.ExitCode.TESTS_FAILED if exitstatus == 0 else exitstatus
