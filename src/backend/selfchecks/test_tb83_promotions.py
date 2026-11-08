# ruff: noqa: S101, ANN401, F811
"""Synthetic identities and isolated DB only. No real G7 decision or promotion."""

from __future__ import annotations

import copy
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import insert, select, update

from app.common.errors import AppError, ErrorCode
from app.db.tables.strategy import (
    strategies,
)
from app.db.tables.strategy import (
    strategy_card_versions as cv,
)
from app.db.tables.strategy import (
    strategy_cards as cards,
)
from app.db.tables.strategy import (
    strategy_promotion_reviews as reviews,
)
from app.db.tables.strategy import (
    strategy_versions as versions,
)
from app.db.tables.users import audit_logs, users
from app.strategy import reviews as service
from selfchecks.test_tb70_replay import integration, no_network  # noqa: F401


@pytest.fixture
def context(integration: Any) -> Any:
    engine, client, stranger, owner, _other = integration
    card, card_version, strategy, version = [uuid.uuid4() for _ in range(4)]
    with engine.begin() as conn:
        conn.execute(update(users).where(users.c.id == owner).values(role="admin"))
        conn.execute(
            insert(cards).values(
                id=card,
                key="synthetic_tb83_" + card.hex,
                title="虚构审核卡（不是正式策略）",
                source_kind="user",
                owner_user_id=owner,
            )
        )
        conn.execute(
            insert(cv).values(
                id=card_version,
                card_id=card,
                version_no=1,
                fields={"title": "完全合成", "version_no": 1},
                field_epistemic={},
            )
        )
        conn.execute(
            insert(strategies).values(
                id=strategy,
                key="synthetic_tb83_" + strategy.hex,
                name="虚构审核策略",
                owner_user_id=owner,
                horizons=["swing"],
            )
        )
        conn.execute(
            insert(versions).values(
                id=version,
                strategy_id=strategy,
                card_version_id=card_version,
                version_no=1,
                config={"rules": [], "validation": {}},
                config_hash="synthetic_hash_not_a_binding",
                lifecycle="draft",
            )
        )
    return engine, client, stranger, owner, card, card_version, strategy, version


def submit(ctx: Any) -> str:
    _, client, _, _, card, _, _, version = ctx
    response = client.post(
        f"/api/v1/strategy-cards/{card}/promotion-requests", json={"version_id": str(version)}
    )
    assert response.status_code == 202, response.text
    return response.json()["review_id"]


