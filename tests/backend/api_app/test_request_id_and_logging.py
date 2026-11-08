"""T-B01 报告 §6 建议 3（request_id）与 9（访问日志）。"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor

import pytest

pytestmark = [pytest.mark.unit]

GENERATED = re.compile(r"^req_[0-9a-f]{32}$")


@pytest.fixture
def app_with_echo(backend, make_settings):
    import asyncio

    from fastapi import APIRouter

    settings = make_settings()
    app = backend.main.create_app(settings)
    r = APIRouter()

    @r.get("/_test/rid")
    async def rid(delay_ms: int = 0) -> dict[str, str | None]:
        before = backend.request_id.get_request_id()
        await asyncio.sleep(delay_ms / 1000)
        after = backend.request_id.get_request_id()
        return {"before": before, "after": after}

    app.include_router(r, prefix=settings.api_prefix)
    return app


@pytest.fixture
def client(make_client, app_with_echo):
    return make_client(app=app_with_echo)


def test_generated_when_missing(client):
    resp = client.get("/api/v1/_test/rid")
    rid = resp.headers["X-Request-Id"]
    assert GENERATED.match(rid)
    assert resp.json() == {"before": rid, "after": rid}


@pytest.mark.parametrize("value", ["abc-123", "req_0123456789abcdef", "a.b:c_d-e", "x" * 128])
def test_valid_passthrough(client, value):
    resp = client.get("/api/v1/_test/rid", headers={"X-Request-Id": value})
    assert resp.headers["X-Request-Id"] == value


def test_surrounding_whitespace_stripped(client):
    assert client.get("/api/v1/_test/rid", headers={"X-Request-Id": "  ok-1  "}).headers["X-Request-Id"] == "ok-1"


@pytest.mark.parametrize("value", ["has space", "x" * 129, "semi;colon", "slash/x", "中文", "", "a\tb"])
def test_invalid_replaced(client, value):
    resp = client.get("/api/v1/_test/rid", headers={"X-Request-Id": value.encode("utf-8")})
    rid = resp.headers["X-Request-Id"]
    assert GENERATED.match(rid), rid
    assert rid != value


def test_error_response_carries_same_rid(client):
    resp = client.get("/api/v1/nope", headers={"X-Request-Id": "rid-err-1"})
    assert resp.headers["X-Request-Id"] == "rid-err-1"
    assert resp.json()["error"]["request_id"] == "rid-err-1"


def test_concurrent_requests_isolated(client):
    def call(i: int) -> tuple[str, dict]:
        rid = f"rid-conc-{i}"
        r = client.get(f"/api/v1/_test/rid?delay_ms={(i * 7) % 30}", headers={"X-Request-Id": rid})
        return rid, {"hdr": r.headers["X-Request-Id"], **r.json()}

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(call, range(32)))
    for rid, got in results:
        assert got == {"hdr": rid, "before": rid, "after": rid}


def test_context_cleared_after_request(backend, client):
    client.get("/api/v1/_test/rid", headers={"X-Request-Id": "rid-leftover"})
    assert backend.request_id.get_request_id() is None


# ---------------- 9. 访问日志 ----------------
def test_access_log_one_line_with_rid_without_query(backend, client, caplog):
    caplog.set_level(logging.INFO, logger="app.access")
    caplog.handler.addFilter(backend.logging.RequestIdFilter())
    client.get("/api/v1/_test/rid?token=QUERY_SECRET_MARKER&x=1", headers={"X-Request-Id": "rid-log-1"})
    access = [r for r in caplog.records if r.name == "app.access"]
    assert len(access) == 1
    rec = access[0]
    assert rec.request_id == "rid-log-1"
    msg = rec.getMessage()
    assert msg.startswith("GET /api/v1/_test/rid 200 ")
    assert "QUERY_SECRET_MARKER" not in msg and "?" not in msg
    # httpx 是测试客户端自己的日志，不算服务端
    server_text = "\n".join(r.getMessage() for r in caplog.records if not r.name.startswith("httpx"))
    assert "QUERY_SECRET_MARKER" not in server_text


def test_access_log_for_500(backend, make_settings, make_client, caplog):
    from fastapi import APIRouter

    settings = make_settings()
    app = backend.main.create_app(settings)
    r = APIRouter()

    @r.get("/_test/boom")
    def boom() -> None:
        raise RuntimeError("boom")

    app.include_router(r, prefix=settings.api_prefix)
    caplog.set_level(logging.INFO)
    make_client(app=app).get("/api/v1/_test/boom")
    access = [r.getMessage() for r in caplog.records if r.name == "app.access"]
    assert len(access) == 1 and " 500 " in access[0]


def test_log_format_has_request_id(backend):
    assert "request_id=%(request_id)s" in backend.logging.LOG_FORMAT
