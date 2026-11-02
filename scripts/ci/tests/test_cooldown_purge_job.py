"""deploy/docker/cooldown-purge.py（T-B10 部署项）：调用后端函数、心跳与健康检查、失败不打印连接串。"""

from __future__ import annotations

import importlib.util
import os
import sys
import time
import types
from pathlib import Path

import pytest

from conftest import REPO

SCRIPT = REPO / "deploy/docker/cooldown-purge.py"


@pytest.fixture
def job(monkeypatch: pytest.MonkeyPatch):
    calls: list[object] = []
    svc = types.ModuleType("app.licences.service")

    def purge(conn):  # 只记录被调用，返回删除行数
        calls.append(conn)
        if getattr(conn, "boom", False):
            raise RuntimeError("postgresql://aia_api:SECRETPW@postgres/aia")
        return 3

    svc.purge_expired_cooldowns = purge
    monkeypatch.setitem(sys.modules, "app", types.ModuleType("app"))
    monkeypatch.setitem(sys.modules, "app.licences", types.ModuleType("app.licences"))
    monkeypatch.setitem(sys.modules, "app.licences.service", svc)
    spec = importlib.util.spec_from_file_location("cooldown_purge", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.calls = calls
    return mod


class _Engine:
    def __init__(self, boom: bool = False) -> None:
        self.conn = types.SimpleNamespace(boom=boom)

    def begin(self):
        eng = self

        class _Ctx:
            def __enter__(self):
                return eng.conn

            def __exit__(self, *a):
                return False

        return _Ctx()


def test_run_once_calls_backend_function_and_beats(job, tmp_path: Path, capsys) -> None:
    hb = tmp_path / "hb"
    assert job.run_once(_Engine(), hb) is True
    assert len(job.calls) == 1 and hb.exists()
    assert '"purged": 3' in capsys.readouterr().out


def test_run_once_failure_hides_dsn_and_no_beat(job, tmp_path: Path, capsys) -> None:
    hb = tmp_path / "hb"
    assert job.run_once(_Engine(boom=True), hb) is False
    out = capsys.readouterr().out
    assert not hb.exists()
    assert "RuntimeError" in out and "SECRETPW" not in out and "postgresql://" not in out


def test_main_requires_database_url(job, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert job.main() == 2


@pytest.mark.parametrize(("age", "rc"), [(None, 1), (10, 0), (2 * 3600 + 30, 0), (2 * 3600 + 120, 1)])
def test_healthcheck_heartbeat_age(job, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, age, rc) -> None:
    hb = tmp_path / "hb"
    monkeypatch.setenv("AIA_COOLDOWN_PURGE_HEARTBEAT", str(hb))
    monkeypatch.setenv("AIA_COOLDOWN_PURGE_INTERVAL_S", "3600")
    if age is not None:
        hb.touch()
        t = time.time() - age
        os.utime(hb, (t, t))
    assert job.healthcheck() == rc


def test_interval_floor_is_60s(job, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hb = tmp_path / "hb"
    hb.touch()
    t = time.time() - 170  # 间隔被抬到 60 → 阈值 180 秒
    os.utime(hb, (t, t))
    monkeypatch.setenv("AIA_COOLDOWN_PURGE_HEARTBEAT", str(hb))
    monkeypatch.setenv("AIA_COOLDOWN_PURGE_INTERVAL_S", "5")
    assert job.healthcheck() == 0


def test_backend_dir_put_on_sys_path(job, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 以脚本方式运行时 sys.path[0] 是脚本目录：必须把后端目录（WORKDIR）补进去，否则 import app 失败
    monkeypatch.setattr(sys, "path", [p for p in sys.path])
    monkeypatch.setenv("AIA_BACKEND_DIR", str(tmp_path))
    job._backend_on_path()
    assert sys.path[0] == str(tmp_path)
