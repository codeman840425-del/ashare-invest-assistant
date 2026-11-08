# ruff: noqa: S101, ANN401, F811
"""T-A21 only. Fictional identities/cards in networkless isolated PG/Redis."""

from __future__ import annotations

import copy
import secrets
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, update

from app.auth.sessions import CSRF_HEADER, SESSION_COOKIE
from app.db.tables.strategy import strategy_lifecycle_events as events
from app.db.tables.strategy import strategy_promotion_reviews as reviews
from app.db.tables.strategy import strategy_versions as versions
from app.db.tables.users import users
from app.strategy import reviews as service
from app.strategy.g6 import QUOTA_UNKNOWN_REASON, QuotaDelta, compare, missing_history_gate
from app.strategy.promotions import public_review
from selfchecks.test_tb70_replay import integration, no_network  # noqa: F401
from selfchecks.test_tb83b_reauth import context, decide, promote  # noqa: F401

STATES = ["draft", "simulating", "published", "observing", "retired"]


def security_state(ctx: Any) -> tuple[Any, int]:
    with ctx["engine"].connect() as conn:
        user = conn.execute(
            select(users.c.failed_login_count, users.c.locked_until).where(
                users.c.id == ctx["owner"]
            )
        ).one()
        count = conn.execute(
            select(func.count())
            .select_from(events)
            .where(events.c.strategy_version_id == uuid.UUID(ctx["version_id"]))
        ).scalar_one()
        return user, count


def test_admin_cookie_identity_precedes_authorization_and_body(context: Any) -> None:
    ctx = context
    client, stranger = ctx["client"], ctx["stranger"]
    route = f"/api/v1/admin/promotions/{ctx['review']}/decision"
    stranger.headers["Authorization"] = "Bearer synthetic-not-a-credential"
    stranger.headers.pop(CSRF_HEADER, None)
    assert stranger.post(route, json={}).status_code == 404  # regular user even without CSRF
    stranger.cookies.clear()
    assert stranger.post(route, json={}).status_code == 404  # anonymous + bearer
    assert stranger.get("/api/v1/admin/promotions").status_code == 404
    stranger.cookies.set(SESSION_COOKIE, "synthetic-invalid-session")
    assert stranger.post(route, json={}).status_code == 404
    client.headers["Authorization"] = "Bearer synthetic-not-a-credential"
    response = decide(ctx)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "HUMAN_SESSION_REQUIRED"
    client.headers["Authorization"] = ""  # header presence is not a browser credential
    assert decide(ctx).json()["error"]["code"] == "HUMAN_SESSION_REQUIRED"
    token = client.headers.pop(CSRF_HEADER)
    assert decide(ctx).json()["error"]["code"] == "CSRF_FAILED"  # preserve current_admin ordering
    client.headers[CSRF_HEADER] = token
    with ctx["engine"].begin() as conn:
        conn.execute(update(users).where(users.c.id == ctx["owner"]).values(status="disabled"))
    assert decide(ctx).status_code == 404  # nonapproved admin never reaches header checks


def test_missing_or_null_password_all_source_target_pairs_do_not_count(context: Any) -> None:
    ctx = context
    url = f"/api/v1/admin/strategies/{ctx['strategy_id']}/versions/{ctx['version_id']}/lifecycle"
    before = security_state(ctx)
    for source in STATES:
        with ctx["engine"].begin() as conn:
            conn.execute(
                update(versions)
                .where(versions.c.id == uuid.UUID(ctx["version_id"]))
                .values(lifecycle=source)
            )
        for target in STATES:
            for null in (False, True):
                body = {"to": target, "reason": "合成缺值检查", "review_id": ctx["review"]}
                if null:
                    body["password"] = None
                response = ctx["client"].post(url, json=body)
                assert response.status_code == 400
                assert response.json()["error"]["code"] == "VALIDATION_ERROR"
        with ctx["engine"].connect() as conn:
            assert (
                conn.execute(
                    select(versions.c.lifecycle).where(
                        versions.c.id == uuid.UUID(ctx["version_id"])
                    )
                ).scalar_one()
                == source
            )
    assert security_state(ctx) == before


def test_wrong_password_all_targets_counts_existing_lockout(context: Any) -> None:
    ctx = context
    for i, target in enumerate(STATES, 1):
        response = promote(ctx, to=target, password=secrets.token_urlsafe(24))
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "REAUTH_FAILED"
        assert security_state(ctx)[0].failed_login_count == i
    assert promote(ctx, to="retired").json()["error"]["code"] == "ACCOUNT_LOCKED"
    before = security_state(ctx)
    assert promote(ctx, to="retired", password=None).status_code == 400
    assert security_state(ctx) == before


