"""T-O12：deploy/scripts/app-master-key-backup.sh（主密钥离线备份 / 核对 / 恢复）。全部用假密钥、临时目录。"""

from __future__ import annotations

import hashlib
import os
import secrets
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "deploy/scripts/app-master-key-backup.sh"


def _env(**extra: str) -> dict[str, str]:
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp"), "AIA_APP_UID": str(os.getuid())}
    env.update(extra)
    return env


def _run(*args: str, xtrace: bool = False, **extra: str) -> subprocess.CompletedProcess[str]:
    cmd = ["bash", "-x", str(SCRIPT), *args] if xtrace else ["bash", str(SCRIPT), *args]
    return subprocess.run(cmd, capture_output=True, text=True, env=_env(**extra), timeout=60)


@pytest.fixture
def key(tmp_path: Path) -> tuple[Path, str]:
    d = tmp_path / "secrets"
    d.mkdir(mode=0o700)
    k = secrets.token_hex(32)
    f = d / "app_master_key"
    f.write_text(k, encoding="utf-8")
    f.chmod(0o600)
    return f, k


def _no_leak(r: subprocess.CompletedProcess[str], k: str) -> None:
    assert k not in r.stdout and k not in r.stderr


def test_first_statement_disables_xtrace() -> None:
    code = [ln for ln in SCRIPT.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    assert code[0] == "{ set +x; } 2>/dev/null"


def test_fingerprint_is_sha256_of_file(key: tuple[Path, str]) -> None:
    f, k = key
    r = _run("fingerprint", "--src", str(f))
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == hashlib.sha256(k.encode()).hexdigest()
    _no_leak(r, k)


def test_backup_verify_restore_roundtrip(tmp_path: Path, key: tuple[Path, str]) -> None:
    f, k = key
    off = tmp_path / "offline"
    r = _run("backup", "--dest", str(off), "--src", str(f), xtrace=True)
    assert r.returncode == 0, r.stderr
    _no_leak(r, k)
    keys = list(off.glob("app_master_key-*.key"))
    assert len(keys) == 1
    bk = keys[0]
    assert bk.read_text(encoding="utf-8") == k
    assert stat.S_IMODE(bk.stat().st_mode) == 0o600
    side = Path(str(bk) + ".sha256")
    assert stat.S_IMODE(side.stat().st_mode) == 0o600
    assert k not in side.read_text(encoding="utf-8")
    assert side.read_text(encoding="utf-8").split()[0] == hashlib.sha256(k.encode()).hexdigest()
    assert not list(off.glob(".app_master_key.*")), "临时文件应已清理"

    r = _run("verify", str(bk), "--src", str(f))
    assert r.returncode == 0 and "一致" in r.stdout
    _no_leak(r, k)

    new = tmp_path / "newhost"
    r = _run("restore", str(bk), "--dir", str(new), xtrace=True)
    assert r.returncode == 0, r.stderr
    _no_leak(r, k)
    restored = new / "app_master_key"
    assert restored.read_text(encoding="utf-8") == k
    assert stat.S_IMODE(restored.stat().st_mode) == 0o600


def test_restore_never_overwrites(tmp_path: Path, key: tuple[Path, str]) -> None:
    f, k = key
    off = tmp_path / "offline"
    assert _run("backup", "--dest", str(off), "--src", str(f)).returncode == 0
    bk = next(off.glob("*.key"))
    other = secrets.token_hex(32)
    f.write_text(other, encoding="utf-8")
    r = _run("restore", str(bk), "--dir", str(f.parent))
    assert r.returncode == 3 and "不覆盖" in r.stderr
    assert f.read_text(encoding="utf-8") == other
    _no_leak(r, k)
    _no_leak(r, other)


def test_verify_detects_wrong_key_and_corruption(tmp_path: Path, key: tuple[Path, str]) -> None:
    f, k = key
    off = tmp_path / "offline"
    assert _run("backup", "--dest", str(off), "--src", str(f)).returncode == 0
    bk = next(off.glob("*.key"))
    wrong = tmp_path / "wrong"
    wrong.write_text(secrets.token_hex(32), encoding="utf-8")
    r = _run("verify", str(bk), "--src", str(wrong))
    assert r.returncode == 1 and "不一致" in r.stdout
    with bk.open("a", encoding="utf-8") as fh:
        fh.write("x")
    r = _run("verify", str(bk), "--src", str(f))
    assert r.returncode == 4 and "损坏" in r.stderr
    r = _run("restore", str(bk), "--dir", str(tmp_path / "n2"))
    assert r.returncode == 4 and not (tmp_path / "n2" / "app_master_key").exists()


@pytest.mark.parametrize("case", ["relative", "in_repo", "secrets_dir", "with_dump"])
def test_backup_refuses_bad_destinations(tmp_path: Path, key: tuple[Path, str], case: str) -> None:
    f, k = key
    if case == "relative":
        dest = "offline"
    elif case == "in_repo":
        dest = str(REPO / "deploy/backups")
    elif case == "secrets_dir":
        dest = str(f.parent)
    else:
        d = tmp_path / "dumps"
        d.mkdir()
        (d / "aia-20261101T000000Z.dump").write_bytes(b"")
        dest = str(d)
    r = _run("backup", "--dest", dest, "--src", str(f))
    assert r.returncode == 2, r.stdout + r.stderr
    _no_leak(r, k)
    if case == "in_repo":
        assert not list((REPO / "deploy/backups").glob("app_master_key-*")) if (REPO / "deploy/backups").exists() else True


def test_backup_refuses_short_or_missing_source(tmp_path: Path) -> None:
    short = tmp_path / "short"
    short.write_text("abc", encoding="utf-8")
    r = _run("backup", "--dest", str(tmp_path / "o"), "--src", str(short))
    assert r.returncode == 3 and not list((tmp_path / "o").glob("*.key"))
    r = _run("backup", "--dest", str(tmp_path / "o"), "--src", str(tmp_path / "missing"))
    assert r.returncode == 3


def test_unknown_subcommand_and_args() -> None:
    assert _run().returncode == 2
    assert _run("rotate").returncode == 2
    assert _run("fingerprint", "--bogus", "x").returncode == 2


def test_drill_passes_and_cleans_up() -> None:
    r = _run("drill")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "drill：全部通过" in r.stdout
    for n in range(1, 10):
        assert f"\n{n} " in "\n" + r.stdout
