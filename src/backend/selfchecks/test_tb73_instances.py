"""T-B73 partial integration: explicitly synthetic component, no H-01/W-01 content."""

# ruff: noqa: S101, ANN401
from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import insert, select, text

from app.common.errors import AppError, ErrorCode
from app.db.tables.accounts import holdings
from app.db.tables.strategy import strategies
from app.db.tables.strategy import strategy_instance_events as events
from app.db.tables.strategy import strategy_instances as instances
from app.db.tables.strategy import strategy_versions as versions
from app.schemas.enums import RiskControl
from app.strategy.instances.service import attach_system
from selfchecks.test_tb70_replay import integration as integration
from selfchecks.test_tb70_replay import no_network as no_network


@pytest.fixture
def component(integration: Any) -> tuple[Any, Any, Any, uuid.UUID, uuid.UUID, uuid.UUID]:
    engine, client, stranger, owner, _ = integration
    account = client.post("/api/v1/accounts", json={"broker_name": "模拟券商", "alias": "实例测试"})
    assert account.status_code == 201
    account_id = uuid.UUID(account.json()["id"])
    strategy_id, version_id = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            insert(strategies).values(
                id=strategy_id,
                key="fixture_" + strategy_id.hex,
                name="Synthetic component NOT H01",
                horizons=["swing"],
            )
        )
        conn.execute(
            insert(versions).values(
                id=version_id,
                strategy_id=strategy_id,
                version_no=1,
                lifecycle="published",
                config_hash="synthetic-only",
                config={
                    "origin": "system",
                    "horizons": ["swing"],
                    "rules": [{"role": role} for role in ("exit", "counter", "invalidation")],
                    "action_map": {"exit": "sell", "else": "hold"},
                },
            )
        )
        conn.execute(
            insert(holdings).values(
                account_id=account_id, security_code="688018.SH", quantity=200, avg_cost=10
            )
        )
    return engine, client, stranger, owner, account_id, version_id


def risks() -> dict[str, Any]:
    return {control.value: {"enabled": True, "params": {}} for control in RiskControl}


def attach(component: Any) -> uuid.UUID:
    engine, _, _, owner, account, version = component
    with engine.begin() as conn:
        return attach_system(
            conn, owner, account, "688018.SH", version, horizon="swing", risk_settings=risks()
        )


def test_attachment_concurrency_and_ownership(component: Any) -> None:
    engine, client, stranger, _, _, _ = component
    with ThreadPoolExecutor(max_workers=2) as pool:
        identifiers = list(pool.map(lambda _: attach(component), range(2)))
    assert identifiers[0] == identifiers[1]
    identifier = identifiers[0]
    detail = client.get(f"/api/v1/strategy-instances/{identifier}")
    assert detail.status_code == 200
    assert detail.json()["origin"] == "system"
    assert detail.json()["status"] == "active"
    assert detail.json()["risk_level"] == "normal"
    for suffix in ("", "/events"):
        assert stranger.get(f"/api/v1/strategy-instances/{identifier}{suffix}").status_code == 404
    for op in ("pause", "resume", "confirm", "archive"):
        assert stranger.post(f"/api/v1/strategy-instances/{identifier}/{op}").status_code == 404
    assert client.post(f"/api/v1/strategy-instances/{identifier}/archive").status_code == 409
    assert client.post(f"/api/v1/strategy-instances/{identifier}/pause").status_code == 200
    before = client.get(f"/api/v1/strategy-instances/{identifier}").json()
    assert attach(component) == identifier
    assert client.post(f"/api/v1/strategy-instances/{identifier}/pause").json() == before
    assert client.post(f"/api/v1/strategy-instances/{identifier}/resume").status_code == 200
    with engine.connect() as conn:
        assert (
            len(conn.execute(select(events).where(events.c.instance_id == identifier)).all()) == 3
        )


