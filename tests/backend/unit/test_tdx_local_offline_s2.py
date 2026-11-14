"""Synthetic TDX bytes and temporary audit files; no sample assets, DB or transport."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import socket
import struct
from collections import Counter
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from app.ingest import tdx_local as tdx

DAY = dt.date(2026, 1, 5)
NOW = dt.datetime(2026, 1, 10, 12, tzinfo=dt.UTC)
CODE = "999991.SH"


@pytest.fixture(autouse=True)
def deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def deny(*_args: object, **_kwargs: object) -> None:
        pytest.fail("offline TDX checks must never open a socket")

    monkeypatch.setattr(socket.socket, "connect", deny)


def daily(day: dt.date = DAY, **changes: Any) -> bytes:
    row = {
        "date": int(day.strftime("%Y%m%d")),
        "open": 1000,
        "high": 1100,
        "low": 900,
        "close": 1050,
        "amount": 1000.0,
        "volume": 100,
        "reserved": 0,
    }
    row.update(changes)
    return struct.pack("<IIIIIfII", *row.values())


def minute(**changes: Any) -> bytes:
    row = {
        "date": tdx.encode_lc_date(DAY),
        "minute": 571,
        "open": 10.0,
        "high": 11.0,
        "low": 9.0,
        "close": 10.5,
        "amount": 1000.0,
        "volume": 100,
        "reserved": 0,
    }
    row.update(changes)
    return struct.pack("<HHfffffII", *row.values())


def tree(tmp_path: Path, kind: str = "day") -> tuple[Path, Path, Path]:
    root, audit = tmp_path / "root", tmp_path / "audit"
    audit.mkdir()
    for market in tdx.MARKETS:
        (root / market / tdx.KIND_DIR[kind]).mkdir(parents=True)
    path = root / "sh" / tdx.KIND_DIR[kind] / ("sh999991" + tdx.KIND_SUFFIX[kind])
    path.write_bytes(daily() if kind == "day" else minute())
    return root, audit, path


def run(root: Path, audit: Path, **changes: Any) -> tdx.RunReport:
    options = {
        "root": root,
        "audit_dir": audit,
        "kind": "day",
        "start": None,
        "until_for": lambda _code: DAY + dt.timedelta(days=10),
        "normalize": lambda raw: raw[2:] + "." + raw[:2],
        "security_of": lambda _code: ("stock", "listed"),
        "scope_codes": None,
        "existing_for": lambda _code, _bars: {},
        "writer": None,
        "now": NOW,
        "run_id": "first",
        "compare_amount": True,
    }
    options.update(changes)
    return tdx.run_import(**options)


def test_binary_layout_and_real_decoder_values() -> None:
    (bar,) = tdx.parse_day_bytes(CODE, daily()).bars
    assert (bar.code, bar.trade_date, bar.ts) == (CODE, DAY, None)
    assert (bar.open, bar.high, bar.low, bar.close) == tuple(
        map(Decimal, (10, 11, 9, "10.5"))
    )
    assert (bar.volume, bar.amount) == (Decimal(100), Decimal("1000.0000"))
    for kind in ("lc1", "lc5"):
        (parsed,) = tdx.parse_lc_bytes(CODE, minute(), kind).bars
        assert parsed.ts == dt.datetime(2026, 1, 5, 9, 31, tzinfo=tdx.BEIJING)
        assert replace(parsed, ts=None) == bar
        assert tdx.bar_key(parsed) == parsed.ts
    assert tdx.bar_key(bar) == DAY
    assert tdx.decode_lc_date(tdx.encode_lc_date(dt.date(2024, 2, 29))) == dt.date(
        2024, 2, 29
    )


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"date": 20261301}, "invalid_date"),
        ({"amount": float("nan")}, "non_finite"),
        ({"amount": float("inf")}, "non_finite"),
        ({"amount": 1e20}, "out_of_range"),
        ({"amount": 1e35}, "out_of_range"),
        ({"open": 0}, "zero_price"),
        ({"high": 999}, "high_low_conflict"),
    ],
)
def test_daily_rejects_only_invalid_record(
    changes: dict[str, Any], reason: str
) -> None:
    result = tdx.parse_day_bytes(CODE, daily(**changes) + daily())
    assert result.rejected == Counter({reason: 1})
    assert len(result.bars) == 1
    assert result.bars[0].trade_date == DAY


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"date": 0}, "invalid_date"),
        ({"minute": 0}, "invalid_minute"),
        ({"minute": 1441}, "invalid_minute"),
        ({"high": float("inf")}, "non_finite"),
        ({"amount": float("nan")}, "non_finite"),
        ({"high": 1e20}, "out_of_range"),
        ({"amount": 1e20}, "out_of_range"),
        ({"low": 0}, "zero_price"),
        ({"close": 12.0}, "high_low_conflict"),
    ],
)
def test_minute_rejects_only_invalid_record(
    changes: dict[str, Any], reason: str
) -> None:
    result = tdx.parse_lc_bytes(CODE, minute(**changes) + minute(), "lc1")
    assert result.rejected == Counter({reason: 1})
    assert len(result.bars) == 1


def test_truncated_files_and_wrong_minute_kind() -> None:
    assert tdx.parse_day_bytes(CODE, daily() + b"x").rejected == {"truncated_file": 1}
    assert tdx.parse_lc_bytes(CODE, minute() + b"x", "lc5").rejected == {
        "truncated_file": 1
    }
    with pytest.raises(ValueError, match="lc1 or lc5"):
        tdx.parse_lc_bytes(CODE, minute(), "day")


def test_file_unit_check_exact_five_percent_boundary() -> None:
    (bar,) = tdx.parse_day_bytes(CODE, daily()).bars
    bad = replace(bar, amount=Decimal(100000))
    assert not tdx.unit_suspect([bad] + [bar] * 19)
    assert tdx.unit_suspect([bad] + [bar] * 18)
    assert not tdx.unit_suspect([replace(bad, volume=Decimal(0))])
    assert not tdx.unit_suspect([])


def test_scan_filters_before_opening_and_keeps_sorted_relative_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _audit, selected = tree(tmp_path)
    names = [
        "notes.txt",
        "invalid.day",
        "sz999992.day",
        "sh999992.day",
        "sh999993.day",
        "sh999994.day",
        "sh999995.day",
        "sh999996.day",
    ]
    for name in names:
        (selected.parent / name).write_bytes(b"not a bar")
    (selected.parent / "folder.day").mkdir()
    normalized: list[str] = []

    def normalize(raw: str) -> str:
        normalized.append(raw)
        if raw == "SH999992":
            raise ValueError("synthetic normalization refusal")
        return raw[2:] + ".SH"

    statuses = {
        "999993.SH": None,
        "999994.SH": ("etf", "listed"),
        "999995.SH": ("stock", "delisted"),
    }

    def no_read(_self: Path) -> bytes:
        pytest.fail("scan must not read even a selected file")

    monkeypatch.setattr(Path, "read_bytes", no_read)
    result = tdx.scan(
        root,
        "day",
        normalize=normalize,
        security_of=lambda code: statuses.get(code, ("stock", "listed")),
        scope_codes=frozenset({CODE}),
    )
    assert [candidate.rel for candidate in result.files] == ["sh/lday/sh999991.day"]
    assert result.skipped == {
        "not_target_file": 2,
        "name_invalid": 2,
        "normalize_failed": 1,
        "non_a_share": 2,
        "not_listed": 1,
        "out_of_scope": 1,
    }
    assert normalized == [
        "SH999991",
        "SH999992",
        "SH999993",
        "SH999994",
        "SH999995",
        "SH999996",
    ]


def test_kind_directories_case_and_missing_market(tmp_path: Path) -> None:
    root = tmp_path / "case"
    (root / "SH" / "LDAY").mkdir(parents=True)
    with pytest.raises(tdx.TdxRefused, match="root_missing:sz/lday"):
        tdx.kind_dirs(root, "day")
    assert tdx.kind_dirs(root, "day", exclude={"sz", "bj"}) == {
        "sh": root / "SH" / "LDAY"
    }
    with pytest.raises(tdx.TdxRefused, match="root_missing:sh/lday"):
        tdx.kind_dirs(tmp_path / "missing", "day")


def test_manifest_roundtrip_change_summary_and_latest_selection(tmp_path: Path) -> None:
    _root, audit, path = tree(tmp_path)
    candidate = tdx.Candidate(CODE, "sh", "sh/lday/sh999991.day", path)
    first = tdx.build_manifest([candidate], gaps=["bj/lday"])
    assert first.entries[0].sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert first.entries[0].size == 32
    assert tdx.parse_manifest(first.text) == first
    path.write_bytes(daily() + daily(DAY + dt.timedelta(days=1)))
    second = tdx.build_manifest([candidate])
    assert tdx.compare_manifests(first, second) == {
        "added": 0,
        "removed": 0,
        "changed": 1,
    }
    assert tdx.compare_manifests(first, tdx.build_manifest([])) == {
        "added": 0,
        "removed": 1,
        "changed": 0,
    }
    assert tdx.compare_manifests(tdx.build_manifest([]), first) == {
        "added": 1,
        "removed": 0,
        "changed": 0,
    }
    assert tdx.latest_manifest(audit, "day") is None
    (audit / "tdx-day-manifest-20260101T000000-a.txt").write_text(first.text)
    (audit / "tdx-day-manifest-20260102T000000-b.txt").write_text(second.text)
    (audit / "tdx-lc1-manifest-20260103T000000-c.txt").write_text("invalid")
    (audit / "unrelated.txt").write_text("invalid")
    assert tdx.latest_manifest(audit, "day") == (
        "tdx-day-manifest-20260102T000000-b.txt",
        second,
    )


@pytest.mark.parametrize(
    "body,tail", [("", "files=0"), ("bad\n", "files=0"), ("a\t1\tx\n", "files=2")]
)
def test_invalid_manifest_structure_is_not_accepted(body: str, tail: str) -> None:
    digest = hashlib.sha256(body.encode()).hexdigest()
    text = body + f"{tail}\tmanifest_sha256={digest}\n"
    if not body and tail == "files=0":
        assert tdx.parse_manifest("") is None
        assert tdx.parse_manifest(text.replace(digest, "0" * 64)) is None
    else:
        assert tdx.parse_manifest(text) is None


def test_audit_refuses_nested_missing_or_nonwritable_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, audit, _path = tree(tmp_path)
    for invalid in (root, root / "nested"):
        with pytest.raises(tdx.TdxRefused, match="audit_dir_inside_root"):
            tdx.check_audit_dir(root, invalid)
    with pytest.raises(tdx.TdxRefused, match="audit_dir_not_writable"):
        tdx.check_audit_dir(root, tmp_path / "absent")
    monkeypatch.setattr(tdx.os, "access", lambda *_: False)
    with pytest.raises(tdx.TdxRefused, match="audit_dir_not_writable"):
        tdx.check_audit_dir(root, audit)


def test_import_output_bounds_and_rerun_manifest_use_real_writer_path(
    tmp_path: Path,
) -> None:
    root, audit, path = tree(tmp_path)
    path.write_bytes(b"".join(daily(DAY + dt.timedelta(days=n)) for n in range(4)))
    written: list[tdx.TdxBar] = []

    def writer(bars: list[tdx.TdxBar]) -> int:
        written.extend(bars)
        return len(bars)

    report = run(
        root,
        audit,
        start=DAY + dt.timedelta(days=1),
        until_for=lambda _code: DAY + dt.timedelta(days=2),
        writer=writer,
    )
    assert (report.parsed_rows, report.before_from, report.after_until) == (4, 1, 1)
    assert (report.would_insert, report.inserted, report.status) == (2, 2, "ok")
    assert [bar.trade_date for bar in written] == [
        DAY + dt.timedelta(days=n) for n in (1, 2)
    ]
    manifest = tdx.parse_manifest((audit / report.manifest_name).read_text())
    assert manifest and manifest.sha256 == report.manifest_sha256
    (summary,) = [
        json.loads(line)
        for line in (audit / report.reconcile_name).read_text().splitlines()
    ]
    assert summary == {
        "summary": True,
        "overlap_keys": 0,
        "mismatch_keys": 0,
        "mismatch_items": 0,
        "mismatch_rate": 0.0,
        "amount_compared": True,
    }
    dry = run(root, audit, run_id="second", until_for=lambda _code: None)
    assert dry.after_until == 4 and dry.inserted == 0
    assert dry.rerun == {"added": 0, "removed": 0, "changed": 0}
    assert dry.previous_manifest == report.manifest_name
    assert dry.stats()["mode"] == "dry-run"
    assert report.stats()["mode"] == "apply"


def test_existing_overlap_is_reported_but_never_sent_to_writer(tmp_path: Path) -> None:
    root, audit, _path = tree(tmp_path)
    existing = tdx.ExistingBar(
        "mairui",
        Decimal(10),
        Decimal(11),
        Decimal(9),
        None,
        Decimal(100),
        Decimal(1002),
    )
    sent: list[object] = []
    report = run(
        root,
        audit,
        existing_for=lambda _code, _bars: {DAY: existing},
        writer=lambda bars: sent.extend(bars) or len(bars),
    )
    rows = [
        json.loads(line)
        for line in (audit / report.reconcile_name).read_text().splitlines()
    ]
    assert sent == [] and report.inserted == 0
    assert (report.overlap_rows, report.conflicts) == (1, 1)
    assert [row["field"] for row in rows[:-1]] == ["close", "amount"]
    assert rows[0]["existing_value"] is None
    assert rows[1]["tolerance"] == "1"
    assert rows[-1]["mismatch_items"] == 2 and rows[-1]["mismatch_rate"] == 1.0
    (bar,) = tdx.parse_day_bytes(CODE, daily()).bars
    exact = replace(existing, close=bar.close, amount=Decimal(1001))
    assert tdx.reconcile(bar, exact, compare_amount=True) == []
    assert tdx.reconcile(bar, replace(exact, amount=None), compare_amount=False) == []
    assert (
        tdx.reconcile(bar, replace(exact, amount=None), compare_amount=True)[0][
            "existing_value"
        ]
        is None
    )


def test_import_rejects_unit_suspect_and_changed_file_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, audit, path = tree(tmp_path)
    path.write_bytes(daily(amount=100000.0))
    report = run(root, audit)
    assert report.status == "partial" and report.rejected_files == {"unit_suspect": 1}
    assert report.issues == [f"tdx_unit_suspect:{CODE}"]
    path.write_bytes(daily())
    original = Path.read_bytes

    def changed(self: Path) -> bytes:
        result = original(self)
        return result + daily() if self == path else result

    monkeypatch.setattr(Path, "read_bytes", changed)
    altered = run(root, audit, run_id="changed")
    assert altered.status == "partial" and altered.rejected_files == {
        "changed_during_import": 1
    }
    assert altered.issues == [f"tdx_file_changed:{CODE}"]
    assert altered.would_insert == 0


def test_minute_import_scope_gap_and_invalid_previous_manifest(tmp_path: Path) -> None:
    root, audit, _path = tree(tmp_path, "lc1")
    (audit / "tdx-lc1-manifest-20260101T000000-old.txt").write_text("broken")
    result = run(root, audit, kind="lc1", compare_amount=False, exclude={"bj"})
    assert result.would_insert == 1 and result.inserted == 0
    assert result.issues == [
        "tdx_scope_excluded:bj/minline",
        "tdx_previous_manifest_invalid",
    ]
    assert (
        "gap\tbj/minline\texcluded_by_scope"
        in (audit / result.manifest_name).read_text()
    )
    assert not list(audit.glob("*.part"))
    with pytest.raises(ValueError, match="timezone-aware"):
        run(root, audit, now=NOW.replace(tzinfo=None))


def test_writer_failure_removes_only_its_partial_reconciliation(tmp_path: Path) -> None:
    root, audit, _path = tree(tmp_path)

    def failed_writer(_bars: list[tdx.TdxBar]) -> int:
        raise RuntimeError("synthetic writer failure")

    with pytest.raises(RuntimeError, match="synthetic writer failure"):
        run(root, audit, writer=failed_writer)
    assert len(list(audit.glob("*manifest*.txt"))) == 1
    assert not list(audit.glob("*reconcile*"))


def test_manifest_replace_failure_cleans_created_part_but_preserves_preexisting_part(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, audit, _path = tree(tmp_path)

    def failed_replace(_source: Path, _destination: Path) -> None:
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(tdx.os, "replace", failed_replace)
    with pytest.raises(OSError, match="synthetic replace failure"):
        run(root, audit)
    assert list(audit.iterdir()) == []
    part = audit / "tdx-day-manifest-20260110T200000-first.txt.part"
    part.write_text("preexisting sentinel")
    with pytest.raises(FileExistsError):
        run(root, audit)
    assert part.read_text() == "preexisting sentinel"
