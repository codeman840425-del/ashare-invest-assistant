"""check_compose_logging.py 正反例（T-A04 ③：所有容器 json-file 日志轮转，统一锚点）。"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import check_compose_logging as ccl
from conftest import CI_DIR, REPO

BASE = "deploy/compose/docker-compose.yml"
DEV = "deploy/compose/docker-compose.dev.yml"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    shutil.copytree(REPO / "deploy/compose", tmp_path / "deploy/compose")
    return tmp_path


def _sub(repo: Path, rel: str, old: str, new: str, count: int = 1) -> None:
    p = repo / rel
    text = p.read_text(encoding="utf-8")
    assert old in text, old
    p.write_text(text.replace(old, new, count), encoding="utf-8")


def test_real_repo_is_clean() -> None:
    assert ccl.check(REPO) == []


def test_every_service_has_rotation() -> None:
    import yaml
    for rel in (BASE, DEV):
        doc = yaml.safe_load((REPO / rel).read_text(encoding="utf-8"))
        for name, svc in doc["services"].items():
            lg = svc["logging"]
            assert lg["driver"] == "json-file", (rel, name)
            assert lg["options"] == {"max-size": "10m", "max-file": "5"}, (rel, name)


def test_cli_exit_codes(repo: Path) -> None:
    run = lambda: subprocess.run([sys.executable, str(CI_DIR / "check_compose_logging.py"), "--repo", str(repo)],  # noqa: E731
                                 capture_output=True, text=True)
    assert run().returncode == 0
    _sub(repo, BASE, "    logging: *default-logging\n", "")
    r = run()
    assert r.returncode == 1 and "compose-logging" in r.stdout


@pytest.mark.parametrize("rel", [BASE, DEV])
def test_service_without_logging_rejected(repo: Path, rel: str) -> None:
    _sub(repo, rel, "    logging: *default-logging\n", "")
    assert any("没有配置 logging" in e for e in ccl.check(repo))


def test_new_service_without_logging_rejected(repo: Path) -> None:
    (repo / "deploy/compose/docker-compose.extra.yml").write_text(
        'x-logging: &default-logging\n  driver: json-file\n  options:\n    max-size: "10m"\n    max-file: "5"\n'
        "services:\n  newsvc:\n    image: busybox\n", encoding="utf-8")
    errs = ccl.check(repo)
    assert any("服务 newsvc 没有配置 logging" in e for e in errs), errs


def test_overlay_without_anchor_rejected(repo: Path) -> None:
    (repo / "deploy/compose/docker-compose.extra.yml").write_text(
        "services:\n  api:\n    logging:\n      driver: json-file\n", encoding="utf-8")
    errs = ccl.check(repo)
    assert any("缺少顶层 x-logging" in e for e in errs), errs
    assert any("服务 api" in e and "缺少 options" in e for e in errs), errs


def test_inline_logging_differs_from_anchor_rejected(repo: Path) -> None:
    _sub(repo, BASE, "  api:\n    logging: *default-logging\n",
         '  api:\n    logging:\n      driver: json-file\n      options:\n        max-size: "50m"\n        max-file: "3"\n')
    errs = ccl.check(repo)
    assert any("服务 api 的 logging 与 x-logging 不一致" in e for e in errs), errs


@pytest.mark.parametrize(("old", "new", "needle"), [
    ("driver: json-file", "driver: local", "logging.driver 必须是 json-file"),
    ("driver: json-file", "driver: none", "logging.driver 必须是 json-file"),
    ('max-size: "10m"', 'max-size: "1g"', "max-size 必须是 1m–100m"),
    ('max-size: "10m"', 'max-size: "500k"', "max-size 必须是 1m–100m"),
    ('max-size: "10m"', "max-size: 10", "max-size 必须是 1m–100m"),
    ('max-file: "5"', 'max-file: "1"', "max-file 必须是 2–20"),
    ('max-file: "5"', "max-file: 5", "max-file 必须是 2–20"),
    ('    max-size: "10m"\n', "", "max-size 必须是 1m–100m"),
])
def test_bad_policy_rejected(repo: Path, old: str, new: str, needle: str) -> None:
    _sub(repo, BASE, old, new)
    errs = ccl.check(repo)
    assert any(needle in e for e in errs), errs


def test_dev_cannot_change_rotation(repo: Path) -> None:
    _sub(repo, DEV, 'max-file: "5"', 'max-file: "10"')
    errs = ccl.check(repo)
    assert any("x-logging 不一致" in e for e in errs), errs


def test_anchor_name_required(repo: Path) -> None:
    _sub(repo, BASE, "x-logging: &default-logging", "x-logging: &logs")
    _sub(repo, BASE, "*default-logging", "*logs", count=-1)
    errs = ccl.check(repo)
    assert any("必须定义为锚点 &default-logging" in e for e in errs), errs


def test_reset_tag_reported_not_crash(repo: Path) -> None:
    (repo / "deploy/compose/docker-compose.extra.yml").write_text(
        "services:\n  api:\n    logging: !reset null\n", encoding="utf-8")
    errs = ccl.check(repo)
    assert errs