def test_request_idempotence_details_filters_pagination_and_ownership(context: Any) -> None:
    engine, client, stranger, _, card, _, _, version = context
    first = submit(context)
    assert submit(context) == first
    assert stranger.get(f"/api/v1/promotion-requests/{first}").status_code == 404
    assert (
        stranger.post(
            f"/api/v1/strategy-cards/{card}/promotion-requests", json={"version_id": str(version)}
        ).status_code
        == 404
    )
    detail = client.get(f"/api/v1/promotion-requests/{first}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["decision"] == "pending"
    assert detail.json()["stale"] is False
    assert len(detail.json()["content_sha256"]) == 64
    assert detail.json()["reviewer_id"] is None
    page = client.get("/api/v1/admin/promotions", params={"card_id": str(card), "limit": 1})
    assert page.status_code == 200, page.text
    assert page.json()["items"][0]["review_id"] == first
    assert [g["gate"] for g in page.json()["items"][0]["gates"]] == [f"G{i}" for i in range(1, 7)]
    for params in [
        {"stale": "yes"},
        {"decision": "approved,bad"},
        {"card_id": "bad"},
        {"version_id": "bad"},
    ]:
        assert client.get("/api/v1/admin/promotions", params=params).status_code == 400
    with engine.begin() as conn:
        conn.execute(
            update(versions)
            .where(versions.c.id == version)
            .values(config={"rules": [], "validation": {}, "synthetic_content_change": True})
        )
    assert client.get(f"/api/v1/promotion-requests/{first}").json()["stale"] is True
    assert (
        client.get("/api/v1/admin/promotions", params={"card_id": str(card)}).json()["items"] == []
    )
    assert (
        client.get(
            "/api/v1/admin/promotions", params={"card_id": str(card), "stale": "true"}
        ).json()["items"][0]["review_id"]
        == first
    )
    second = submit(context)
    assert second != first
    page = client.get(
        "/api/v1/admin/promotions",
        params={"card_id": str(card), "decision": "pending,approved", "limit": 1},
    )
    assert page.json()["items"][0]["review_id"] == second


def test_new_version_stale_409_and_lifecycle_state(context: Any) -> None:
    engine, client, _, owner, card, _oldcv, strategy, version = context
    review = submit(context)
    newcv, newversion = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            insert(cv).values(id=newcv, card_id=card, version_no=2, fields={"title": "完全合成v2"})
        )
        conn.execute(
            insert(versions).values(
                id=newversion,
                strategy_id=strategy,
                card_version_id=newcv,
                version_no=2,
                config={"rules": []},
                config_hash="synthetic_v2",
            )
        )
    response = client.post(
        f"/api/v1/strategy-cards/{card}/promotion-requests", json={"version_id": str(version)}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PROMOTION_STALE"
    assert response.json()["error"]["details"]["current_version_id"] == str(newversion)
    with engine.connect() as conn:
        row, _, cvrow, vrow = service.review_context(conn, owner, uuid.UUID(review))
        with pytest.raises(AppError) as raised:
            service.require_approved(
                row,
                service.binding_of(row),
                newversion,
                service.content_sha256(cvrow, vrow),
                version,
            )
        assert raised.value.code == ErrorCode.PROMOTION_STALE
    with engine.begin() as conn:
        conn.execute(
            update(versions).where(versions.c.id == newversion).values(lifecycle="retired")
        )
    response = client.post(
        f"/api/v1/strategy-cards/{card}/promotion-requests", json={"version_id": str(newversion)}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


@pytest.mark.parametrize("credential", ["cookie_csrf", "bearer", "forged_human_headers"])
def test_g7_rejects_unattested_credentials_and_never_mutates(context: Any, credential: str) -> None:
    engine, client, _, owner, _, _, strategy, version = context
    review = submit(context)
    headers = (
        {"Authorization": "Bearer synthetic_not_real"}
        if credential == "bearer"
        else (
            {"X-Human": "true", "X-Browser-Session": "true", "Sec-Fetch-Mode": "navigate"}
            if credential == "forged_human_headers"
            else {}
        )
    )
    for path, body in [
        (
            f"/api/v1/admin/promotions/{review}/decision",
            {
                "decision": "approved",
                "comment": "虚构审核",
                "ack_warn_gates": [],
                "reviewer_id": str(uuid.uuid4()),
            },
        ),
        (
            f"/api/v1/admin/strategies/{strategy}/versions/{version}/lifecycle",
            {"to": "simulating", "reason": "虚构", "review_id": review},
        ),
    ]:
        response = client.post(path, json=body, headers=headers)
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "HUMAN_SESSION_REQUIRED"
    with engine.connect() as conn:
        row = conn.execute(select(reviews).where(reviews.c.id == uuid.UUID(review))).one()
        assert row.decision == "pending"
        assert row.reviewer_id is None
        assert (
            conn.execute(select(versions.c.lifecycle).where(versions.c.id == version)).scalar_one()
            == "draft"
        )
        if credential != "bearer":
            assert conn.execute(
                select(audit_logs.c.id).where(
                    audit_logs.c.actor_id == owner,
                    audit_logs.c.action == "promotion.human_session_required",
                )
            ).first()


@pytest.mark.parametrize("decision", ["pending", "rejected", "changes_requested"])
def test_unapproved_review_never_sufficient(context: Any, decision: str) -> None:
    engine, _, _, owner, _, _, _, version = context
    identifier = submit(context)
    with engine.begin() as conn:
        conn.execute(
            update(reviews).where(reviews.c.id == uuid.UUID(identifier)).values(decision=decision)
        )
        row, _, cvrow, vrow = service.review_context(conn, owner, uuid.UUID(identifier))
        with pytest.raises(AppError) as raised:
            service.require_approved(
                row, service.binding_of(row), version, service.content_sha256(cvrow, vrow), version
            )
        assert raised.value.code == ErrorCode.PROMOTION_GATES_NOT_MET


def test_pure_binding_and_gate_validation_no_g7() -> None:
    version = uuid.uuid4()
    binding = {"version_id": str(version), "content_sha256": "a" * 64}
    row = SimpleNamespace(
        decision="pending",
        gate_results=[
            {"gate": f"G{i}", "result": "warn" if i == 6 else "pass"} for i in range(1, 7)
        ],
    )
    with pytest.raises(AppError) as error:
        service.validate_decision(row, binding, version, "a" * 64, "approved", [])
    assert error.value.code == ErrorCode.PROMOTION_WARN_UNACKNOWLEDGED
    service.validate_decision(row, binding, version, "a" * 64, "approved", ["G6"])
    broken = copy.deepcopy(row)
    broken.gate_results[0]["result"] = "fail"
    with pytest.raises(AppError) as error:
        service.validate_decision(broken, binding, version, "a" * 64, "approved", ["G6"])
    assert error.value.code == ErrorCode.PROMOTION_GATES_NOT_MET
    service.validate_decision(broken, binding, version, "a" * 64, "rejected", [])
    row.decision = "rejected"
    with pytest.raises(AppError) as error:
        service.validate_decision(row, binding, version, "a" * 64, "approved", ["G6"])
    assert error.value.code == ErrorCode.INVALID_STATE_TRANSITION
    with pytest.raises(AppError) as error:
        service.require_current(binding, version, "b" * 64)
    assert error.value.code == ErrorCode.PROMOTION_STALE
    # Legacy approvals with no original digest may not be silently rebound.
    with pytest.raises(AppError) as error:
        service.binding_of(SimpleNamespace(compliance_lint={}, decision="approved"))
    assert error.value.code == ErrorCode.MAINTENANCE


def test_page_tie_breaker_missing_review_and_legacy_rejection(context: Any) -> None:
    engine, client, _, _owner, card, _, _, version = context
    identifier = uuid.UUID(submit(context))
    with engine.begin() as conn:
        original = conn.execute(select(reviews).where(reviews.c.id == identifier)).one()
        second = uuid.uuid4()
        conn.execute(
            insert(reviews).values(
                id=second,
                card_version_id=original.card_version_id,
                target_strategy_version_id=version,
                gate_results=original.gate_results,
                fixture_runs=original.fixture_runs,
                g6_report=original.g6_report,
                compliance_lint=original.compliance_lint,
                decision="rejected",
                created_at=original.created_at,
            )
        )
        with pytest.raises(AppError) as error:
            service.require_approved(None, {}, version, "synthetic", version)
        assert error.value.code == ErrorCode.PROMOTION_GATES_NOT_MET
    first = client.get("/api/v1/admin/promotions", params={"card_id": str(card), "limit": 1})
    assert first.status_code == 200
    cursor = first.json()["next_cursor"]
    assert cursor
    second_page = client.get(
        "/api/v1/admin/promotions", params={"card_id": str(card), "limit": 1, "cursor": cursor}
    )
    assert second_page.status_code == 200
    ids = [first.json()["items"][0]["review_id"], second_page.json()["items"][0]["review_id"]]
    assert ids == sorted([str(identifier), str(second)], reverse=True)
    assert second_page.json()["next_cursor"] is None
    assert (
        client.get("/api/v1/admin/promotions", params={"limit": 1, "cursor": cursor}).status_code
        == 400
    )
    with engine.begin() as conn:
        conn.execute(update(reviews).where(reviews.c.id == identifier).values(compliance_lint={}))
    response = client.get(f"/api/v1/promotion-requests/{identifier}")
    assert response.status_code == 503
    assert response.json()["error"]["details"]["issue"] == "legacy_review_binding_missing"
    with engine.connect() as conn:
        row = conn.execute(select(reviews).where(reviews.c.id == identifier)).one()
        assert row.compliance_lint == {}
        assert row.reviewer_id is None


def test_real_deferred_gate_execution_once_preserves_binding(context: Any) -> None:
    engine, client, _, owner, card, _, _, version = context
    settings = client.app.state.settings
    with engine.begin() as conn:
        identifier, created = service.request_review(conn, owner, card, version, settings)
        assert created
    with engine.begin() as conn:
        duplicate, created = service.request_review(conn, owner, card, version, settings)
        assert duplicate == identifier
        assert not created
        pending = conn.execute(select(reviews).where(reviews.c.id == identifier)).one()
        assert all(g["result"] == "skipped" for g in pending.gate_results)
        original_binding = service.binding_of(pending)
    service.execute_review(engine, owner, identifier, settings)
    with engine.connect() as conn:
        prepared = conn.execute(select(reviews).where(reviews.c.id == identifier)).one()
        assert service.binding_of(prepared) == original_binding
        assert (
            prepared.gate_results[0]["result"] == "fail"
        )  # actual invalid synthetic card, not mocked output
        assert prepared.gate_results[-1]["gate"] == "G7"
        assert prepared.gate_results[-1]["result"] == "skipped"
        assert prepared.reviewer_id is None
        assert prepared.decision == "pending"
        assert prepared.compliance_lint["status"] == "pending_human_review"
        snapshot = dict(prepared._mapping)
    service.execute_review(engine, owner, identifier, settings)
    with engine.connect() as conn:
        assert (
            dict(conn.execute(select(reviews).where(reviews.c.id == identifier)).one()._mapping)
            == snapshot
        )


def test_approved_flag_without_reviewer_never_valid() -> None:
    version = uuid.uuid4()
    binding = {"version_id": str(version), "content_sha256": "a" * 64}
    synthetic = SimpleNamespace(
        target_strategy_version_id=version, decision="approved", reviewer_id=None, reviewed_at=None
    )
    with pytest.raises(AppError) as error:
        service.require_approved(synthetic, binding, version, "a" * 64, version)
    assert error.value.code == ErrorCode.PROMOTION_GATES_NOT_MET
