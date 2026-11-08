"""T-O19：前端接入网关的正反例。不构建、不连网。"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import check_frontend_deploy as cfd
from conftest import REPO

FILES = (
    "deploy/nginx/nginx.conf",
    "deploy/compose/docker-compose.yml",
    "deploy/docker/frontend.Dockerfile",
)


def _tree(tmp_path: Path) -> Path:
    for rel in FILES:
        dest = tmp_path / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / rel, dest)
    return tmp_path


def _sub(repo: Path, rel: str, old: str, new: str) -> None:
    p = repo / rel
    text = p.read_text(encoding="utf-8")
    assert old in text, old
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


def test_repo_is_clean() -> None:
    assert cfd.check(REPO) == []


def test_placeholder_rejected(tmp_path: Path) -> None:
    repo = _tree(tmp_path)
    _sub(repo, "deploy/nginx/nginx.conf", "try_files $uri /index.html;",
         'return 200 "ashare-invest-assistant placeholder (frontend not built yet)\\n";')
    errs = cfd.check(repo)
    assert any("占位" in e for e in errs), errs


def test_assets_must_not_fall_back_to_spa(tmp_path: Path) -> None:
    repo = _tree(tmp_path)
    _sub(repo, "deploy/nginx/nginx.conf", "try_files $uri =404;", "try_files $uri /index.html;")
    errs = cfd.check(repo)
    assert any("/assets/" in e for e in errs), errs


def test_api_must_not_serve_index(tmp_path: Path) -> None:
    repo = _tree(tmp_path)
    _sub(repo, "deploy/nginx/nginx.conf", "proxy_pass http://$aia_api_upstream;",
         "try_files $uri /index.html;")
    errs = cfd.check(repo)
    assert any("/api/" in e for e in errs), errs


def test_host_network_rejected(tmp_path: Path) -> None:
    repo = _tree(tmp_path)
    _sub(repo, "deploy/compose/docker-compose.yml", "    restart: unless-stopped\n    ports:\n      - \"127.0.0.1:${NGINX_HTTP_PORT:-8080}:80\"\n",
         "    network_mode: host\n    restart: unless-stopped\n    ports:\n      - \"127.0.0.1:${NGINX_HTTP_PORT:-8080}:80\"\n")
    errs = cfd.check(repo)
    assert any("host 网络" in e for e in errs), errs


def test_dockerfile_rejects_secret_and_full_copy(tmp_path: Path) -> None:
    repo = _tree(tmp_path)
    df = repo / "deploy/docker/frontend.Dockerfile"
    df.write_text(df.read_text(encoding="utf-8") + "COPY . /src\nENV APP_MASTER_KEY=x\n", encoding="utf-8")
    errs = cfd.check(repo)
    assert any("整目录" in e for e in errs), errs
    assert any("APP_MASTER_KEY" in e for e in errs), errs


def test_master_volume_still_required(tmp_path: Path) -> None:
    repo = _tree(tmp_path)
    _sub(repo, "deploy/compose/docker-compose.yml", "master:${MASTER_SNAPSHOT_PATH:-/var/lib/aia-dev/master}", "imports:${IMPORT_STORAGE_PATH:-/var/lib/aia-dev/imports}")
    errs = cfd.check(repo)
    assert any("master 快照卷" in e for e in errs), errs


@pytest.mark.parametrize("needle", ["MAIRUI_", "PASSWORD"])
def test_dockerfile_rejects_runtime_names(tmp_path: Path, needle: str) -> None:
    repo = _tree(tmp_path)
    df = repo / "deploy/docker/frontend.Dockerfile"
    df.write_text(df.read_text(encoding="utf-8") + f"\n# {needle}nope\n", encoding="utf-8")
    errs = cfd.check(repo)
    assert any(needle in e for e in errs), errs


def test_missing_static_root_rejected(tmp_path: Path) -> None:
    repo = _tree(tmp_path)
    _sub(repo, "deploy/nginx/nginx.conf", "    root /usr/share/nginx/html;\n", "")
    errs = cfd.check(repo)
    assert any("root /usr/share/nginx/html" in e for e in errs), errs


def test_wrong_static_root_rejected(tmp_path: Path) -> None:
    repo = _tree(tmp_path)
    _sub(repo, "deploy/nginx/nginx.conf", "root /usr/share/nginx/html;", "root /etc/nginx/html;")
    errs = cfd.check(repo)
    assert any("root /usr/share/nginx/html" in e for e in errs), errs


def test_location_root_override_rejected(tmp_path: Path) -> None:
    repo = _tree(tmp_path)
    _sub(repo, "deploy/nginx/nginx.conf", "location / {\n      try_files $uri /index.html;",
         "location / {\n      root /tmp/not-the-image;\n      try_files $uri /index.html;")
    errs = cfd.check(repo)
    assert any("location / 不得另行指定 root" in e for e in errs), errs


def test_asset_404_must_not_use_default_page(tmp_path: Path) -> None:
    repo = _tree(tmp_path)
    _sub(repo, "deploy/nginx/nginx.conf", "      error_page 404 @assets_missing;\n", "")
    errs = cfd.check(repo)
    assert any("@assets_missing" in e for e in errs), errs


def test_asset_404_body_must_stay_empty(tmp_path: Path) -> None:
    repo = _tree(tmp_path)
    _sub(repo, "deploy/nginx/nginx.conf", 'return 404 "not found\\n";', 'return 404 "<html>nginx</html>";')
    errs = cfd.check(repo)
    assert any("404 正文" in e for e in errs), errs
