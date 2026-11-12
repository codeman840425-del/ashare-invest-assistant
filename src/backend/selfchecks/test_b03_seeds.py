# ruff: noqa: S101
"""B-03 isolated synthetic data/transport/contract checks; never use real services."""

from __future__ import annotations

import json
import socket
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from selfchecks import b03_seeds as tool
from selfchecks.b03_shapes import validate

CASES = [
    (resource, case)
    for resource in tool.RESOURCES
    for case in ("stock", "licence_unavailable", "etf", "index", "pending", "minute")
    if case in {"stock", "licence_unavailable"}
    or (case == "etf" and resource != "bars")
    or (case == "index" and resource not in {"bars", "announcements"})
    or (case in {"pending", "minute"} and resource == "bars")
]


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("B-03 attempted real network access")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


@pytest.fixture(scope="module")
def bundle(tmp_path_factory: pytest.TempPathFactory) -> Path:
    parent = tmp_path_factory.mktemp("b03")
    return tool.generate(parent / "fixtures")


def test_b03_generator_is_reproducible_and_never_replaces_existing_data(
    bundle: Path, tmp_path: Path
) -> None:
    other = tool.generate(tmp_path / "again")
    assert len(CASES) == 19
    for source in bundle.iterdir():
        assert source.read_bytes() == (other / source.name).read_bytes()
        assert b"\r" not in source.read_bytes()
    with pytest.raises(FileExistsError, match="fresh"):
        tool.generate(other)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["cases"] == len(CASES)
    assert manifest["upstream_calls"] == 0
    assert manifest["application_routes"] is False


@pytest.mark.parametrize(("resource", "case"), CASES)
def test_b03_json_to_endpoint_skeleton_round_trip(bundle: Path, resource: str, case: str) -> None:
    callback = tool.FixtureEndpoint(bundle, case)
    expected = callback.bundle[resource][case]
    with httpx.Client(
        transport=httpx.MockTransport(callback), base_url="https://b03.invalid"
    ) as client:
        result = client.get(
            expected["request"]["path"],
            params=expected["request"]["params"],
            headers={"x-b03-viewer": "approved"},
        )
    assert result.status_code == 200
    assert result.headers["cache-control"] == "private, no-store"
    assert result.json() == expected["response"]
    validate(resource, result.json(), tool.allowlist())


@pytest.mark.parametrize(
    ("viewer", "status", "code"),
    [
        (None, 401, "AUTH_REQUIRED"),
        ("pending", 403, "ACCOUNT_NOT_APPROVED"),
        ("disabled", 403, "ACCOUNT_NOT_APPROVED"),
    ],
)
def test_b03_permission_negatives_never_expose_fixture_items(
    bundle: Path, viewer: str | None, status: int, code: str
) -> None:
    with httpx.Client(transport=httpx.MockTransport(tool.FixtureEndpoint(bundle))) as client:
        headers = {} if viewer is None else {"x-b03-viewer": viewer}
        result = client.get(
            "https://b03.invalid/api/v1/securities/999999.SH/financials", headers=headers
        )
    assert result.status_code == status
    assert result.json()["error"]["code"] == code
    assert "items" not in result.json()
    assert result.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize(
    ("method", "path", "status"),
    [
        ("POST", "/api/v1/securities/999999.SH/financials", 405),
        ("GET", "/api/v1/securities/000000.SH/financials", 404),
        ("GET", "/api/v1/securities/999999.SH/dividends", 404),
        ("GET", "/api/v1/securities/999999.SH/bars?freq=1m&adjust=qfq", 400),
        ("GET", "https://example.invalid/api/v1/securities/999999.SH/financials", 404),
    ],
)
def test_b03_endpoint_skeleton_is_bounded(
    bundle: Path, method: str, path: str, status: int
) -> None:
    with httpx.Client(
        transport=httpx.MockTransport(tool.FixtureEndpoint(bundle)), base_url="https://b03.invalid"
    ) as client:
        result = client.request(method, path, headers={"x-b03-viewer": "approved"})
    assert result.status_code == status


@pytest.mark.parametrize(
    "mutation",
    [
        "financial_missing",
        "financial_number",
        "financial_calendar",
        "factor_counts",
        "factor_industry_rank",
        "announcement_body",
        "announcement_host",
        "announcement_http",
        "announcement_order",
        "bars_decimal_number",
        "bars_minute_adjust",
        "flow_buckets",
        "invented_asof",
    ],
)
def test_b03_contract_and_semantic_negatives(bundle: Path, mutation: str) -> None:
    payloads = tool.read_bundle(bundle)
    resource = "financials"
    body = deepcopy(payloads[resource]["stock"]["response"])
    if mutation == "financial_missing":
        del body["items"][0]["debt_ratio_pct"]
    elif mutation == "financial_number":
        body["items"][0]["operating_cash_flow"] = 1.25
    elif mutation == "financial_calendar":
        body["items"][0]["available_from"] = "2026-10-31"
    elif mutation.startswith("factor_"):
        resource = "factors"
        body = deepcopy(payloads[resource]["stock"]["response"])
        if mutation == "factor_counts":
            body["counts"]["total"] = 99
        else:
            body["items"][0]["industry_rank"] = 1
    elif mutation.startswith("announcement_"):
        resource = "announcements"
        body = deepcopy(payloads[resource]["stock"]["response"])
        if mutation == "announcement_body":
            body["items"][0]["body"] = "forbidden synthetic body"
        elif mutation == "announcement_order":
            body["items"].reverse()
        else:
            host = "example.invalid" if mutation == "announcement_host" else "www.cninfo.com.cn"
            scheme = "https" if mutation == "announcement_host" else "http"
            body["items"][0].update(url=f"{scheme}://{host}/synthetic.pdf", url_host=host)
    elif mutation.startswith("bars_"):
        resource = "bars"
        body = deepcopy(payloads[resource]["stock"]["response"])
        if mutation == "bars_decimal_number":
            body["items"][0]["amount"] = 1.25
        else:
            body.update(freq="1m", adjust="qfq")
    elif mutation == "flow_buckets":
        resource = "fund-flows"
        body = deepcopy(payloads[resource]["stock"]["response"])
        body["items"][0]["main_net"] = "0.00"
    elif mutation == "invented_asof":
        body = deepcopy(payloads[resource]["licence_unavailable"]["response"])
        body["data_as_of"] = "2026-11-03T15:00:00+08:00"
    with pytest.raises(
        ValueError,
        match=(
            r"validation error|synthetic calendar|factor counts|allowlist|descending|"
            r"adjusted|two large-order|data_as_of"
        ),
    ):
        validate(resource, body, tool.allowlist())


@pytest.mark.parametrize("resource", ["bars", "financials", "announcements"])
def test_b03_unreviewed_model_draft_is_not_accepted(resource: str) -> None:
    draft = json.loads(tool.DRAFT.read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match=r"validation error|descending|allowlist"):
        validate(resource, draft[resource], tool.allowlist())


def test_b03_does_not_trust_a_tampered_bundle(bundle: Path, tmp_path: Path) -> None:
    for source in bundle.iterdir():
        (tmp_path / source.name).write_bytes(source.read_bytes())
    target = tmp_path / "financials.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["stock"]["response"]["items"][0]["revenue"] = "0.00"
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="digest mismatch"):
        tool.FixtureEndpoint(tmp_path)
