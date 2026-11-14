"""Synthetic public master terms; scripted connections are not real database verification."""

from __future__ import annotations

import socket
from dataclasses import asdict
from types import SimpleNamespace
from typing import Any

import pytest
from app.master.terms import Term, generate, initials, rebuild

CODE = "600000.SH"
OLD_CODE = "830001.BJ"


@pytest.fixture(autouse=True)
def deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(*args: Any, **kwargs: Any) -> None:
        pytest.fail("master terms attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(socket, "create_connection", reject)


class StubResult:
    def __init__(self, rows: Any = ()) -> None:
        self.rows = rows

    def all(self) -> Any:
        return self.rows

    def scalars(self) -> StubResult:
        return self


class ScriptedConnection:
    """Return queued results and record calls; no persistence or constraint claims."""

    def __init__(self, *results: StubResult | None) -> None:
        self.results = iter(results)
        self.calls: list[tuple[Any, Any]] = []

    def execute(self, statement: Any, parameters: Any = None) -> StubResult | None:
        self.calls.append((statement, parameters))
        try:
            return next(self.results)
        except StopIteration as error:
            raise AssertionError("unexpected database call") from error

    def assert_done(self) -> None:
        assert list(self.results) == []


def db_tuple(term: Term) -> tuple[Any, ...]:
    return (
        term.term_kind,
        term.term,
        term.source_name,
        term.is_st_stripped,
        term.variant_rank,
        term.generator_version,
    )


def sql_text(call: tuple[Any, Any]) -> str:
    return str(call[0]).lstrip().upper()


def test_initials_phrase_reading_stays_first_when_capped() -> None:
    assert initials("重庆银行", maximum=1) == ["CQYH"]
    assert initials("重庆银行", maximum=2) == ["CQYH", "ZQYX"]


def test_initials_heteronym_product_is_deterministic_and_capped_at_sixteen() -> None:
    assert initials("重重重重重", maximum=3) == ["CCCCZ", "ZZZZZ", "ZZZZC"]
    rows = initials("重重重重重", maximum=100)
    assert len(rows) == 16
    assert len(set(rows)) == 16
    assert rows[0] == "CCCCZ"


def test_initials_nfkc_and_non_han_chunks_keep_searchable_ascii() -> None:
    assert initials("ＡI股1") == ["AIG1"]
    assert initials("A-1") == ["A1"]


def test_initials_empty_and_invalid_limit() -> None:
    assert initials("") == []
    with pytest.raises(ValueError, match="initials maximum must be positive"):
        initials("合成", 0)


def test_generate_five_declared_kinds_and_st_stripped_variants() -> None:
    rows = generate("*ST示例", ["旧示例"], ["830094.BJ"], maximum=3)
    assert len(rows) == 13
    assert rows == sorted(rows)
    assert {row.term_kind for row in rows} == {
        "name",
        "name_initials",
        "former_name",
        "former_initials",
        "former_code",
    }
    assert any(row.term == "STSL" and not row.is_st_stripped for row in rows)
    assert any(row.term == "SL" and row.is_st_stripped for row in rows)
    assert any(row.term == "示例" and row.is_st_stripped for row in rows)
    assert any(
        row.term_kind == "former_code"
        and row.term == "830094"
        and row.source_name == "830094.BJ"
        for row in rows
    )
    assert len({(row.term_kind, row.term, row.source_name) for row in rows}) == len(
        rows
    )
    assert all(
        row.term.isalnum() and row.term.isascii() and row.term == row.term.upper()
        for row in rows
        if row.term_kind in {"name_initials", "former_initials"}
    )


def test_generate_skips_blank_and_normalized_duplicate_former_names() -> None:
    rows = generate("合成", ["合成", ""])
    assert {row.term_kind for row in rows} == {"name", "name_initials"}
    assert [row.term for row in rows if row.term_kind == "name"] == ["合成"]
    assert generate("", ["", "  "]) == []


def test_generate_empty_stripped_form_and_duplicate_old_code_are_safe() -> None:
    rows = generate("退", old_codes=[OLD_CODE, OLD_CODE])
    assert not any(row.is_st_stripped for row in rows)
    assert len([row for row in rows if row.term_kind == "former_code"]) == 1


@pytest.mark.parametrize("code", ["830001.SH", "830001", "830001.BJ.extra"])
def test_generate_rejects_non_bse_or_malformed_former_codes(code: str) -> None:
    with pytest.raises(ValueError, match="invalid former BSE code"):
        generate("合成", old_codes=[code])


def test_generate_propagates_invalid_initials_limit() -> None:
    with pytest.raises(ValueError, match="initials maximum must be positive"):
        generate("合成", maximum=0)


@pytest.mark.parametrize("codes", [["bad"], ["600000.SH", "12345.SH"], ["600000.XX"]])
def test_rebuild_rejects_invalid_security_code_before_any_database_call(
    codes: list[str],
) -> None:
    conn = ScriptedConnection()
    with pytest.raises(ValueError, match="invalid security code"):
        rebuild(conn, codes)  # type: ignore[arg-type]
    assert conn.calls == []


def test_rebuild_rejects_invalid_limit_before_any_database_call() -> None:
    conn = ScriptedConnection()
    with pytest.raises(ValueError, match="initials maximum must be positive"):
        rebuild(conn, maximum=0)  # type: ignore[arg-type]
    assert conn.calls == []


def test_rebuild_empty_selection_has_no_writes() -> None:
    conn = ScriptedConnection(StubResult([]))
    assert rebuild(conn, []) == {"securities": 0, "changed_securities": 0, "terms": 0}  # type: ignore[arg-type]
    conn.assert_done()
    assert len(conn.calls) == 1
    assert "FOR UPDATE" in sql_text(conn.calls[0])


def test_rebuild_unchanged_rows_do_not_rewrite_terms() -> None:
    row = SimpleNamespace(code=CODE, name="合成银行")
    former_names = ["往日合成"]
    old_codes = [OLD_CODE]
    expected = generate(row.name, former_names, old_codes, maximum=4)
    existing = [db_tuple(term) for term in reversed(expected)]
    conn = ScriptedConnection(
        StubResult([row]),
        StubResult(),
        StubResult(former_names),
        StubResult(old_codes),
        StubResult(existing),
    )

    assert rebuild(conn, [CODE, CODE], maximum=4) == {  # type: ignore[arg-type]
        "securities": 1,
        "changed_securities": 0,
        "terms": len(expected),
    }
    conn.assert_done()
    assert len(conn.calls) == 5
    assert not any(
        sql_text(call).startswith(("DELETE", "INSERT")) for call in conn.calls
    )
    assert conn.calls[1][1] == {"code": CODE}


def test_rebuild_changed_rows_delete_then_insert_generated_terms() -> None:
    row = SimpleNamespace(code=CODE, name="合成银行")
    expected = generate(row.name, maximum=2)
    conn = ScriptedConnection(
        StubResult([row]),
        StubResult(),
        StubResult([]),
        StubResult([]),
        StubResult([]),
        None,
        None,
    )

    assert rebuild(conn, maximum=2) == {  # type: ignore[arg-type]
        "securities": 1,
        "changed_securities": 1,
        "terms": len(expected),
    }
    conn.assert_done()
    assert len(conn.calls) == 7
    assert sql_text(conn.calls[-2]).startswith("DELETE")
    assert sql_text(conn.calls[-1]).startswith("INSERT")
    assert conn.calls[-1][1] == [{"code": CODE, **asdict(term)} for term in expected]


def test_rebuild_changed_empty_expected_deletes_without_insert() -> None:
    row = SimpleNamespace(code=CODE, name=" ")
    old = Term("name", "旧名", "旧名")
    conn = ScriptedConnection(
        StubResult([row]),
        StubResult(),
        StubResult([]),
        StubResult([]),
        StubResult([db_tuple(old)]),
        None,
    )

    assert rebuild(conn, [CODE]) == {
        "securities": 1,
        "changed_securities": 1,
        "terms": 0,
    }  # type: ignore[arg-type]
    conn.assert_done()
    assert len(conn.calls) == 6
    assert sql_text(conn.calls[-1]).startswith("DELETE")
    assert not any(sql_text(call).startswith("INSERT") for call in conn.calls)
