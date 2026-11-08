# ruff: noqa: S101, ANN401, F811
"""Fictional users/cards only. Real HTTP, Redis sessions, password hashes and isolated PG.

No canonical strategy key is approved. No real user credentials or G7 action occurs.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import secrets
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
import yaml
from pydantic import SecretStr
from sqlalchemy import insert, select, update

from app.auth import service as auth_service
from app.auth.deps import get_password_policy, get_session_store
from app.auth.passwords import PasswordPolicy
from app.auth.sessions import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE
from app.db.tables.strategy import strategies
from app.db.tables.strategy import strategy_card_versions as cv
from app.db.tables.strategy import strategy_cards as cards
from app.db.tables.strategy import (
    strategy_lifecycle_events as events,
)
from app.db.tables.strategy import (
    strategy_promotion_reviews as reviews,
)
from app.db.tables.strategy import (
    strategy_versions as versions,
)
from app.db.tables.users import audit_logs, users
from app.strategy.cards.persistence import import_batch, validate_batch
from app.strategy.cards.preflight import feature_registry
from selfchecks.test_tb70_replay import integration, no_network  # noqa: F401
from selfchecks.test_tb71_import import ROOT, formal_catalog


@pytest.fixture
def context(integration: Any) -> Any:
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
    registry = feature_registry(formal_catalog())
    source = (ROOT / "docs/strategies/cards/hold_risk_monitor.md").read_text()
    original = validate_batch([source], registry)[0]
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
            source_matrix=(ROOT / "docs/strategies/T-R18_source_matrix.yaml").read_text(),
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


def decide(ctx: Any, **overrides: Any) -> Any:
    body = {
        "decision": "approved",
        "comment": "纯虚构审核测试",
        "ack_warn_gates": ["G6"],
        "password": ctx["password"].get_secret_value(),
        "reviewer_id": str(ctx["other"]),
    }
    body.update(overrides)
    return ctx["client"].post(f"/api/v1/admin/promotions/{ctx['review']}/decision", json=body)


def promote(ctx: Any, **overrides: Any) -> Any:
    body = {
        "to": "simulating",
        "reason": "纯虚构隔离验收",
        "review_id": ctx["review"],
        "password": ctx["password"].get_secret_value(),
    }
    body.update(overrides)
    return ctx["client"].post(
        f"/api/v1/admin/strategies/{ctx['strategy_id']}/versions/{ctx['version_id']}/lifecycle",
        json=body,
    )


def state(ctx: Any) -> Any:
    with ctx["engine"].connect() as conn:
        review = conn.execute(select(reviews).where(reviews.c.id == uuid.UUID(ctx["review"]))).one()
        lifecycle = conn.execute(
            select(versions.c.lifecycle).where(versions.c.id == uuid.UUID(ctx["version_id"]))
        ).scalar_one()
    return review, lifecycle


def test_synthetic_full_chain_and_no_password_persistence(
    context: Any, caplog: pytest.LogCaptureFixture
) -> None:
    ctx = context
    response = decide(ctx)
    assert response.status_code == 200, response.text
    assert response.json()["reviewer_id"] == str(ctx["owner"])
    assert response.json()["stale_reason"] is None
    assert "password" not in response.text
    assert decide(ctx).status_code == 409
    result = promote(ctx)
    assert result.status_code == 200, result.text
    assert result.json() == {"from": "draft", "to": "simulating"}
    assert promote(ctx).status_code == 409
    # Approval of G7 is not publication eligibility.
    assert promote(ctx, to="published").status_code == 422
    row, lifecycle = state(ctx)
    assert row.decision == "approved"
    assert lifecycle == "simulating"
    with ctx["engine"].connect() as conn:
        audits = conn.execute(
            select(audit_logs).where(
                audit_logs.c.actor_id == ctx["owner"],
                audit_logs.c.action.in_(["promotion.decision", "strategy.lifecycle"]),
            )
        ).all()
        assert len(audits) == 2
        assert all(a.actor_id == ctx["owner"] for a in audits)
        assert (
            len(
                conn.execute(
                    select(events).where(
                        events.c.strategy_version_id == uuid.UUID(ctx["version_id"])
                    )
                ).all()
            )
            == 1
        )
    assert ctx["password"].get_secret_value() not in str(dict(row._mapping))
    assert ctx["password"].get_secret_value() not in str(audits)
    assert ctx["password"].get_secret_value() not in caplog.text
    assert ctx["password"].get_secret_value() not in response.text + result.text


def test_wrong_password_lockout_commits_without_decision(context: Any) -> None:
    ctx = context
    failures = ctx["client"].app.state.settings.auth_abuse.lock_after_failures
    for _ in range(failures):
        response = decide(ctx, password=secrets.token_urlsafe(24))
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "REAUTH_FAILED"
    response = decide(ctx)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ACCOUNT_LOCKED"
    row, lifecycle = state(ctx)
    assert row.decision == "pending"
    assert row.reviewer_id is None
    assert lifecycle == "draft"
    with ctx["engine"].connect() as conn:
        user = conn.execute(select(users).where(users.c.id == ctx["owner"])).one()
        assert user.failed_login_count == failures
        assert user.locked_until is not None


@pytest.mark.parametrize("credential", ["legacy_origin", "forged_origin", "bearer", "csrf"])
def test_origin_and_csrf_cannot_be_self_reported(context: Any, credential: str) -> None:
    ctx = context
    client = ctx["client"]
    if credential in {"legacy_origin", "forged_origin"}:
        store = get_session_store(client.app.state.settings)
        sid, session = store.create(str(ctx["owner"]))  # no trusted server login origin
        client.cookies.set(SESSION_COOKIE, sid)
        client.cookies.set(CSRF_COOKIE, session.csrf_token)
        client.headers[CSRF_HEADER] = session.csrf_token
        if credential == "forged_origin":
            client.headers["X-Human"] = "true"
            client.headers["X-Session-Origin"] = "password_login"
    elif credential == "bearer":
        client.headers["Authorization"] = "Bearer fictional_only"
    else:
        client.headers[CSRF_HEADER] = "wrong_csrf"
    response = decide(ctx, origin="password_login", human=True)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == (
        "CSRF_FAILED" if credential == "csrf" else "HUMAN_SESSION_REQUIRED"
    )
    assert state(ctx)[0].decision == "pending"


@pytest.mark.parametrize(
    "failure", ["warn", "gate", "comment", "legacy", "changed", "unapproved", "rejected"]
)
def test_negative_decision_and_promotion_paths(context: Any, failure: str) -> None:
    ctx = context
    if failure == "warn":
        response = decide(ctx, ack_warn_gates=[])
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "PROMOTION_WARN_UNACKNOWLEDGED"
    elif failure == "comment":
        response = decide(ctx, comment="保证")
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "COMPLIANCE_LINT_FAILED"
    elif failure == "unapproved":
        response = promote(ctx)
        assert response.status_code == 422
        assert promote(ctx, review_id=None).status_code == 422
    elif failure == "rejected":
        assert decide(ctx, decision="rejected").status_code == 200
        assert promote(ctx).status_code == 422
    elif failure == "gate":
        with ctx["engine"].begin() as conn:
            row = conn.execute(
                select(reviews).where(reviews.c.id == uuid.UUID(ctx["review"]))
            ).one()
            gates = copy.deepcopy(row.gate_results)
            gates[0]["result"] = "fail"
            conn.execute(update(reviews).where(reviews.c.id == row.id).values(gate_results=gates))
        assert decide(ctx).status_code == 422
        assert decide(ctx, decision="changes_requested").status_code == 200
    elif failure == "legacy":
        with ctx["engine"].begin() as conn:
            conn.execute(
                update(reviews)
                .where(reviews.c.id == uuid.UUID(ctx["review"]))
                .values(compliance_lint={})
            )
        detail = ctx["client"].get(f"/api/v1/promotion-requests/{ctx['review']}")
        assert detail.status_code == 200
        assert detail.json()["stale_reason"] == "legacy_unbound"
        assert detail.json()["version_id"] is None
        assert detail.json()["content_sha256"] is None
        page = ctx["client"].get(
            "/api/v1/admin/promotions", params={"stale": "true", "card_id": ctx["card_id"]}
        )
        assert page.status_code == 200
        assert page.json()["items"][0]["stale_reason"] == "legacy_unbound"
        assert decide(ctx).status_code == 409
        assert promote(ctx).status_code == 409
    elif failure == "changed":
        assert decide(ctx).status_code == 200
        with ctx["engine"].begin() as conn:
            version = conn.execute(
                select(versions).where(versions.c.id == uuid.UUID(ctx["version_id"]))
            ).one()
            config = {**version.config, "synthetic_content_change": True}
            conn.execute(update(versions).where(versions.c.id == version.id).values(config=config))
        assert promote(ctx).status_code == 409
        assert (
            ctx["client"].get(f"/api/v1/promotion-requests/{ctx['review']}").json()["stale_reason"]
            == "content_changed"
        )
    assert state(ctx)[1] == "draft"


def test_concurrent_decisions_only_one_commits(context: Any) -> None:
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: decide(context).status_code, range(2)))
    assert sorted(results) == [200, 409]
    with context["engine"].connect() as conn:
        assert (
            len(
                conn.execute(
                    select(audit_logs.c.id).where(
                        audit_logs.c.action == "promotion.decision",
                        audit_logs.c.target_id == context["review"],
                    )
                ).all()
            )
            == 1
        )


def test_content_race_after_real_password_check_is_stale(
    context: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    checked = threading.Event()
    original = PasswordPolicy.verify

    def verify(self: PasswordPolicy, hashed: str | None, password: str) -> bool:
        valid = original(self, hashed, password)
        if valid:
            checked.set()
        return valid

    monkeypatch.setattr(PasswordPolicy, "verify", verify)
    with context["engine"].connect() as conn:
        tx = conn.begin()
        row = conn.execute(
            select(versions)
            .where(versions.c.id == uuid.UUID(context["version_id"]))
            .with_for_update()
        ).one()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(decide, context)
            assert checked.wait(10)
            conn.execute(
                update(versions)
                .where(versions.c.id == row.id)
                .values(config={**row.config, "synthetic_concurrent_change": True})
            )
            tx.commit()
            response = future.result(timeout=10)
    assert response.status_code == 409
    assert state(context)[0].decision == "pending"


def test_success_audit_failure_rolls_back_review(
    context: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = auth_service.audit

    def audit(conn: Any, **kwargs: Any) -> None:
        if kwargs["action"] == "promotion.decision":
            raise RuntimeError("synthetic_audit_failure")
        original(conn, **kwargs)

    monkeypatch.setattr(auth_service, "audit", audit)
    assert decide(context).status_code == 500
    row, lifecycle = state(context)
    assert row.decision == "pending"
    assert row.reviewer_id is None
    assert lifecycle == "draft"


def test_password_rotation_issues_origin_and_reauth_uses_current_hash(context: Any) -> None:
    ctx = context
    client = ctx["client"]
    store = get_session_store(client.app.state.settings)
    old_sid = client.cookies.get(SESSION_COOKIE)
    new_password = SecretStr("Fictional-rotated#8B-" + secrets.token_hex(10))
    response = client.post(
        "/api/v1/auth/password",
        json={
            "old_password": ctx["password"].get_secret_value(),
            "new_password": new_password.get_secret_value(),
        },
    )
    assert response.status_code == 204, response.text
    assert store.get(old_sid) is None
    current = store.get(client.cookies.get(SESSION_COOKIE))
    assert current is not None
    assert current.origin == "password_login"
    client.headers[CSRF_HEADER] = client.cookies.get(CSRF_COOKIE)
    assert decide(ctx).status_code == 401  # old password no longer valid
    ctx["password"] = new_password
    assert decide(ctx).status_code == 200
    assert promote(ctx, password=secrets.token_urlsafe(24)).status_code == 401
    assert state(ctx)[1] == "draft"
    assert promote(ctx).status_code == 200


def test_legacy_missing_origin_and_approved_review_stays_readonly(context: Any) -> None:
    ctx = context
    client = ctx["client"]
    store = get_session_store(client.app.state.settings)
    session = store.get(client.cookies.get(SESSION_COOKIE))
    assert session is not None
    key = "auth:session:" + session.sid_digest
    record = json.loads(store._r.get(key))
    record.pop("origin")
    store._r.set(key, json.dumps(record), keepttl=True)
    legacy = store.get(client.cookies.get(SESSION_COOKIE))
    assert legacy is not None
    assert legacy.origin is None
    assert decide(ctx).json()["error"]["code"] == "HUMAN_SESSION_REQUIRED"
    with ctx["engine"].begin() as conn:
        conn.execute(
            update(reviews)
            .where(reviews.c.id == uuid.UUID(ctx["review"]))
            .values(
                compliance_lint={},
                decision="approved",
                reviewer_id=ctx["other"],
                reviewed_at=dt.datetime.now(dt.UTC),
            )
        )
    response = client.get(f"/api/v1/promotion-requests/{ctx['review']}")
    assert response.status_code == 200
    assert response.json()["decision"] == "approved"
    assert response.json()["stale_reason"] == "legacy_unbound"
    assert response.json()["version_id"] is None
    assert response.json()["content_sha256"] is None


def test_new_version_stale_reason_and_no_decision(context: Any) -> None:
    ctx = context
    with ctx["engine"].begin() as conn:
        old = conn.execute(
            select(versions).where(versions.c.id == uuid.UUID(ctx["version_id"]))
        ).one()
        old_card = conn.execute(select(cv).where(cv.c.id == old.card_version_id)).one()
        new_cv, new_version = uuid.uuid4(), uuid.uuid4()
        conn.execute(
            insert(cv).values(
                id=new_cv,
                card_id=old_card.card_id,
                version_no=2,
                fields={**old_card.fields, "version_no": 2},
            )
        )
        conn.execute(
            insert(versions).values(
                id=new_version,
                strategy_id=old.strategy_id,
                card_version_id=new_cv,
                version_no=2,
                config=old.config,
                config_hash="fictional_new_version_hash",
                lifecycle="draft",
            )
        )
        conn.execute(
            update(cards).where(cards.c.id == old_card.card_id).values(current_version_id=new_cv)
        )
        conn.execute(
            update(strategies)
            .where(strategies.c.id == old.strategy_id)
            .values(current_version_id=new_version)
        )
    response = ctx["client"].get(f"/api/v1/promotion-requests/{ctx['review']}")
    assert response.status_code == 200
    assert response.json()["stale_reason"] == "new_version"
    assert decide(ctx).status_code == 409
    assert promote(ctx).status_code == 409
    assert state(ctx)[0].decision == "pending"


def test_lifecycle_audit_failure_rolls_back_event_and_version(
    context: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert decide(context).status_code == 200
    original = auth_service.audit

    def audit(conn: Any, **kwargs: Any) -> None:
        if kwargs["action"] == "strategy.lifecycle":
            raise RuntimeError("synthetic_lifecycle_audit_failure")
        original(conn, **kwargs)

    monkeypatch.setattr(auth_service, "audit", audit)
    assert promote(context).status_code == 500
    row, lifecycle = state(context)
    assert row.decision == "approved"
    assert lifecycle == "draft"
    with context["engine"].connect() as conn:
        assert (
            conn.execute(
                select(events.c.id).where(
                    events.c.strategy_version_id == uuid.UUID(context["version_id"])
                )
            ).first()
            is None
        )


def test_coarse_ip_uses_trusted_peer_not_client_header() -> None:
    from starlette.requests import Request

    from app.api.v1.promotions import coarse_ip
    from app.config import Settings

    settings = Settings.model_construct(trusted_proxies=())
    for peer, expected in [
        ("192.0.2.77", "192.0.2.0/24"),
        ("2001:db8:abcd:1234::9", "2001:db8:abcd:1234::/64"),
        ("testclient", None),
    ]:
        request = Request(
            {
                "type": "http",
                "client": (peer, 1234),
                "headers": [(b"x-forwarded-for", b"198.51.100.222")],
            }
        )
        assert coarse_ip(request, settings) == expected