def test_correct_password_all_source_target_pairs_preserve_transition_rules(context: Any) -> None:
    ctx = context
    assert decide(ctx).status_code == 200  # strictly fictional card and account
    for source in STATES:
        for target in STATES:
            with ctx["engine"].begin() as conn:
                conn.execute(
                    update(versions)
                    .where(versions.c.id == uuid.UUID(ctx["version_id"]))
                    .values(lifecycle=source)
                )
            before = security_state(ctx)[1]
            response = promote(ctx, to=target)
            if source == target or source == "retired":
                expected = 409
            elif source == "draft" and target == "simulating":
                expected = 200
            elif source == "simulating" and target == "published":
                expected = 422  # publication evidence chain intentionally remains closed
            elif target == "retired":
                expected = 200
            else:
                expected = 409
            assert response.status_code == expected, (source, target, response.status_code)
            assert security_state(ctx)[1] == before + (expected == 200)
    assert security_state(ctx)[0].failed_login_count == 0


@pytest.mark.parametrize("bad", [0.0, "0", False])
def test_quota_rejects_float_string_and_boolean(bad: object) -> None:
    with pytest.raises(ValidationError):
        QuotaDelta.model_validate({"quota_delta_per_min": bad})


@pytest.mark.parametrize("value", [0, 7, None])
def test_quota_is_int_or_null_only(value: int | None) -> None:
    result = QuotaDelta(quota_delta_per_min=value).model_dump()["quota_delta_per_min"]
    assert result is None or type(result) is int


@pytest.mark.parametrize("fixture_ok", [False, True])
def test_unknown_quota_never_turns_fixture_failure_into_warning(fixture_ok: bool) -> None:
    gate = missing_history_gate(fixture_ok, compare(None, set(), []), quota_unknown=True)
    assert gate["result"] == ("warn" if fixture_ok else "fail")
    assert gate["detail"]["quota_delta_reason"] == QUOTA_UNKNOWN_REASON
    assert gate["detail"]["max_jaccard_null_reason"] == "no_history"
    assert gate["detail"]["fixtures_all_pass"] == fixture_ok


def test_real_engine_and_placeholder_preserve_unknown_quota(context: Any) -> None:
    ctx = context
    initial = ctx["client"].get(f"/api/v1/promotion-requests/{ctx['review']}").json()
    assert type(initial["g6_report"]["quota_delta_per_min"]) is int
    assert initial["g6_report"]["quota_delta_per_min"] == 0
    vid = uuid.UUID(ctx["version_id"])
    with ctx["engine"].begin() as conn:
        config = copy.deepcopy(
            conn.execute(select(versions.c.config).where(versions.c.id == vid)).scalar_one()
        )
        config["validation"]["feature_requests"] = ["synthetic_unimplemented_feature"]
        conn.execute(update(versions).where(versions.c.id == vid).values(config=config))
        review_id, created = service.request_review(
            conn, ctx["owner"], uuid.UUID(ctx["card_id"]), vid, ctx["client"].app.state.settings
        )
        assert created
        pending = conn.execute(
            select(reviews.c.g6_report).where(reviews.c.id == review_id)
        ).scalar_one()
        assert pending["quota_delta_per_min"] is None
    service.execute_review(ctx["engine"], ctx["owner"], review_id, ctx["client"].app.state.settings)
    detail = ctx["client"].get(f"/api/v1/promotion-requests/{review_id}").json()
    assert detail["g6_report"]["quota_delta_per_min"] is None
    gate = next(g for g in detail["gate_results"] if g["gate"] == "G6")
    assert gate["result"] == "warn"
    assert gate["detail"]["quota_delta_reason"] == QUOTA_UNKNOWN_REASON
    assert all(run["passed"] for run in detail["fixture_runs"])


@pytest.mark.parametrize("stored", ["pass", "warn", "fail", "skipped"])
def test_read_projection_unknown_quota_preserves_failure_evidence(stored: str) -> None:
    row = SimpleNamespace(
        decision="pending",
        fixture_runs=[],
        gate_results=[
            {"gate": "G6", "result": stored, "detail": {"evidence": "synthetic-existing-evidence"}}
        ],
        g6_report={
            "max_jaccard": None,
            "max_jaccard_null_reason": "no_history",
            "quota_delta_per_min": None,
        },
    )
    before = copy.deepcopy(row.gate_results)
    public = public_review(row)
    assert public["gate_results"][0]["result"] == ("warn" if stored == "pass" else stored)
    assert public["gate_results"][0]["detail"]["evidence"] == "synthetic-existing-evidence"
    assert public["gate_results"][0]["detail"]["quota_delta_reason"] == QUOTA_UNKNOWN_REASON
    assert row.gate_results == before
