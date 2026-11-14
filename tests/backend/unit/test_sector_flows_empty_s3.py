"""S3-9 sector HTTP empty states: actual router/auth and synthetic read-only SQL."""

from __future__ import annotations

import datetime as dt
import socket
import uuid
from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any

import pytest
from app.api.v1 import router
from app.auth import deps
from app.auth.sessions import SESSION_COOKIE, Session
from app.common.errors import install_exception_handlers
from fastapi import FastAPI
from fastapi.testclient import TestClient

OWNER, OTHER = uuid.UUID(int=721), uuid.UUID(int=722)
PATH = "/api/v1/market/sector-flows"


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Any:
    state = SimpleNamespace(
        reads=[], fail=False, approved=True, active={OWNER}, revoked=[]
    )

    def execute(statement: Any) -> Any:
        rendered = str(statement)
        assert rendered.lstrip().upper().startswith("SELECT "), "GET must never write"
        assert "app.user_data_licence_status" in rendered
        assert "app.user_data_licence_holds" in rendered
        assert "deleted_at IS NULL" in rendered and "paused_until" in rendered
        assert "expires_on" in rendered
        assert "market." not in rendered, "no global unowned sector data"
        params = statement.compile().params
        state.reads.append((rendered, params))
        if state.fail:
            raise RuntimeError("synthetic sector database failure")
        return SimpleNamespace(
            scalar_one_or_none=lambda: (
                uuid.UUID(int=723) if params["user_id_1"] in state.active else None
            )
        )

    engine = SimpleNamespace(
        connect=lambda: nullcontext(SimpleNamespace(execute=execute))
    )
    sessions = {
        key: Session(
            "synthetic", str(owner), "synthetic", dt.datetime.now(dt.UTC).isoformat()
        )
        for key, owner in (("a", OWNER), ("b", OTHER))
    }
    store = SimpleNamespace(
        get=lambda sid: sessions.get(sid),
        delete=lambda session: None,
        revoke_user=state.revoked.append,
    )
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[deps.get_engine] = lambda: engine
    app.dependency_overrides[deps.get_session_store] = lambda: store
    monkeypatch.setattr(
        deps,
        "load_user",
        lambda _engine, uid: SimpleNamespace(
            id=uid, status="approved" if state.approved else "pending"
        ),
    )

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("sector GET must never send, read credentials, or connect")

    from app.ingest import daily_lists, egress

    monkeypatch.setattr(egress, "mairui_get", forbidden)
    monkeypatch.setattr(daily_lists, "credential", forbidden)
    with TestClient(app) as client:
        # Windows portal startup needs its local asyncio self-pipe first.
        monkeypatch.setattr(socket.socket, "connect", forbidden)
        client.cookies.set(SESSION_COOKIE, "a")
        yield SimpleNamespace(client=client, state=state)


@pytest.mark.parametrize("kind", ["industry", "concept"])
def test_sector_never_obtained_has_all_six_explicit_empty_fields(
    world: Any, kind: str
) -> None:
    response = world.client.get(PATH, params={"kind": kind})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "kind",
        "taxonomy",
        "trade_date",
        "items",
        "sources",
        "data_status",
        "data_as_of",
        "gaps",
    }
    assert body["kind"] == kind
    assert body["items"] == [] and body["sources"] == []
    assert body["trade_date"] is None and body["taxonomy"] is None
    assert body["data_status"] == "unavailable" and body["data_as_of"] is None
    assert body["gaps"][0]["reason"] == "no_source"
    assert len(world.state.reads) == 1


def test_sector_client_owner_cannot_borrow_another_users_licence(world: Any) -> None:
    world.client.cookies.set(SESSION_COOKIE, "b")
    response = world.client.get(
        PATH, params={"kind": "industry", "user_id": str(OWNER)}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["gaps"][0]["reason"] == "data_licence_unavailable"
    assert body["trade_date"] is None and body["taxonomy"] is None
    assert world.state.reads[0][1]["user_id_1"] == OTHER


@pytest.mark.parametrize(
    "query",
    [
        "",
        "?kind=",
        "?kind=bogus",
        "?kind=industry&kind=concept",
        "?kind=industry&sort=bogus",
        "?kind=industry&sort=main_net_desc&sort=main_net_asc",
        "?kind=industry&limit=0",
        "?kind=industry&limit=101",
        "?kind=industry&limit=-1",
        "?kind=industry&limit=1.5",
        "?kind=industry&limit=",
        "?kind=industry&limit=1&limit=2",
    ],
)
def test_sector_invalid_query_is_400_before_sql(world: Any, query: str) -> None:
    response = world.client.get(PATH + query)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert world.state.reads == []


@pytest.mark.parametrize(
    "sort", ["main_net_desc", "main_net_asc", "change_pct_desc", "change_pct_asc"]
)
@pytest.mark.parametrize("limit", [1, 100])
def test_sector_existing_sort_enums_and_limit_boundaries(
    world: Any, sort: str, limit: int
) -> None:
    response = world.client.get(
        PATH, params={"kind": "concept", "sort": sort, "limit": limit}
    )
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_sector_auth_precedes_invalid_query_and_conditional_cache(world: Any) -> None:
    world.client.cookies.clear()
    response = world.client.get(PATH + "?kind=bad", headers={"If-None-Match": "*"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"
    assert world.state.reads == []


def test_sector_pending_account_is_rejected_by_actual_auth(world: Any) -> None:
    world.state.approved = False
    response = world.client.get(PATH, params={"kind": "industry"})
    assert response.status_code == 403
    assert world.state.revoked == [str(OWNER)]
    assert world.state.reads == []


def test_sector_private_etag_still_rechecks_auth_and_owner(world: Any) -> None:
    first = world.client.get(PATH, params={"kind": "industry"})
    assert first.status_code == 200
    assert first.headers["cache-control"].startswith("private")
    tag = first.headers["etag"]
    response = world.client.get(
        PATH, params={"kind": "industry"}, headers={"If-None-Match": tag}
    )
    assert response.status_code == 304 and response.content == b""
    world.client.cookies.set(SESSION_COOKIE, "b")
    other = world.client.get(
        PATH, params={"kind": "industry"}, headers={"If-None-Match": tag}
    )
    assert other.status_code == 200
    assert other.json()["gaps"][0]["reason"] == "data_licence_unavailable"
    world.client.cookies.clear()
    assert (
        world.client.get(
            PATH, params={"kind": "industry"}, headers={"If-None-Match": tag}
        ).status_code
        == 401
    )


def test_sector_sql_failure_does_not_become_successful_empty_data(world: Any) -> None:
    world.state.fail = True
    with pytest.raises(RuntimeError, match="synthetic sector database failure"):
        world.client.get(PATH, params={"kind": "industry"})
