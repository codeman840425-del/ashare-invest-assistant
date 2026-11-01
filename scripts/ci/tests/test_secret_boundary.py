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
    "x/seal_private_keys.json",
])
def test_gitignore_blocks_seal_key_files(path: str) -> None:
    r = subprocess.run(["git", "-C", str(REPO), "check-ignore", "-q", "--no-index", path])
    assert r.returncode == 0, f".gitignore 应排除 {path}"
