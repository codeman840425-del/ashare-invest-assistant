"""PROFILE: actual authenticated routes, applicability and permission boundaries."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

_spec = importlib.util.spec_from_file_location(
    "profile_t23", Path(__file__).with_name("test_contract_v028_t_t23.py")
)
_t23 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_t23)
authdb, sql, app_client, mkuser, session, make_settings = (
    _t23.authdb,
    _t23.sql,
    _t23.app_client,
    _t23.mkuser,
    _t23.session,
    _t23.make_settings,
)
DATASETS = ("financials", "fund-flows", "factors", "announcements")
pytestmark = pytest.mark.integration


@pytest.mark.parametrize("dataset", DATASETS)
def test_real_etf_dataset_body_and_conditional_cache(
    session: Any, sql: Any, dataset: str
) -> None:
    s = session()
    _t23.seed_securities(sql)
    path = "/api/v1/securities/510981.SH/" + dataset
    response = s.client.get(path)
    assert response.status_code == 200
    body = response.json()
    assert body["security_code"] == "510981.SH" and body["name"] == "测廿三ETF"
    assert body["items"] == [] and body["sources"] == []
    assert body["data_status"] == "unavailable" and body["data_as_of"] is None
    assert [(g["key"], g["reason"]) for g in body["gaps"]] == [
        (dataset.replace("-", "_"), "not_applicable")
    ]
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["etag"].startswith('W/"')
    cached = s.client.get(path, headers={"If-None-Match": response.headers["etag"]})
    assert cached.status_code == 304 and cached.content == b""
    assert cached.headers["cache-control"] == "private, no-store"
    if dataset == "factors":
        assert body["counts"] == {"total": 0, "by_category": {}}
        assert body["factor_set_version"] is None
    if dataset == "announcements":
        assert body["next_cursor"] is None
        assert (
            body["disclaimer"]
            == "公告内容以交易所及上市公司披露原文为准，本系统仅提供标题与原文链接。"
        )


@pytest.mark.parametrize("dataset", DATASETS)
def test_authentication_precedes_dataset_query_validation(
    app_client: Any, dataset: str
) -> None:
    response = app_client().get(
        "/api/v1/securities/510981.SH/" + dataset,
        params={"limit": "bad", "days": "bad"},
    )
    _t23.assert_err(response, 401, "AUTH_REQUIRED")
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("dataset", DATASETS)
def test_unapproved_owner_cannot_read_dataset(
    session: Any, sql: Any, dataset: str
) -> None:
    s = session()
    sql("UPDATE app.users SET status='pending' WHERE id=:i", i=s.user.id)
    response = s.client.get("/api/v1/securities/510981.SH/" + dataset)
    _t23.assert_err(response, 403, "ACCOUNT_NOT_APPROVED")


@pytest.mark.parametrize("dataset", DATASETS)
def test_unknown_and_old_codes_keep_master_404(
    session: Any, sql: Any, dataset: str
) -> None:
    s = session()
    _t23.seed_securities(sql)
    sql(
        "INSERT INTO market.securities (code,name,type,exchange,listing_status) "
        "VALUES ('920987.BJ','明确虚构北交所夹具','stock','BJ','listed') ON CONFLICT DO NOTHING"
    )
    sql(
        "INSERT INTO market.security_code_history (code,old_code,valid_from,source) "
        "VALUES ('920987.BJ','830987.BJ','2026-10-30','bse_code_map') ON CONFLICT DO NOTHING"
    )
    _t23.assert_err(
        s.client.get("/api/v1/securities/999999.SH/" + dataset), 404, "NOT_FOUND"
    )
    old = s.client.get("/api/v1/securities/830987.BJ/" + dataset)
    error = _t23.assert_err(old, 404, "NOT_FOUND")
    assert error["details"] == {"superseded_by": "920987.BJ"}


@pytest.mark.parametrize(
    ("dataset", "query"),
    [
        ("financials", {"limit": "41"}),
        ("financials", {"limit": "0"}),
        ("financials", {"report_period": "annual"}),
        ("financials", {"as_of": "20261101"}),
        ("fund-flows", {"days": "251"}),
        ("fund-flows", {"days": "bad"}),
        ("fund-flows", {"from": "2026-10-01"}),
        ("fund-flows", {"days": "1", "from": "2026-10-01", "to": "2026-10-02"}),
        ("fund-flows", {"from": "2026-10-02", "to": "2026-10-01"}),
        ("factors", {"trade_date": "not-a-date"}),
        ("factors", {"category": "invented"}),
        ("announcements", {"limit": "201"}),
        ("announcements", {"category": "invented"}),
        ("announcements", {"from": "2026-11-01", "to": "2026-10-01"}),
    ],
)
def test_dataset_query_bounds_still_apply(
    session: Any, sql: Any, dataset: str, query: dict[str, str]
) -> None:
    s = session()
    _t23.seed_securities(sql)
    response = s.client.get("/api/v1/securities/510981.SH/" + dataset, params=query)
    _t23.assert_err(response, 400, "VALIDATION_ERROR")


def test_announcement_invalid_cursor_is_not_hidden_by_empty_result(
    session: Any, sql: Any
) -> None:
    s = session()
    _t23.seed_securities(sql)
    response = s.client.get(
        "/api/v1/securities/510981.SH/announcements", params={"cursor": "!!bad!!"}
    )
    _t23.assert_err(response, 400, "INVALID_CURSOR")


@pytest.mark.parametrize("code", ["510981.SH", "600981.SH", "689981.SH", "000981.SH"])
@pytest.mark.parametrize("requested_date", [None, "2026-10-30"])
def test_unavailable_factor_set_has_null_version_and_no_values(
    session: Any, sql: Any, code: str, requested_date: str | None
) -> None:
    s = session()
    _t23.seed_securities(sql)
    query = {} if requested_date is None else {"trade_date": requested_date}
    response = s.client.get("/api/v1/securities/" + code + "/factors", params=query)
    assert response.status_code == 200
    body = response.json()
    assert "factor_set_version" in body and body["factor_set_version"] is None
    assert body["items"] == [] and body["counts"] == {"total": 0, "by_category": {}}
    assert body["data_status"] == "unavailable" and body["data_as_of"] is None
    assert body["trade_date"] == requested_date
    expected_reason = (
        "not_applicable" if code == "510981.SH" else "data_licence_unavailable"
    )
    assert [(gap["key"], gap["reason"]) for gap in body["gaps"]] == [
        ("factors", expected_reason)
    ]


def test_applicable_security_never_borrows_unscoped_financial_rows(
    session: Any, sql: Any
) -> None:
    s = session()
    _t23.seed_securities(sql)
    sql(
        "INSERT INTO market.financial_reports (code,report_type,period_end,payload,payload_hash) "
        "VALUES ('600981.SH','income','2026-09-30','{\"synthetic_unscoped_marker\": 9876}', 'synthetic_profile_only') "
        "ON CONFLICT DO NOTHING"
    )
    response = s.client.get("/api/v1/securities/600981.SH/financials")
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == [] and body["data_status"] == "unavailable"
    assert body["gaps"][0]["reason"] == "data_licence_unavailable"
    assert "synthetic_unscoped_marker" not in response.text
    assert "9876" not in response.text
