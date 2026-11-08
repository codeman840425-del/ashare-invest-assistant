import pytest
from pathlib import Path
from typing import Any, Iterator
import uuid, secrets
from argon2 import PasswordHasher
from pydantic import SecretStr
from sqlalchemy import create_engine, text, insert, select
from starlette.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.schemas.enums import RegistrationMode
from app.db.tables.users import users
from app.replay.baseline import require_isolated
from selfchecks import test_tb70_replay as tb70
from tt21_head import expected_main_head
DB, REDIS, INSTRUMENTS = tb70.DB, tb70.REDIS, tb70.INSTRUMENTS

@pytest.fixture
def tt21_integration(
    tmp_path: Path,
) -> Iterator[tuple[Any, TestClient, TestClient, uuid.UUID, uuid.UUID]]:
    if not Path("/tmp/tb70-pg-socket/.s.PGSQL.5432").exists():
        pytest.fail("T-T21专用隔离PG未就绪，不跳过或回退共享库")
    engine = create_engine(DB)
    with engine.begin() as conn:
        require_isolated(conn, app_env="test")
        assert (
            conn.execute(text("select version_num from public.alembic_version")).scalar_one()
            == expected_main_head(Path(tb70.__file__).resolve().parents[1])
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


import copy, yaml
from sqlalchemy import update
from app.auth.deps import get_password_policy
from app.auth.sessions import CSRF_HEADER
from app.strategy.cards.persistence import validate_batch, import_batch
from tt21_synthetic import document as synthetic_document, registry as synthetic_registry
@pytest.fixture
def tt21_gate_context(integration: Any) -> Any:
    engine, client, stranger, owner, other = integration
    settings = client.app.state.settings
    password = SecretStr("Fictional-only#7A-" + secrets.token_hex(12))
    policy = get_password_policy(settings)
    with engine.begin() as conn:
        conn.execute(
            update(users)
            .where(users.c.id == owner)
            .values(
                role="admin",
                password_hash=policy.hash(password.get_secret_value()),
                failed_login_count=0,
                locked_until=None,
            )
        )
        username = conn.execute(select(users.c.username).where(users.c.id == owner)).scalar_one()
    response = client.post(
        "/api/v1/auth/login", json={"username": username, "password": password.get_secret_value()}
    )
    assert response.status_code == 200
    client.headers[CSRF_HEADER] = response.json()["csrf_token"]
    registry = synthetic_registry(gate=True)
    source = synthetic_document("tt21_gate_seed", gate=True)
    original = validate_batch([source], registry)[0]
    # 只在本任务独立库登记虚构feature；不提升任何真实f.*来源状态。
    with engine.begin() as conn:
        for feature, row in registry.items():
            conn.execute(text("INSERT INTO app.feature_catalog (feature_key,unit,adjust,frequency,pit_rule,status,source) "
                              "VALUES (:k,:u,:a,'daily','{}'::jsonb,'verified_doc','{}'::jsonb) "
                              "ON CONFLICT (feature_key) DO UPDATE SET status='verified_doc'"),
                         {"k": feature, "u": row["unit"], "a": row["adjust"]})
    blocks = copy.deepcopy(original.blocks)
    key = "fictional_tb83b_" + uuid.uuid4().hex[:16]
    blocks["strategy-card"].update(key=key, version_no=1, name="纯虚构审核接线卡（不是正式策略）")
    blocks["strategy-spec"].update(key=key, version_no=1)
    document = "\n".join(
        "```yaml " + name + "\n" + yaml.safe_dump(body, allow_unicode=True) + "```"
        for name, body in blocks.items()
    )
    with engine.begin() as conn:
        imported = import_batch(
            conn,
            [document],
            registry,
            source_matrix=None,
        )[0]
    assert key not in {"hold_risk_monitor", "sw_ma_trend_pullback"}
    response = client.post(
        f"/api/v1/strategy-cards/{imported['card_id']}/promotion-requests",
        json={"version_id": imported["version_id"]},
    )
    assert response.status_code == 202
    review = response.json()["review_id"]
    detail = client.get(f"/api/v1/promotion-requests/{review}").json()
    assert all(g["result"] == "pass" for g in detail["gate_results"][:5])
    assert detail["gate_results"][5]["result"] == "warn"
    assert detail["gate_results"][6]["result"] == "skipped"
    return {
        "engine": engine,
        "client": client,
        "stranger": stranger,
        "owner": owner,
        "other": other,
        "password": password,
        "review": review,
        **imported,
    }


@pytest.fixture(scope="module")
def tt21_corpus():
    from app.strategy.cards.preflight import preflight
    reg = synthetic_registry()
    staged, errors = preflight([synthetic_document("tt21_alpha"), synthetic_document("tt21_beta")], reg)
    assert not errors, errors
    return staged, errors, reg, tb70.Settings(_env_file=None).business.market_rules

@pytest.hookimpl(tryfirst=True)
def pytest_fixture_setup(fixturedef, request):
    # 只替换测试夹具，不patch业务函数，不删除/放宽原用例断言。
    path = str(Path(fixturedef.func.__code__.co_filename))
    replacement = None
    if fixturedef.argname == "integration" and path.endswith("test_tb70_replay.py"):
        replacement = "tt21_integration"
    elif fixturedef.argname == "corpus" and path.endswith("test_tb71_formal.py"):
        replacement = "tt21_corpus"
    elif fixturedef.argname == "context" and path.endswith("test_tb83b_reauth.py"):
        replacement = "tt21_gate_context"
    if replacement:
        value = request.getfixturevalue(replacement)
        fixturedef.cached_result = (value, fixturedef.cache_key(request), None)
        return value
