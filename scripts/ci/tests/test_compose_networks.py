"""check_compose_networks.py 正反例（T-O68：只让 ingest 出网；发布端口走无伪装 edge）。"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import check_compose_networks as ccn
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
    assert ccn.check(REPO) == []


def test_cli_exit_codes(repo: Path) -> None:
    run = lambda: subprocess.run(  # noqa: E731
        [sys.executable, str(CI_DIR / "check_compose_networks.py"), "--repo", str(repo)],
        capture_output=True,
        text=True,
    )
    assert run().returncode == 0
    _sub(repo, BASE, "      aia_egress:\n", "")
    r = run()
    assert r.returncode == 1 and "compose-networks" in r.stdout


def test_worker_on_egress_rejected(repo: Path) -> None:
    _sub(
        repo,
        BASE,
        "  worker:\n    logging: *default-logging\n    networks:\n      aia_internal:\n",
        "  worker:\n    logging: *default-logging\n    networks:\n      aia_internal:\n      aia_egress:\n",
    )
    errs = ccn.check(repo)
    assert any("worker" in e and "aia_egress" in e and "不得接入" in e for e in errs), errs


def test_ingest_must_join_egress(repo: Path) -> None:
    _sub(
        repo,
        BASE,
        "  ingest:\n    logging: *default-logging\n    networks:\n      aia_internal:\n      aia_egress:\n",
        "  ingest:\n    logging: *default-logging\n    networks:\n      aia_internal:\n",
    )
    errs = ccn.check(repo)
    assert any("ingest" in e and "必须挂 aia_egress" in e for e in errs), errs


def test_service_without_internal_rejected(repo: Path) -> None:
    _sub(
        repo,
        BASE,
        "  beat:\n    logging: *default-logging\n    networks:\n      aia_internal:\n",
        "  beat:\n    logging: *default-logging\n",
    )
    errs = ccn.check(repo)
    assert any("beat" in e and "必须挂 aia_internal" in e for e in errs), errs


def test_list_form_networks_rejected(repo: Path) -> None:
    _sub(
        repo,
        BASE,
        "  api:\n    logging: *default-logging\n    networks:\n      aia_internal:\n",
        "  api:\n    logging: *default-logging\n    networks: [aia_internal]\n",
    )
    errs = ccn.check(repo)
    assert any("api" in e and "必须是映射" in e for e in errs), errs


def test_default_not_internal_rejected(repo: Path) -> None:
    _sub(
        repo,
        BASE,
        "  default:\n    name: ${AIA_VOLUME_PREFIX:?请用 deploy/scripts/compose.sh 调用}_default\n    internal: true\n",
        "  default:\n    name: ${AIA_VOLUME_PREFIX:?请用 deploy/scripts/compose.sh 调用}_default\n",
    )
    errs = ccn.check(repo)
    assert any("networks.default" in e and "internal: true" in e for e in errs), errs


def test_edge_masquerade_must_be_off(repo: Path) -> None:
    _sub(
        repo,
        BASE,
        '      com.docker.network.bridge.enable_ip_masquerade: "false"\n',
        '      com.docker.network.bridge.enable_ip_masquerade: "true"\n',
    )
    errs = ccn.check(repo)
    assert any("enable_ip_masquerade" in e for e in errs), errs


def test_nginx_must_join_edge(repo: Path) -> None:
    _sub(
        repo,
        BASE,
        "  nginx:\n    logging: *default-logging\n    networks:\n      aia_internal:\n      aia_edge:\n",
        "  nginx:\n    logging: *default-logging\n    networks:\n      aia_internal:\n",
    )
    errs = ccn.check(repo)
    assert any("nginx" in e and ("必须挂 aia_edge" in e or "发布了 ports" in e) for e in errs), errs


def test_dev_postgres_ports_require_edge(repo: Path) -> None:
    _sub(
        repo,
        DEV,
        "  postgres:\n    logging: *default-logging\n    # 与基础文件的 aia_internal 合并（映射式，不会冲掉内部网）。\n    networks:\n      aia_edge:\n    ports:\n",
        "  postgres:\n    logging: *default-logging\n    ports:\n",
    )
    errs = ccn.check(repo)
    assert any("postgres" in e and "发布了 ports" in e for e in errs), errs


def test_overlay_cannot_put_api_on_egress(repo: Path) -> None:
    _sub(
        repo,
        DEV,
        "  api:\n    logging: *default-logging\n",
        "  api:\n    logging: *default-logging\n    networks:\n      aia_egress:\n",
    )
    errs = ccn.check(repo)
    assert any("api" in e and "aia_egress" in e and "不得接入" in e for e in errs), errs


def test_new_service_without_networks_rejected(repo: Path) -> None:
    (repo / "deploy/compose/docker-compose.extra.yml").write_text(
        "x-logging: &default-logging\n"
        "  driver: json-file\n"
        "  options:\n    max-size: \"10m\"\n    max-file: \"5\"\n"
        "services:\n  newsvc:\n    image: busybox\n    logging: *default-logging\n",
        encoding="utf-8",
    )
    errs = ccn.check(repo)
    assert any("newsvc" in e and "必须挂 aia_internal" in e for e in errs), errs


def test_overlay_cannot_declare_unregistered_network_on_worker(repo: Path) -> None:
    """T-A96 M12：覆盖层新声明非 internal 网（如 pub）并挂到 worker，必须报错。"""
    (repo / "deploy/compose/docker-compose.extra.yml").write_text(
        "networks:\n"
        "  pub: {}\n"
        "services:\n"
        "  worker:\n"
        "    networks:\n"
        "      pub:\n",
        encoding="utf-8",
    )
    errs = ccn.check(repo)
    assert any("未登记" in e and "pub" in e for e in errs), errs


def test_nginx_ports_must_bind_localhost(repo: Path) -> None:
    _sub(
        repo,
        BASE,
        '"127.0.0.1:${NGINX_HTTP_PORT:-8080}:80"',
        '"${NGINX_HTTP_PORT:-8080}:80"',
    )
    errs = ccn.check(repo)
    assert any("nginx" in e and "127.0.0.1" in e for e in errs), errs
