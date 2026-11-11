"""B-05 announcement route, signed cursors and link safety; all inputs synthetic."""

# ruff: noqa: S101, ANN401
from __future__ import annotations

import time
from collections.abc import Iterator
from copy import deepcopy
from typing import Any
from urllib.parse import quote

import pytest
from starlette.datastructures import QueryParams

from app.api.v1.security_announcements import (
    DISCLAIMER,
    AnnouncementsQuery,
    get_announcements_reader,
)
from app.auth.sessions import SESSION_COOKIE
from app.common.pagination import encode_cursor
from selfchecks.b03_shapes import validate
from selfchecks.b05_harness import (
    ETF,
    STOCK,
    check_access,
    check_defaults,
    check_guard,
    check_scope,
    environment,
)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    with environment(
        monkeypatch, "announcements", get_announcements_reader, lambda b, _q: b
    ) as value:
        yield value


def test_b05_announcements_shape_and_metadata(env: Any) -> None:
    response = env.client.get(env.path)
    assert response.status_code == 200
    body = response.json()
    validate("announcements", body, set())
    assert [row["id"] for row in body["items"]] == ["syn-ann-0002", "syn-ann-0001"]
    assert body["disclaimer"] == DISCLAIMER
    assert body["next_cursor"] is None
    assert "security_code" not in body
    assert not any("summary" in row or "body" in row for row in body["items"])
    assert response.headers["cache-control"] == "private, no-store"


def test_b05_announcements_dates_categories_empty(env: Any) -> None:
    response = env.client.get(env.path + "?from=2026-11-02&to=2026-11-02")
    assert [row["id"] for row in response.json()["items"]] == ["syn-ann-0001"]
    periodic = env.client.get(env.path + "?category=periodic_report")
    assert [row["category"] for row in periodic.json()["items"]] == ["periodic_report"]
    both = env.client.get(env.path + "?category=other,periodic_report")
    assert len(both.json()["items"]) == 2
    empty = env.client.get(env.path + "?to=2026-11-01").json()
    assert empty["items"] == []
    assert empty["data_as_of"] is None
    assert empty["sources"] == []
    validate("announcements", empty, set())


def test_b05_announcements_pagination_ties_no_duplicates(env: Any) -> None:
    first = env.client.get(env.path + "?limit=1").json()
    cursor = first["next_cursor"]
    assert isinstance(cursor, str)
    second = env.client.get(env.path + "?limit=1&cursor=" + quote(cursor)).json()
    assert first["items"][0]["id"] != second["items"][0]["id"]
    assert second["next_cursor"] is None
    # Tie on published_at must use id descending, with an exclusive keyset boundary.
    rows = env.reader.bundle["stock"]["response"]["items"]
    rows[1]["published_at"] = rows[0]["published_at"]
    first = env.client.get(env.path + "?limit=1").json()
    second = env.client.get(env.path + "?limit=1&cursor=" + quote(first["next_cursor"])).json()
    assert first["items"][0]["id"] == "syn-ann-0002"
    assert second["items"][0]["id"] == "syn-ann-0001"


@pytest.mark.parametrize("change", ["owner", "code", "category", "from", "to", "tamper"])
def test_b05_announcements_cursor_cannot_cross_scope(env: Any, change: str) -> None:
    cursor = env.client.get(env.path + "?limit=1").json()["next_cursor"]
    url = env.path + "?limit=1&cursor=" + quote(cursor)
    if change == "owner":
        env.client.cookies.set(SESSION_COOKIE, "b")
    elif change == "code":
        url = url.replace(STOCK, ETF)
    elif change == "tamper":
        payload, signature = cursor.split(".")
        signature = ("a" if signature[0] != "a" else "b") + signature[1:]
        url = env.path + "?cursor=" + quote(payload + "." + signature)
    else:
        url += (
            "&"
            + {"category": "category=other", "from": "from=2026-11-02", "to": "to=2026-11-03"}[
                change
            ]
        )
    response = env.client.get(url)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_CURSOR"


@pytest.mark.parametrize("case", ["expired", "keys", "timezone", "scope"])
def test_b05_announcements_signed_but_invalid_cursor(env: Any, case: str) -> None:
    query = AnnouncementsQuery.parse(QueryParams(), env.settings)
    scope = query.scope(env.owners["a"], STOCK)
    keys: list[Any] = ["2026-11-03T09:00:00+08:00", "syn-ann-0002"]
    at = time.time()
    if case == "expired":
        at -= env.settings.cursor_ttl_s + 5
    elif case == "keys":
        keys = [1]
    elif case == "timezone":
        keys[0] = "2026-11-03T09:00:00"
    else:
        scope = "trades:list"
    cursor = encode_cursor(keys, scope=scope, settings=env.settings, now=at)
    response = env.client.get(env.path + "?cursor=" + quote(cursor))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_CURSOR"


@pytest.mark.parametrize(
    ("scheme", "host", "visible"),
    [
        ("https", "allowlisted", True),
        ("http", "allowlisted", False),
        ("https", "not-whitelisted.example", False),
        ("https", "allowlisted.evil.example", False),
    ],
)
def test_b05_announcements_url_allowlist(
    env: Any,
    monkeypatch: pytest.MonkeyPatch,
    scheme: str,
    host: str,
    visible: bool,
) -> None:
    allowed = env.settings.business.securities.announcements.url_host_allowlist
    host = allowed[0] if host == "allowlisted" else host
    body = deepcopy(env.reader.bundle["stock"]["response"])
    body["items"][0]["url"] = f"{scheme}://{host}/synthetic.pdf"
    monkeypatch.setattr(env.reader, "read", lambda *_args: body)
    response = env.client.get(env.path)
    assert response.status_code == 200
    row = response.json()["items"][0]
    assert (row["url"] is not None) is visible
    assert row["url_host"] == host
    validate("announcements", response.json(), set(allowed))


