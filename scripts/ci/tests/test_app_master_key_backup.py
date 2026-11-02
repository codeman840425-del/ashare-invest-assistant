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
    (tmp_path / "src").mkdir()   # 源文件单独目录：--dest 不能在密钥目录里（m2）
    short = tmp_path / "src" / "short"
    short.write_text("abc", encoding="utf-8")
    r = _run("backup", "--dest", str(tmp_path / "o"), "--src", str(short))
    assert r.returncode == 3 and not list((tmp_path / "o").glob("*.key"))
    r = _run("backup", "--dest", str(tmp_path / "o"), "--src", str(tmp_path / "src" / "missing"))
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


# ---------- T-A04 ⑧：评审 b195ca6 M1 / m1 / m2 / n1 / n2 ----------

def _backup(tmp_path: Path, f: Path) -> Path:
    off = tmp_path / "offline"
    assert _run("backup", "--dest", str(off), "--src", str(f)).returncode == 0
    return next(off.glob("*.key"))


def test_restore_without_sidecar_requires_expect(tmp_path: Path, key: tuple[Path, str]) -> None:
    f, k = key
    bk = _backup(tmp_path, f)
    Path(str(bk) + ".sha256").unlink()
    r = _run("restore", str(bk), "--dir", str(tmp_path / "n1"))
    assert r.returncode == 2 and "--expect-sha256" in r.stderr, r.stderr
    assert not (tmp_path / "n1" / "app_master_key").exists()
    r = _run("restore", str(bk), "--dir", str(tmp_path / "n2"), "--expect-sha256", hashlib.sha256(b"other").hexdigest())
    assert r.returncode == 4 and "台账" in r.stderr and not (tmp_path / "n2" / "app_master_key").exists()
    good = hashlib.sha256(k.encode()).hexdigest()
    r = _run("restore", str(bk), "--dir", str(tmp_path / "n3"), "--expect-sha256", good.upper(), xtrace=True)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "n3" / "app_master_key").read_text(encoding="utf-8") == k
    _no_leak(r, k)


def test_restore_swapped_backup_and_sidecar_caught_by_ledger(tmp_path: Path, key: tuple[Path, str]) -> None:
    f, k = key
    bk = _backup(tmp_path, f)
    ledger = hashlib.sha256(k.encode()).hexdigest()
    other = secrets.token_hex(32)
    bk.write_text(other, encoding="utf-8")   # 备份与 .sha256 一起换成另一把：备份自洽
    Path(str(bk) + ".sha256").write_text(f"{hashlib.sha256(other.encode()).hexdigest()}  {bk.name}\n", encoding="utf-8")
    r = _run("restore", str(bk), "--dir", str(tmp_path / "n1"))
    assert r.returncode == 0 and "--expect-sha256" in r.stderr   # 不带台账值：只能做到自洽，并提醒
    r = _run("restore", str(bk), "--dir", str(tmp_path / "n2"), "--expect-sha256", ledger)
    assert r.returncode == 4 and not (tmp_path / "n2" / "app_master_key").exists()
    _no_leak(r, other)


@pytest.mark.parametrize("bad", ["abc", "g" * 64, "0" * 63])
def test_restore_expect_must_be_hex64(tmp_path: Path, key: tuple[Path, str], bad: str) -> None:
    f, _ = key
    bk = _backup(tmp_path, f)
    r = _run("restore", str(bk), "--dir", str(tmp_path / "n"), "--expect-sha256", bad)
    assert r.returncode == 2 and not (tmp_path / "n").exists()


def test_restore_chown_failure_is_fatal(tmp_path: Path, key: tuple[Path, str]) -> None:
    f, k = key
    bk = _backup(tmp_path, f)
    fake = tmp_path / "fakebin"
    fake.mkdir()
    for name in ("sudo", "chown"):
        (fake / name).write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        (fake / name).chmod(0o755)
    target = tmp_path / "n"
    r = _run("restore", str(bk), "--dir", str(target), PATH=f"{fake}:{os.environ['PATH']}", AIA_APP_UID="65534")
    assert r.returncode == 5, r.stdout + r.stderr
    assert not (target / "app_master_key").exists()
    assert not list(target.glob(".app_master_key.*")), "临时文件应已清理"
    _no_leak(r, k)


@pytest.mark.parametrize("case", ["secrets_subdir", "dump_in_subdir", "dump_in_parent", "symlink_into_repo"])
def test_backup_refuses_bad_destinations_m2(tmp_path: Path, key: tuple[Path, str], case: str) -> None:
    f, k = key
    if case == "secrets_subdir":
        dest = f.parent / "sub"
    elif case == "dump_in_subdir":
        dest = tmp_path / "o1"
        (dest / "db").mkdir(parents=True)
        (dest / "db" / "aia-20261101T000000Z.dump").write_bytes(b"")
    elif case == "dump_in_parent":
        (tmp_path / "aia-20261101T000000Z.dump").write_bytes(b"")
        dest = tmp_path / "o2"
    else:
        dest = tmp_path / "link"
        dest.symlink_to(REPO / "deploy")
    r = _run("backup", "--dest", str(dest), "--src", str(f))
    assert r.returncode == 2, r.stdout + r.stderr
    _no_leak(r, k)
    if case == "symlink_into_repo":
        assert not list((REPO / "deploy").glob("app_master_key-*"))
    elif case == "secrets_subdir":
        assert not dest.exists()


def test_backup_new_dest_is_700(tmp_path: Path, key: tuple[Path, str]) -> None:
    f, _ = key
    off = tmp_path / "fresh" / "offline"
    assert _run("backup", "--dest", str(off), "--src", str(f)).returncode == 0
    assert stat.S_IMODE(off.stat().st_mode) == 0o700
