"""T-B01 报告 §6 建议 5：游标分页（契约 §1.2）。

用一个只用于测试的列表路由（内存数据、含相同 created_at 的并列行）走真实的
``page_params`` / ``build_page`` / ``decode_cursor``。
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any

import pytest

pytestmark = [pytest.mark.unit]

SCOPE = "test:list"
N_ROWS = 237


def _rows() -> list[dict[str, Any]]:
    # 每 3 行共用一个 created_at，制造并列；排序 created_at desc, id desc
    rows = [{"id": f"{i:05d}", "created_at": f"2026-11-01T10:{(i // 3) % 60:02d}:{(i // 180):02d}+08:00"} for i in range(N_ROWS)]
    return sorted(rows, key=lambda r: (r["created_at"], r["id"]), reverse=True)


@pytest.fixture
def setup(backend, make_settings):
    from fastapi import APIRouter, Depends

    pg = backend.pagination
    settings = make_settings()
    app = backend.main.create_app(settings)
    data = _rows()
    r = APIRouter()

    @r.get("/_test/list")
    def list_rows(p=Depends(pg.page_params)) -> dict[str, Any]:  # noqa: B008
        rows = data
        if p.cursor:
            ca, rid = pg.decode_cursor(p.cursor, scope=SCOPE, settings=settings)
            rows = [x for x in data if (x["created_at"], x["id"]) < (ca, rid)]
        page = pg.build_page(rows[: p.limit + 1], limit=p.limit, key=lambda x: (x["created_at"], x["id"]), scope=SCOPE, settings=settings)
        return page.model_dump()

    app.include_router(r, prefix=settings.api_prefix)
    return app, settings, data


@pytest.fixture
def client(make_client, setup):
    return make_client(app=setup[0])


def _walk(client, limit: int | None) -> list[str]:
    ids: list[str] = []
    cursor = None
    for _ in range(N_ROWS + 2):
        q = {} if limit is None else {"limit": limit}
        if cursor:
            q["cursor"] = cursor
        body = client.get("/api/v1/_test/list", params=q).json()
        assert set(body) == {"items", "next_cursor"}
        ids += [x["id"] for x in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            return ids
    raise AssertionError("分页没有终止")


@pytest.mark.parametrize("limit", [None, 1, 7, 200])
def test_walk_all_pages_no_dup_no_gap(client, setup, limit):
    ids = _walk(client, limit)
    assert ids == [x["id"] for x in setup[2]]


def test_default_page_size(client):
    assert len(client.get("/api/v1/_test/list").json()["items"]) == 50


def test_last_page_cursor_null_when_exact_multiple(backend, setup):
    _, settings, data = setup
    page = backend.pagination.build_page(data[:10], limit=10, key=lambda x: (x["id"],), scope=SCOPE, settings=settings)
    assert page.next_cursor is None


def _first_cursor(client) -> str:
    return client.get("/api/v1/_test/list?limit=5").json()["next_cursor"]


def _assert_invalid(resp) -> None:
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"]["code"] == "INVALID_CURSOR"


def test_tampered_one_char(client):
    cur = _first_cursor(client)
    i = len(cur) // 3
    bad = cur[:i] + ("A" if cur[i] != "A" else "B") + cur[i + 1 :]
    _assert_invalid(client.get("/api/v1/_test/list", params={"cursor": bad}))


@pytest.mark.parametrize("mutate", ["truncate", "no_dot", "two_dots", "garbage", "sig_only"])
def test_malformed(client, mutate):
    cur = _first_cursor(client)
    bad = {
        "truncate": cur[:-3],
        "no_dot": cur.replace(".", ""),
        "two_dots": cur + ".x",
        "garbage": "%%%.@@@",
        "sig_only": "." + cur.split(".")[1],
    }[mutate]
    _assert_invalid(client.get("/api/v1/_test/list", params={"cursor": bad}))


def test_payload_swap_keeps_sig_rejected(client):
    cur = _first_cursor(client)
    payload_b64, sig = cur.split(".")
    body = json.loads(base64.urlsafe_b64decode(payload_b64 + "=" * (-len(payload_b64) % 4)))
    body["k"] = ["9999", "99999"]
    forged = base64.urlsafe_b64encode(json.dumps(body, separators=(",", ":")).encode()).rstrip(b"=").decode()
    _assert_invalid(client.get("/api/v1/_test/list", params={"cursor": f"{forged}.{sig}"}))


def test_other_scope_rejected(backend, client, setup):
    cur = backend.pagination.encode_cursor(["x", "y"], scope="other:list", settings=setup[1])
    _assert_invalid(client.get("/api/v1/_test/list", params={"cursor": cur}))


def test_expired_and_future_iat(backend, setup):
    pg, settings = backend.pagination, setup[1]
    now = time.time()
    old = pg.encode_cursor(["a"], scope=SCOPE, settings=settings, now=now - settings.cursor_ttl_s - 5)
    future = pg.encode_cursor(["a"], scope=SCOPE, settings=settings, now=now + 600)
    ok = pg.encode_cursor(["a"], scope=SCOPE, settings=settings, now=now - settings.cursor_ttl_s + 60)
    for cur in (old, future):
        with pytest.raises(backend.errors.AppError) as ei:
            pg.decode_cursor(cur, scope=SCOPE, settings=settings, now=now)
        assert ei.value.code == "INVALID_CURSOR"
    assert pg.decode_cursor(ok, scope=SCOPE, settings=settings, now=now) == ["a"]


def test_other_master_key_rejected(backend, setup, make_settings):
    pg = backend.pagination
    cur = pg.encode_cursor(["a"], scope=SCOPE, settings=setup[1])
    other = make_settings(app_master_key="another-test-only-key-" + "y" * 16)
    with pytest.raises(backend.errors.AppError):
        pg.decode_cursor(cur, scope=SCOPE, settings=other)


def test_empty_cursor_treated_as_first_page(client):
    assert len(client.get("/api/v1/_test/list?cursor=&limit=3").json()["items"]) == 3


def test_decode_empty_string_invalid(backend, setup):
    with pytest.raises(backend.errors.AppError):
        backend.pagination.decode_cursor("", scope=SCOPE, settings=setup[1])