def test_b05_announcements_url_backslash_bypass(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    allowed = env.settings.business.securities.announcements.url_host_allowlist
    body = deepcopy(env.reader.bundle["stock"]["response"])
    # WHATWG treats the backslash as a path separator: the actual host is outside.example.
    body["items"][0]["url"] = f"https://outside.example\\@{allowed[0]}/synthetic.pdf"
    safe = f"https://{allowed[0]}/synthetic.pdf"
    body["items"][1]["url"] = safe
    monkeypatch.setattr(env.reader, "read", lambda *_args: body)
    response = env.client.get(env.path)
    assert response.status_code == 200
    rows = response.json()["items"]
    assert [row["id"] for row in rows] == ["syn-ann-0002", "syn-ann-0001"]
    assert rows[0]["url"] is None
    assert rows[0]["url_host"] == "outside.example"
    assert rows[1]["url"] == safe
    assert rows[1]["url_host"] == allowed[0]
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["etag"]


@pytest.mark.parametrize("broken", ["https://[invalid/synthetic.pdf", "https://[gg::1]/x"])
def test_b05_announcements_malformed_url_keeps_page(
    env: Any, monkeypatch: pytest.MonkeyPatch, broken: str
) -> None:
    allowed = env.settings.business.securities.announcements.url_host_allowlist
    body = deepcopy(env.reader.bundle["stock"]["response"])
    safe = f"https://{allowed[0]}/synthetic.pdf"
    body["items"][0]["url"] = broken
    body["items"][0]["url_host"] = allowed[0]  # Must not retain misleading source metadata.
    body["items"][1]["url"] = safe
    monkeypatch.setattr(env.reader, "read", lambda *_args: body)
    response = env.client.get(env.path)
    assert response.status_code == 200
    rows = response.json()["items"]
    assert [row["id"] for row in rows] == ["syn-ann-0002", "syn-ann-0001"]
    assert rows[0]["url"] is None
    assert rows[0]["url_host"] is None
    assert rows[1]["url"] == safe
    assert rows[1]["url_host"] == allowed[0]
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["etag"]
    validate("announcements", response.json(), set(allowed))


@pytest.mark.parametrize("path", [r"\synthetic.pdf", r"/folder\synthetic.pdf"])
def test_b05_announcements_returns_the_checked_normalized_url(
    env: Any, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    allowed = env.settings.business.securities.announcements.url_host_allowlist
    body = deepcopy(env.reader.bundle["stock"]["response"])
    body["items"][0]["url"] = f"https://{allowed[0]}{path}"
    monkeypatch.setattr(env.reader, "read", lambda *_args: body)
    response = env.client.get(env.path)
    assert response.status_code == 200
    row = response.json()["items"][0]
    expected_path = "/synthetic.pdf" if path.startswith("\\") else "/folder/synthetic.pdf"
    assert row["url"] == f"https://{allowed[0]}{expected_path}"
    assert "\\" not in row["url"]
    assert row["url_host"] == allowed[0]
    validate("announcements", response.json(), set(allowed))


@pytest.mark.parametrize(
    ("raw", "known_host"),
    [
        ("https://user@{host}/synthetic.pdf", True),
        ("https://{host}/synthetic\n.pdf", False),
        ("https://{host}:invalid/synthetic.pdf", False),
        ("https://{host}:65536/synthetic.pdf", False),
    ],
)
def test_b05_announcements_ambiguous_authority_disables_link(
    env: Any, monkeypatch: pytest.MonkeyPatch, raw: str, known_host: bool
) -> None:
    allowed = env.settings.business.securities.announcements.url_host_allowlist
    body = deepcopy(env.reader.bundle["stock"]["response"])
    body["items"][0]["url"] = raw.format(host=allowed[0])
    monkeypatch.setattr(env.reader, "read", lambda *_args: body)
    response = env.client.get(env.path)
    assert response.status_code == 200
    row = response.json()["items"][0]
    assert row["url"] is None
    assert row["url_host"] == (allowed[0] if known_host else None)


@pytest.mark.parametrize(
    "query",
    [
        "?limit=0",
        "?limit=201",
        "?limit=bad",
        "?limit=1&limit=2",
        "?category=unknown",
        "?category=",
        "?from=2026-02-30",
        "?to=20261102",
        "?from=2026-11-03&to=2026-11-02",
        "?from=2026-11-02&from=2026-11-03",
    ],
)
def test_b05_announcements_invalid_400(env: Any, query: str) -> None:
    response = env.client.get(env.path + query)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("cursor", ["", "bad", "a" * 2049])
def test_b05_announcements_malformed_cursor_400(env: Any, cursor: str) -> None:
    response = env.client.get(env.path + "?cursor=" + cursor)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_CURSOR"


def test_b05_announcements_auth(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    check_access(env, monkeypatch)


def test_b05_announcements_owner_etag(env: Any) -> None:
    check_scope(env)


def test_b05_announcements_default_404_and_empty(env: Any) -> None:
    check_defaults(env)


@pytest.mark.parametrize("mode", ["staging", "production"])
def test_b05_announcements_production_guard(env: Any, mode: str) -> None:
    check_guard(env, mode)
