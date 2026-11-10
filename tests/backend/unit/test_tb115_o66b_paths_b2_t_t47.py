# ruff: noqa: S101
"""T-T47 / T-B115：T-O66b 路径常量 + B-2 残留临时文件语义（tmp_path，不碰真实 /run）。"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from app.ingest import daily_lists as ingest
from app.master import daily_delivery as daily

ROOT = Path(__file__).resolve().parents[3]


def test_tb115_o66b_path_constants_match_to66b() -> None:
    assert ingest.TEMP == Path("/run/aia/tmp/mairui-daily.tmp")
    assert ingest.HALT == Path("/run/aia/state/halt/mairui-daily.HALTED")
    assert daily.AUTHORIZATION == Path("/run/aia/receipts/mairui-daily.json")
    dl = (ROOT / "src/backend/app/ingest/daily_lists.py").read_text(encoding="utf-8")
    dd = (ROOT / "src/backend/app/master/daily_delivery.py").read_text(encoding="utf-8")
    assert "/run/aia/mairui-daily.tmp" not in dl
    assert "/run/aia/mairui-daily.HALTED" not in dl
    assert "/run/aia/authorizations/" not in dd


def test_tb115_b2_leftover_regular_temp_replaced(tmp_path: Path) -> None:
    temp = tmp_path / "mairui-daily.tmp"
    stale = b"STALE-RESIDUE-DO-NOT-LOG"
    temp.write_bytes(stale)
    temp.chmod(0o600)
    marker = "fresh-credential-material-tt47"
    identity = ingest.temporary(temp, marker)
    try:
        st = temp.stat()
        assert stat.S_ISREG(st.st_mode)
        assert stat.S_IMODE(st.st_mode) == 0o600
        assert temp.read_bytes() == marker.encode()
        assert temp.read_bytes() != stale
        assert identity == (st.st_dev, st.st_ino)
    finally:
        ingest.remove_owned(temp, identity)
        assert not temp.exists()


def test_tb115_b2_symlink_temp_refused(tmp_path: Path) -> None:
    temp = tmp_path / "mairui-daily.tmp"
    target = tmp_path / "other"
    target.write_text("x", encoding="utf-8")
    temp.symlink_to(target)
    with pytest.raises(ingest.DailyHaltError, match="temp_path_not_regular"):
        ingest.temporary(temp, "should-not-write")
    assert temp.is_symlink()
    assert target.read_text(encoding="utf-8") == "x"


def test_tb115_b2_directory_temp_refused(tmp_path: Path) -> None:
    temp = tmp_path / "mairui-daily.tmp"
    temp.mkdir()
    with pytest.raises(ingest.DailyHaltError, match="temp_path_not_regular"):
        ingest.temporary(temp, "should-not-write")
    assert temp.is_dir()


def test_tb115_halt_flag_not_auto_cleared(tmp_path: Path) -> None:
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
        assert halt.exists()
        assert halt.read_bytes() == b"limit_103_or_429"
    finally:
        ingest.remove_owned(temp, identity)
    assert halt.exists()


def test_tb115_code_does_not_write_receipts_dir(tmp_path: Path) -> None:
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    if os.geteuid() == 0:
        pytest.skip("root 下 chmod 拒写无意义")
    receipts.chmod(0o555)

    dd = (ROOT / "src/backend/app/master/daily_delivery.py").read_text(encoding="utf-8")
    assert "O_RDONLY" in dd
    assert "os.open(path, os.O_RDONLY" in dd or "O_RDONLY | os.O_NOFOLLOW" in dd

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

    assert list(receipts.iterdir()) == []
    assert not (receipts / "mairui-daily.json").exists()
    assert halt.exists()