def test_state_events_and_cursor_scope(component: Any) -> None:
    engine, client, _, owner, account, version = component
    identifier = attach(component)
    another = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            insert(instances).values(
                id=another,
                user_id=owner,
                account_id=account,
                strategy_version_id=version,
                scope="security",
                security_code="688018.SH",
                horizon="swing",
                origin="user",
                status="proposed",
            )
        )
    assert client.post(f"/api/v1/strategy-instances/{another}/confirm").status_code == 200
    assert client.post(f"/api/v1/strategy-instances/{another}/archive").status_code == 200
    assert client.post(f"/api/v1/strategy-instances/{another}/resume").status_code == 409
    response = client.get(
        "/api/v1/strategy-instances", params={"limit": 1, "status": ["active", "archived"]}
    )
    assert response.status_code == 200
    cursor = response.json()["next_cursor"]
    assert cursor is not None
    assert (
        client.get(
            "/api/v1/strategy-instances",
            params={"limit": 1, "cursor": cursor, "status": ["active", "archived"]},
        ).status_code
        == 200
    )
    changed = client.get("/api/v1/strategy-instances", params={"limit": 1, "cursor": cursor})
    assert changed.status_code == 400
    assert changed.json()["error"]["code"] == "INVALID_CURSOR"
    assert client.post(f"/api/v1/strategy-instances/{identifier}/pause").status_code == 200
    history = client.get(
        f"/api/v1/strategy-instances/{identifier}/events", params={"limit": 1}
    ).json()
    assert len(history["items"]) == 1
    assert history["items"][0]["actor"] == "user"
    assert history["items"][0]["from_status"] == "active"
    assert history["next_cursor"] is not None
    assert (
        client.get(
            f"/api/v1/strategy-instances/{identifier}/events",
            params={
                "cursor": history["next_cursor"],
                "limit": 1,
            },
        ).status_code
        == 200
    )


@pytest.mark.parametrize("lifecycle", ["draft", "retired", "simulating"])
def test_resume_rejects_nonrunnable_effective_version(component: Any, lifecycle: str) -> None:
    engine, client, _, _, _, version = component
    identifier = attach(component)
    assert client.post(f"/api/v1/strategy-instances/{identifier}/pause").status_code == 200
    with engine.begin() as conn:
        conn.execute(
            text("update app.strategy_versions set lifecycle=:state where id=:id"),
            {"state": lifecycle, "id": version},
        )
    response = client.post(f"/api/v1/strategy-instances/{identifier}/resume")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "STRATEGY_VERSION_NOT_RUNNABLE"
    assert client.get(f"/api/v1/strategy-instances/{identifier}").json()["status"] == "paused"


@pytest.mark.parametrize("security_type", ["etf", None])
def test_system_attachment_rejects_ineligible_type(
    component: Any, security_type: str | None
) -> None:
    engine, _, _, owner, account, version = component
    with engine.connect() as conn:
        transaction = conn.begin()
        if security_type:
            conn.execute(
                text("update market.securities set type=:type where code='688018.SH'"),
                {"type": security_type},
            )
        else:
            conn.execute(text("delete from market.securities where code='688018.SH'"))
        with pytest.raises(AppError) as error:
            attach_system(
                conn, owner, account, "688018.SH", version, horizon="swing", risk_settings=risks()
            )
        assert error.value.code == ErrorCode.INSTANCE_SCOPE_INVALID
        transaction.rollback()


def user_template(component: Any, *, lifecycle: str = "published") -> uuid.UUID:
    engine, _, _, _, _, _ = component
    strategy_id, version_id = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            insert(strategies).values(
                id=strategy_id,
                key="fixture_user_" + strategy_id.hex,
                name="Synthetic NOT W01",
                horizons=["swing", "intraday_t"],
            )
        )
        conn.execute(
            insert(versions).values(
                id=version_id,
                strategy_id=strategy_id,
                version_no=1,
                lifecycle=lifecycle,
                config_hash="synthetic-metadata-only",
                config={
                    "horizons": ["swing", "intraday_t"],
                    "params_schema": {
                        "synthetic_count": {
                            "type": "int",
                            "default": 2,
                            "min": 1,
                            "max": 3,
                            "step": 1,
                        }
                    },
                },
            )
        )
    return version_id


def create_body(component: Any, version_id: uuid.UUID) -> dict[str, Any]:
    return {
        "strategy_version_id": str(version_id),
        "account_id": str(component[4]),
        "scope": "security",
        "security_code": "688018.SH",
        "horizon": "swing",
    }


