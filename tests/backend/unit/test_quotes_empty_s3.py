"""S3-9 HTTP empty quotes: real route/auth, synthetic read-only database facts."""

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

OWNER, OTHER = uuid.UUID(int=711), uuid.UUID(int=712)
CODE, ETF = "999991.SH", "999992.SH"


class Result:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def all(self) -> list[Any]:
        return self.rows

    def scalar_one_or_none(self) -> Any:
        return self.rows[0] if self.rows else None


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Any:
    state = SimpleNamespace(
        reads=[], fail=False, approved=True, active={OWNER}, revoked=[]
    )

    def execute(statement: Any) -> Result:
        rendered = str(statement)
        assert rendered.lstrip().upper().startswith("SELECT "), "GET must never write"
        state.reads.append(rendered)
        if state.fail:
            raise RuntimeError("synthetic database failure")
        params = statement.compile().params
        if "market.securities" in rendered:
            requested = params["code_1"]
            return Result(
                [
                    SimpleNamespace(code=code, name="synthetic " + code)
                    for code in (CODE, ETF)
                    if code in requested
                ]
            )
        assert "app.user_data_licence_status" in rendered
        assert "app.user_data_licence_holds" in rendered
        assert "deleted_at IS NULL" in rendered and "paused_until" in rendered
        assert "expires_on" in rendered and "held" not in params
        return Result(
            [uuid.UUID(int=713)] if params["user_id_1"] in state.active else []
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
        pytest.fail("quote GET must never send, read credentials, or connect")

    from app.ingest import daily_lists, egress

    monkeypatch.setattr(egress, "mairui_get", forbidden)
    monkeypatch.setattr(daily_lists, "credential", forbidden)
    with TestClient(app) as client:
        # Windows creates its asyncio self-pipe at portal startup, before any request.
        monkeypatch.setattr(socket.socket, "connect", forbidden)
        client.cookies.set(SESSION_COOKIE, "a")
        yield SimpleNamespace(client=client, state=state)


def test_registered_quotes_has_explicit_empty_fields_and_no_made_up_time(
    world: Any,
) -> None:
    response = world.client.get("/api/v1/quotes", params={"codes": CODE + "," + ETF})
    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["security_code"] for item in items] == [CODE, ETF]
    for item in items:
        assert set(item) == {
            "security_code",
            "name",
            "price",
            "change_pct",
            "volume",
            "amount",
            "t",
            "data_status",
            "data_as_of",
            "gaps",
        }
        assert all(
            item[key] is None
            for key in ("price", "change_pct", "volume", "amount", "t", "data_as_of")
        )
        assert item["data_status"] == "unavailable"
        assert item["gaps"][0]["reason"] == "no_source"
    assert len(world.state.reads) == 2


def test_owner_query_cannot_borrow_another_users_active_licence(world: Any) -> None:
    world.client.cookies.set(SESSION_COOKIE, "b")
    response = world.client.get(
        "/api/v1/quotes", params={"codes": CODE, "user_id": str(OWNER)}
    )
    assert response.status_code == 200
    assert (
        response.json()["items"][0]["gaps"][0]["reason"] == "data_licence_unavailable"
    )


@pytest.mark.parametrize(
    "query",
    [
        "",
        "?codes=",
        "?codes=oops",
        "?codes=999991.SH,",
        "?codes=999991.SH&codes=999992.SH",
        "?codes=" + ",".join([CODE] * 201),
    ],
)
def test_bad_quotes_query_is_400_before_database_reads(world: Any, query: str) -> None:
    response = world.client.get("/api/v1/quotes" + query)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert world.state.reads == []


def test_two_hundred_requested_codes_are_accepted_and_duplicates_deduplicated(
    world: Any,
) -> None:
    response = world.client.get(
        "/api/v1/quotes", params={"codes": ",".join([CODE] * 200)}
    )
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1


def test_quote_authentication_precedes_invalid_query_and_conditional_cache(
    world: Any,
) -> None:
    world.client.cookies.clear()
    response = world.client.get(
        "/api/v1/quotes?codes=oops", headers={"If-None-Match": "*"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"
    assert world.state.reads == []


def test_pending_user_is_rejected_by_existing_authentication(world: Any) -> None:
    world.state.approved = False
    response = world.client.get("/api/v1/quotes", params={"codes": CODE})
    assert response.status_code == 403
    assert world.state.revoked == [str(OWNER)]
    assert world.state.reads == []


def test_empty_quote_etag_is_private_and_auth_still_checked(world: Any) -> None:
    first = world.client.get(
        "/api/v1/quotes", params={"codes": CODE + "," + CODE.lower()}
    )
    assert first.status_code == 200 and len(first.json()["items"]) == 1
    assert first.headers["cache-control"].startswith("private")
    tag = first.headers["etag"]
    cached = world.client.get(
        "/api/v1/quotes", params={"codes": CODE}, headers={"If-None-Match": tag}
    )
    assert cached.status_code == 304 and cached.content == b""
    world.client.cookies.set(SESSION_COOKIE, "b")
    changed = world.client.get(
        "/api/v1/quotes", params={"codes": CODE}, headers={"If-None-Match": tag}
    )
    assert changed.status_code == 200


def test_unknown_security_is_404_without_creating_a_quote_or_querying_licence(
    world: Any,
) -> None:
    response = world.client.get("/api/v1/quotes", params={"codes": "999999.SH"})
    assert response.status_code == 404
    assert len(world.state.reads) == 1


def test_sql_failures_are_not_hidden_as_successful_empty_quotes(world: Any) -> None:
    world.state.fail = True
    with pytest.raises(RuntimeError, match="synthetic database failure"):
        world.client.get("/api/v1/quotes", params={"codes": CODE})
