# ruff: noqa: S101
"""T-B115: T-O66b path constants + T-A85 B-2 leftover temp must not permanent-halt.

Paths injected via tmp_path — never writes real /run/aia.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from app.ingest import daily_lists as ingest
from app.master import daily_delivery as daily

ROOT = Path(__file__).resolve().parents[3]


def test_tb115_o66b_path_constants() -> None:
    assert ingest.TEMP == Path("/run/aia/tmp/mairui-daily.tmp"), (
        f"TEMP still old path: {ingest.TEMP} (baseline red / T-O66b)"
    )
    assert ingest.HALT == Path("/run/aia/state/halt/mairui-daily.HALTED"), (
        f"HALT still old path: {ingest.HALT}"
    )
    assert daily.AUTHORIZATION == Path("/run/aia/receipts/mairui-daily.json"), (
        f"AUTHORIZATION still old path: {daily.AUTHORIZATION}"
    )
    # Old locations must be gone from source
    dl = (ROOT / "src/backend/app/ingest/daily_lists.py").read_text(encoding="utf-8")
    dd = (ROOT / "src/backend/app/master/daily_delivery.py").read_text(encoding="utf-8")
    assert "/run/aia/mairui-daily.tmp" not in dl
    assert "/run/aia/mairui-daily.HALTED" not in dl
    assert "/run/aia/authorizations/" not in dd


def test_tb115_b2_leftover_temp_is_replaced_not_halt(tmp_path: Path) -> None:
    """SIGKILL residue at temp path must not raise FileExistsError / permanent halt."""
    temp = tmp_path / "mairui-daily.tmp"
    # Simulate leftover (never print content in assertions beyond length/mode)
    stale = b"STALE-RESIDUE-DO-NOT-LOG"
    temp.write_bytes(stale)
    temp.chmod(0o600)
    assert temp.exists()

    marker = "fresh-credential-material-tb115"
    identity = ingest.temporary(temp, marker)
    try:
        st = temp.stat()
        assert stat.S_ISREG(st.st_mode)
        assert stat.S_IMODE(st.st_mode) == 0o600
        # Content replaced; do not echo to stdout
        assert temp.read_bytes() == marker.encode()
        assert temp.read_bytes() != stale
        assert identity == (st.st_dev, st.st_ino)
    finally:
        ingest.remove_owned(temp, identity)
        assert not temp.exists()


def test_tb115_b2_nonregular_temp_refused(tmp_path: Path) -> None:
    temp = tmp_path / "mairui-daily.tmp"
    target = tmp_path / "other"
    target.write_text("x", encoding="utf-8")
    temp.symlink_to(target)
    with pytest.raises(ingest.DailyHaltError, match="temp_path_not_regular"):
        ingest.temporary(temp, "should-not-write")
    # Symlink still present; target untouched
    assert temp.is_symlink()
    assert target.read_text(encoding="utf-8") == "x"


def test_tb115_halt_flag_not_auto_cleared(tmp_path: Path) -> None:
    """Clearing leftover temp must never remove an existing halt flag."""
    halt = tmp_path / "state" / "halt" / "mairui-daily.HALTED"
    halt.parent.mkdir(parents=True)
    halt.write_bytes(b"limit_103_or_429")
    halt.chmod(0o600)

    temp = tmp_path / "tmp" / "mairui-daily.tmp"
    temp.parent.mkdir(parents=True)
    temp.write_bytes(b"stale")
    temp.chmod(0o600)

    identity = ingest.temporary(temp, "new")
    try:
        assert halt.exists(), "halt flag must remain (never auto-cleared)"
        assert halt.read_bytes() == b"limit_103_or_429"
    finally:
        ingest.remove_owned(temp, identity)
    assert halt.exists()


def test_tb115_no_write_to_receipts_dir(tmp_path: Path) -> None:
    """Application must not create/write under the receipts directory."""
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    # Make receipts dir non-writable to the process (best-effort; skip if root)
    if os.geteuid() == 0:
        pytest.skip("running as root; chmod refusal not meaningful")
    receipts.chmod(0o555)
    receipt = receipts / "mairui-daily.json"

    # Source: daily_lists / daily_delivery must not open AUTHORIZATION for write
    dl = (ROOT / "src/backend/app/ingest/daily_lists.py").read_text(encoding="utf-8")
    dd = (ROOT / "src/backend/app/master/daily_delivery.py").read_text(encoding="utf-8")
    assert "O_WRONLY" not in dd or "AUTHORIZATION" not in dd.split("O_WRONLY")[0][-200:]
    # read_grant uses O_RDONLY only
    assert "O_RDONLY" in dd
    assert "os.open(path, os.O_RDONLY" in dd or "O_RDONLY | os.O_NOFOLLOW" in dd

    # Runtime: attempting to write receipt path must fail; our modules don't do it.
    # Prove no file appears after temporary() + halt create elsewhere.
    halt = tmp_path / "state" / "halt" / "mairui-daily.HALTED"
    halt.parent.mkdir(parents=True)
    temp = tmp_path / "tmp" / "mairui-daily.tmp"
    temp.parent.mkdir(parents=True)
    identity = ingest.temporary(temp, "x")
    try:
        fd = os.open(halt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.write(fd, b"limit_103_or_429")
        os.close(fd)
    finally:
        ingest.remove_owned(temp, identity)

    assert list(receipts.iterdir()) == [], "receipts dir must stay empty (no app writes)"
    assert not receipt.exists()
    # halt is under state/, not receipts — allowed
    assert halt.exists()