def test_user_creation_derivation_patch_and_risk(component: Any) -> None:
    engine, client, stranger, owner, _, _ = component
    version = user_template(component)
    from app.db.tables.strategy import risk_control_settings

    with engine.begin() as conn:
        conn.execute(
            insert(risk_control_settings).values(
                id=uuid.uuid4(),
                scope="user",
                user_id=owner,
                control="stop_take",
                enabled=False,
                params={},
            )
        )
    body = create_body(component, version) | {
        "param_overrides": {"synthetic_count": 3},
        "budget_amount": "1500.00",
    }
    response = client.post("/api/v1/strategy-instances", json=body)
    assert response.status_code == 201
    identifier = response.json()["id"]
    assert response.json()["derived_strategy_version_id"] is not None
    assert any("RC1" in message for message in response.json()["warnings"])
    assert any("partial" in message for message in response.json()["warnings"])
    detail = client.get(f"/api/v1/strategy-instances/{identifier}").json()
    assert detail["strategy_version_id"] == response.json()["derived_strategy_version_id"]
    assert Decimal(detail["budget_amount"]) == Decimal("1500.00")
    with engine.connect() as conn:
        row = conn.execute(select(instances).where(instances.c.id == uuid.UUID(identifier))).one()
        assert row.risk_settings_snapshot["controls"]["stop_take"]["enabled"] is False
    assert (
        stranger.patch(
            f"/api/v1/strategy-instances/{identifier}", json={"budget_amount": "1"}
        ).status_code
        == 404
    )
    changed = client.patch(
        f"/api/v1/strategy-instances/{identifier}",
        json={
            "param_overrides": {"synthetic_count": 1},
            "budget_amount": "2000",
        },
    )
    assert changed.status_code == 200
    assert changed.json()["derived_strategy_version_id"] != detail["derived_strategy_version_id"]
    assert client.post(f"/api/v1/strategy-instances/{identifier}/archive").status_code == 200
    assert client.patch(f"/api/v1/strategy-instances/{identifier}", json={}).status_code == 409


@pytest.mark.parametrize(
    "overrides",
    [{"synthetic_count": 4}, {"synthetic_count": True}, {"synthetic_count": "2"}, {"unknown": 1}],
)
def test_parameter_rejection_does_not_create_partial_versions(
    component: Any, overrides: Any
) -> None:
    engine, client, _, _, _, _ = component
    version = user_template(component)
    with engine.connect() as conn:
        before = len(conn.execute(select(versions.c.id)).all())
    response = client.post(
        "/api/v1/strategy-instances",
        json=create_body(component, version) | {"param_overrides": overrides},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "STRATEGY_PARAM_OUT_OF_RANGE"
    with engine.connect() as conn:
        assert len(conn.execute(select(versions.c.id)).all()) == before


def test_simulation_permission_and_horizon_scope(component: Any) -> None:
    engine, client, stranger, owner, _, _ = component
    version = user_template(component, lifecycle="simulating")
    body = create_body(component, version)
    assert client.post("/api/v1/strategy-instances", json=body).status_code == 409
    assert stranger.post("/api/v1/strategy-instances", json=body).status_code == 404
    with engine.begin() as conn:
        conn.execute(text("update app.users set role='admin' where id=:id"), {"id": owner})
    assert client.post("/api/v1/strategy-instances", json=body).status_code == 201
    version = user_template(component)
    body = create_body(component, version)
    assert (
        client.post("/api/v1/strategy-instances", json=body | {"horizon": "long"}).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/strategy-instances",
            json=body
            | {
                "horizon": "intraday_t",
                "security_code": "688073.SH",
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/strategy-instances",
            json=body
            | {
                "scope": "account",
                "security_code": None,
            },
        ).status_code
        == 201
    )
    assert (
        client.post("/api/v1/strategy-instances", json=body | {"origin": "system"}).status_code
        == 400
    )


def test_paused_archived_never_eligible_for_new_signals() -> None:
    from app.schemas.enums import InstanceOrigin, InstancePausedBy, InstanceStatus
    from app.strategy.instances.state import InstanceState, generates_signals

    assert not generates_signals(
        InstanceState(
            status=InstanceStatus.PAUSED,
            origin=InstanceOrigin.USER,
            paused_by=InstancePausedBy.USER,
        )
    )
    import datetime as dt

    assert not generates_signals(
        InstanceState(
            status=InstanceStatus.ARCHIVED,
            origin=InstanceOrigin.USER,
            archived_at=dt.datetime.now(dt.UTC),
        )
    )


def test_watch_group_fails_closed_pending_selector_contract(component: Any) -> None:
    version = user_template(component)
    response = component[1].post(
        "/api/v1/strategy-instances",
        json=create_body(component, version)
        | {
            "scope": "watch_group",
            "security_code": None,
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"]["issue"] == "scope_deferred"
