# ruff: noqa: S101
"""Preparation gates use only synthetic files/responses, never public or private market rows."""

from __future__ import annotations

import io
import struct
import zipfile
from pathlib import Path

import pytest

from retest.t_r58 import prepare_hf, prepare_tdx


def bundle(path: Path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)


def test_tb136_html_response_never_becomes_ready_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        prepare_tdx.urllib.request, "urlopen",
        lambda *a, **kw: io.BytesIO(b"<script>synthetic</script>"),
    )
    with pytest.raises(ValueError, match="non-ZIP"):
        prepare_tdx.prepare(tmp_path)
    assert (tmp_path / "hsjday.zip.part").exists()
    assert not (tmp_path / "hsjday.zip").exists()
    assert not (tmp_path / "T-B136-tdx-manifest.json").exists()


def test_tb136_archive_cannot_write_outside_destination(tmp_path: Path) -> None:
    bundle(tmp_path / "hsjday.zip", {"../outside.bin": b"synthetic"})
    with pytest.raises(ValueError, match="outside"):
        prepare_tdx.prepare(tmp_path)
    assert not (tmp_path / "outside.bin").exists()


def test_tb136_existing_extracted_file_is_preserved(tmp_path: Path) -> None:
    bundle(tmp_path / "hsjday.zip", {"sh/lday/synthetic.day": b"new"})
    target = tmp_path / "hsjday" / "sh" / "lday" / "synthetic.day"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"existing")
    with pytest.raises(ValueError, match="preserve"):
        prepare_tdx.prepare(tmp_path)
    assert target.read_bytes() == b"existing"


def test_tb136_daily_coverage_before_cutoff_cannot_be_ready(tmp_path: Path) -> None:
    row = struct.pack("<IIIIIfII", 20261109, 1000, 1000, 1000, 1000, 0.0, 0, 0)
    bundle(tmp_path / "hsjday.zip", {f"sh/lday/{s}.day": row
                                    for s in ("sh000001", "sh000300")})
    bundle(tmp_path / "gbbq.zip", {"gbbq": b"synthetic"})
    with pytest.raises(ValueError, match="does not cover"):
        prepare_tdx.prepare(tmp_path)
    assert not (tmp_path / "T-B136-tdx-manifest.json").exists()


def test_tb136_raw_sha_list_cannot_read_outside_root(tmp_path: Path) -> None:
    listing = tmp_path / "expected.txt"
    listing.write_text("0" * 64 + " ../outside\n", encoding="utf-8")
    with pytest.raises(ValueError, match="outside"):
        prepare_hf.verify_raw(tmp_path / "raw", listing)


def test_tb136_incomplete_raw_sha_list_stops_before_conversion(tmp_path: Path) -> None:
    listing = tmp_path / "expected.txt"
    listing.write_text("0" * 64 + " file\n", encoding="utf-8")
    with pytest.raises(ValueError, match="5801 unique"):
        prepare_hf.verify_raw(tmp_path / "raw", listing)


def test_tb136_raw_sha_missing_files_are_not_success(tmp_path: Path) -> None:
    listing = tmp_path / "expected.txt"
    listing.write_text("".join("0" * 64 + f" file-{i}\n" for i in range(5801)), encoding="utf-8")
    with pytest.raises(ValueError, match="conversion forbidden"):
        prepare_hf.verify_raw(tmp_path / "raw", listing)
