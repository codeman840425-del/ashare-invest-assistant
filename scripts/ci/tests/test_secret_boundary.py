"""check_secret_boundary.py 正反例 + .gitignore 拦截证书封装私钥（T-O09）。"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import check_secret_boundary as ccs
from conftest import CI_DIR, REPO

NAME = "MAIRUI_" + "LICENCE"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    shutil.copytree(REPO / "deploy/compose", tmp_path / "deploy/compose")
    shutil.copytree(REPO / "deploy/scripts", tmp_path / "deploy/scripts")
    (tmp_path / "deploy/env").mkdir(parents=True)
    shutil.copy(REPO / ccs.ENV_EXAMPLE, tmp_path / ccs.ENV_EXAMPLE)
    shutil.copytree(REPO / ".github", tmp_path / ".github")
    return tmp_path


def _sub(repo: Path, rel: str, old: str, new: str) -> None:
    p = repo / rel
    text = p.read_text(encoding="utf-8")
    assert old in text, old
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


def test_repo_is_clean(repo: Path) -> None:
    assert ccs.check(repo) == []


def test_real_repo_is_clean() -> None:
    assert ccs.check(REPO) == []


def test_cli_exit_codes(repo: Path) -> None:
    run = lambda: subprocess.run([sys.executable, str(CI_DIR / "check_secret_boundary.py"), "--repo", str(repo)],  # noqa: E731
                                 capture_output=True, text=True)
    assert run().returncode == 0
    (repo / "deploy/scripts/x.sh").write_text(f'echo "${NAME}"\n', encoding="utf-8")
    assert run().returncode == 1


@pytest.mark.parametrize("rel", ["deploy/compose/docker-compose.dev.yml", "deploy/env/.env.example",
                                 "deploy/scripts/up.sh", ".github/workflows/ci.yml"])
def test_forbidden_name_anywhere(repo: Path, rel: str) -> None:
    with (repo / rel).open("a", encoding="utf-8") as f:
        f.write(f"# {NAME}\n")
    assert any(rel in e for e in ccs.check(repo))


def test_private_secret_on_api(repo: Path) -> None:
    _sub(repo, ccs.BASE_COMPOSE, "    secrets:\n      - data_licence_seal_public_keys\n",
         "    secrets:\n      - data_licence_seal_public_keys\n      - data_licence_seal_private_keys\n")
    assert any("服务 api" in e and "data_licence_seal_private_keys" in e for e in ccs.check(repo))


def test_private_env_on_overlay_worker(repo: Path) -> None:
    (repo / "deploy/compose/docker-compose.x.yml").write_text(
        "services:\n  worker:\n    environment:\n      DATA_LICENCE_SEAL_PRIVATE_KEYS: x\n", encoding="utf-8")
    assert any("worker" in e for e in ccs.check(repo))


def test_private_env_list_form_and_volume(repo: Path) -> None:
    (repo / "deploy/compose/docker-compose.x.yml").write_text(
        "services:\n  beat:\n    environment: [\"SEAL_PRIVATE_KEY=x\"]\n    volumes: [\"/s/data_licence_seal_private_keys:/k:ro\"]\n",
        encoding="utf-8")
    errs = ccs.check(repo)
    assert sum("beat" in e for e in errs) == 2


def test_env_file_forbidden(repo: Path) -> None:
    (repo / "deploy/compose/docker-compose.x.yml").write_text(
        "services:\n  api:\n    env_file: ../env/.env\n", encoding="utf-8")
    assert any("env_file" in e for e in ccs.check(repo))


def test_secret_from_environment_forbidden(repo: Path) -> None:
    (repo / "deploy/compose/docker-compose.x.yml").write_text(
        "secrets:\n  data_licence_seal_private_keys:\n    environment: SEAL\n", encoding="utf-8")
    assert any("environment:" in e for e in ccs.check(repo))


def test_ingest_must_have_private(repo: Path) -> None:
    _sub(repo, ccs.BASE_COMPOSE, "      - data_licence_seal_private_keys\n", "")
    assert any("服务 ingest" in e for e in ccs.check(repo))


def test_env_example_private_key(repo: Path) -> None:
    with (repo / ccs.ENV_EXAMPLE).open("a", encoding="utf-8") as f:
        f.write("DATA_LICENCE_SEAL_PRIVATE_KEYS=\n")
    assert any(".env.example" in e for e in ccs.check(repo))


@pytest.mark.parametrize("path", [
    "deploy/secrets/data_licence_seal_private_keys",
    "data_licence_seal_private_keys",
    "deploy/x/data_licence_seal_public_keys",
    "backup/data_licence_seal_private_keys.20261102",
])
def test_gitignore_blocks_seal_key_files(path: str) -> None:
    r = subprocess.run(["git", "-C", str(REPO), "check-ignore", "-q", "--no-index", path])
    assert r.returncode == 0, f".gitignore 应排除 {path}"


# ---------------------------------------------------------------- 数据库角色分离（T-O10）

def test_api_on_owner_role_rejected(repo: Path) -> None:
    _sub(repo, ccs.BASE_COMPOSE, "DATABASE_URL: *db-api-url", "DATABASE_URL: postgresql+psycopg://${POSTGRES_USER:-aia}:${POSTGRES_PASSWORD:?x}@postgres:5432/aia")
    errs = ccs.check(repo)
    assert any("服务 api 的 DATABASE_URL 应为 aia_api" in e for e in errs), errs


def test_ingest_literal_password_rejected(repo: Path) -> None:
    _sub(repo, ccs.BASE_COMPOSE, "DATABASE_URL: *db-ingest-url",
         "DATABASE_URL: postgresql+psycopg://aia_ingest:" + "x" * 8 + "@postgres:5432/aia")
    assert any("服务 ingest 的 DATABASE_URL" in e for e in ccs.check(repo))


def test_overlay_cannot_switch_api_back_to_owner(repo: Path) -> None:
    (repo / "deploy/compose/docker-compose.x.yml").write_text(
        "services:\n  api:\n    environment:\n      - DATABASE_URL=postgresql://aia:${POSTGRES_PASSWORD}@postgres/aia\n",
        encoding="utf-8")
    assert any("docker-compose.x.yml: 服务 api 的 DATABASE_URL" in e for e in ccs.check(repo))


def test_db_password_secret_only_for_db_roles(repo: Path) -> None:
    (repo / "deploy/compose/docker-compose.x.yml").write_text(
        "services:\n  worker:\n    secrets: [db_password_aia_api]\n", encoding="utf-8")
    assert any("服务 worker 挂了 db_password_aia_api" in e for e in ccs.check(repo))


def test_db_password_secret_must_be_file(repo: Path) -> None:
    text = (repo / ccs.BASE_COMPOSE).read_text(encoding="utf-8")
    assert "  db_password_aia_ingest:\n    file:" in text
    _sub(repo, ccs.BASE_COMPOSE, "  db_password_aia_ingest:\n    file:", "  db_password_aia_ingest:\n    x-file:")
    assert any("顶层 secrets 缺少 db_password_aia_ingest" in e for e in ccs.check(repo))


# ---------------------------------------------------------------- aia_maint / APP_MASTER_KEY（T-O11）

def _overlay(repo: Path, text: str) -> list[str]:
    (repo / "deploy/compose/docker-compose.x.yml").write_text(text, encoding="utf-8")
    return ccs.check(repo)


def test_maint_password_only_for_db_roles_and_maint_cli(repo: Path) -> None:
    errs = _overlay(repo, "services:\n  api:\n    secrets: [db_password_aia_maint]\n")
    assert any("服务 api 挂了 db_password_aia_maint" in e for e in errs), errs
    assert _overlay(repo, "services:\n  maint-cli:\n    secrets: [db_password_aia_maint]\n") == []


def test_maint_cli_cannot_take_other_role_passwords(repo: Path) -> None:
    errs = _overlay(repo, "services:\n  maint-cli:\n    secrets: [db_password_aia_api]\n")
    assert any("服务 maint-cli 挂了 db_password_aia_api" in e for e in errs), errs


def test_maint_cli_without_owner_database_url(repo: Path) -> None:
    errs = _overlay(repo, "services:\n  maint-cli:\n    environment:\n      DATABASE_URL: postgresql://aia:x@postgres/aia\n")
    assert any("maint-cli 不得有 DATABASE_URL" in e for e in errs), errs


@pytest.mark.parametrize("key", ["AIA_MAINT_DATABASE_URL", "AIA_MAINT_DATABASE_URL_FILE"])
def test_maint_url_never_in_environment(repo: Path, key: str) -> None:
    errs = _overlay(repo, f"services:\n  api:\n    environment: [\"{key}=x\"]\n")
    assert any(key in e for e in errs), errs


def test_maint_password_secret_must_be_file(repo: Path) -> None:
    _sub(repo, ccs.BASE_COMPOSE, "  db_password_aia_maint:\n    file:", "  db_password_aia_maint:\n    x-file:")
    assert any("顶层 secrets 缺少 db_password_aia_maint" in e for e in ccs.check(repo))


@pytest.mark.parametrize("svc", ["api", "worker", "ingest"])
def test_master_key_never_in_environment(repo: Path, svc: str) -> None:
    errs = _overlay(repo, f"services:\n  {svc}:\n    environment:\n      APP_MASTER_KEY: x\n")
    assert any(f"服务 {svc} 的 environment 有 APP_MASTER_KEY" in e for e in errs), errs


def test_master_key_secret_only_api_worker(repo: Path) -> None:
    errs = _overlay(repo, "services:\n  ingest:\n    secrets: [app_master_key]\n")
    assert any("服务 ingest 挂了 app_master_key" in e for e in errs), errs


def test_master_key_secret_must_be_file_and_mounted(repo: Path) -> None:
    _sub(repo, ccs.BASE_COMPOSE, "  app_master_key:\n    file:", "  app_master_key:\n    x-file:")
    assert any("顶层 secrets 缺少 app_master_key" in e for e in ccs.check(repo))


def test_worker_must_mount_master_key(repo: Path) -> None:
    _sub(repo, ccs.BASE_COMPOSE, "    secrets:\n      - app_master_key\n    volumes:\n      - ../../config:/app/config:ro",
         "    volumes:\n      - ../../config:/app/config:ro")
    assert any("服务 worker 缺少 secrets ['app_master_key']" in e for e in ccs.check(repo))


def test_env_example_master_key_value(repo: Path) -> None:
    with (repo / ccs.ENV_EXAMPLE).open("a", encoding="utf-8") as f:
        f.write("APP_MASTER_KEY=placeholder\n")
    assert any("APP_MASTER_KEY 不得出现在 .env" in e for e in ccs.check(repo))


@pytest.mark.parametrize("path", [
    "app_master_key", "deploy/x/app_master_key", "deploy/x/db_password_aia_maint", "x/.db_password_aia_api.AbC123",
    "x/aia-maint.dsn",
])
def test_gitignore_blocks_master_key_and_role_passwords(path: str) -> None:
    r = subprocess.run(["git", "-C", str(REPO), "check-ignore", "-q", "--no-index", path])
    assert r.returncode == 0, f".gitignore 应排除 {path}"
