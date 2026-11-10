# ruff: noqa: S101
"""T-T62：临时库名校验与非 o61 端口拒绝（monkeypatch 模拟，不连 o55）。"""

from __future__ import annotations

import pytest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pg_o61 import (  # noqa: E402
    DEFAULT_TEMPLATE_DB,
    InvalidTempDbName,
    PgOwnershipError,
    require_o61_pg,
    template_db_name,
    validate_temp_db_name,
)


def test_template_db_name_default_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TT_O61_TEMPLATE_DB", raising=False)
    assert template_db_name({}) == DEFAULT_TEMPLATE_DB
    assert template_db_name({"TT_O61_TEMPLATE_DB": "o61_tmp_0030"}) == "o61_tmp_0030"
    assert template_db_name({"TT_O61_TEMPLATE_DB": "tt51_tpl"}) == "tt51_tpl"
    with pytest.raises(InvalidTempDbName):
        template_db_name({"TT_O61_TEMPLATE_DB": "o55_p2_verify"})
    with pytest.raises(InvalidTempDbName):
        template_db_name({"TT_O61_TEMPLATE_DB": "postgres"})
    with pytest.raises(InvalidTempDbName):
        validate_temp_db_name("o61_tmp_0030;drop")
    with pytest.raises(InvalidTempDbName):
        validate_temp_db_name("template1")


def test_require_o61_pg_refuses_non_o61_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    """端口归属不是 o61-pg 时必须拒绝；用模拟归属，不连接 o55 或其他实例。"""
    monkeypatch.setattr(
        "pg_o61.lookup_tcp_owner",
        lambda host, port: ("o55-p2-pg", "monkeypatch 模拟，未连接该实例"),
    )
    with pytest.raises(PgOwnershipError) as ei:
        require_o61_pg("127.0.0.1", 55494)
    msg = str(ei.value)
    assert "o61-pg" in msg
    assert "o55-p2-pg" in msg
    assert "拒绝建库" in msg


def test_require_o61_pg_accepts_o61_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pg_o61.lookup_tcp_owner",
        lambda host, port: ("o61-pg", "monkeypatch 模拟"),
    )
    assert require_o61_pg("127.0.0.1", 55461) == "o61-pg"
